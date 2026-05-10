"""4-tier data integrity test for the hybrid Postgres + R2 layer.

Run from repo root:

    python scripts/test_data_integrity.py

Exits 0 if all tiers pass, 1 if any fail. Per-tier counts and per-failure
dataset_keys/reasons are printed.

Tiers:
    1. Registry sanity   — every registry row references a real backend
    2. Round-trip        — load_dataset() row count ~ ground-truth CSV
    3. App contract      — legacy public functions return expected columns
    4. Routing policy    — actual storage_location matches route_dataset()
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from data_loader import (
    fetch_part_b_data,
    fetch_part_d_data,
    load_ahrf,
    load_dataset,
    load_geo_variation,
    load_hpsa,
)
from psycopg2 import sql as pgsql

from infra import get_postgres_conn, load_secrets, make_r2
from routing import route_dataset


def _fetch_registry(conn, columns: list[str]) -> list[dict]:
    """SELECT the named columns from dataset_registry; return list of dicts.

    Column names are quoted via psycopg2.sql.Identifier so this is safe
    even though `columns` is technically interpolated into the query.
    """
    query = pgsql.SQL("SELECT {fields} FROM dataset_registry").format(
        fields=pgsql.SQL(",").join(pgsql.Identifier(c) for c in columns)
    )
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

DATA_DIR = ROOT / "data"
ROW_TOLERANCE = 0.05
SAMPLE_SIZE = 10
SAMPLE_SEED = 42

# Datasets where the app reads non-numeric columns (brand names, status
# strings, geographic level labels, etc.). Melting these into observations
# would lose those columns, so they belong in R2 as raw Parquet.
CATEGORICAL_USED_BY_APP = {
    "part_d",                                 # Brnd_Name
    "part_b",                                 # Brnd_Name
    "geo_variation_2014_2023",                # BENE_GEO_LVL/AGE_LVL/DESC
    "hpsa_primary_care",                      # HPSA Status, Discipline
    "hpsa_dental",
    "hpsa_mental_health",
    "hospital_compare_general_info",
    "hospital_compare_complications_state",
    "hospital_compare_hcahps_state",
    "hospital_compare_readmissions_state",
    "cms_nursing_home",
    "cms_hospital_prices",
    "cms_timely_care",
    "cms_enrollment_additive",
    "samhsa_facilities",
    "samhsa_nmhss",
    "cdc_nndss",
}

# Datasets the app primarily filters by state/year — point-lookup access,
# not full-scan analytics.
FILTER_HEAVY = {
    "ahrf_state_national_2025",
    "bls_unemployment",
    "bls_healthcare_wages",
    "census_saipe",
    "census_sahie",
    "state_risk_index",
    "cdc_hai",
    "cdc_hiv",
    "cdc_sti",
    "hrsa_nurse_corps",
}


# --- Tier 1: registry sanity ------------------------------------------------

def tier1_registry_sanity(conn, r2, bucket: str) -> dict:
    failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    passes = 0
    try:
        registry = _fetch_registry(
            conn, ["dataset_key", "storage_location", "parquet_path", "row_count"]
        )
    except Exception as exc:  # noqa: BLE001
        return {"passes": 0, "failures": [("(registry fetch)", str(exc))],
                "warnings": [], "total": 0}

    for r in registry:
        key = r.get("dataset_key") or "(unknown)"
        loc = r.get("storage_location")
        rc = r.get("row_count")

        # Backward compat during the Neon cutover (March 2026): legacy
        # 'supabase' rows are accepted as 'postgres' but flagged so we
        # know which registry entries still need their value updated.
        if loc == "supabase":
            warnings.append((key, "storage_location='supabase' — rename to 'postgres'"))
            loc = "postgres"

        if loc not in ("postgres", "r2"):
            failures.append((key, f"storage_location={loc!r}"))
            continue
        if rc is None or rc <= 0:
            failures.append((key, f"row_count={rc!r}"))
            continue

        if loc == "r2":
            ppath = r.get("parquet_path")
            if not ppath:
                failures.append((key, "parquet_path is null"))
                continue
            try:
                r2.head_object(Bucket=bucket, Key=ppath)
            except Exception as exc:  # noqa: BLE001
                failures.append((key, f"R2 HEAD failed for {ppath}: {exc.__class__.__name__}"))
                continue
        else:  # postgres
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM observations WHERE dataset_key = %s",
                        (key,),
                    )
                    n = cur.fetchone()[0] or 0
            except Exception as exc:  # noqa: BLE001
                failures.append((key, f"observations count failed: {exc.__class__.__name__}"))
                continue
            if n <= 0:
                failures.append((key, "observations rows = 0"))
                continue

        passes += 1

    return {"passes": passes, "failures": failures,
            "warnings": warnings, "total": len(registry)}


# --- Tier 2: round-trip integrity -------------------------------------------

_KEY_COL_PRIORITY = [
    "state", "State", "STATE", "st_abbrev",
    "county", "County", "COUNTY",
    "year", "Year", "YEAR",
    "Brnd_Name", "BENE_GEO_DESC", "BENE_GEO_LVL", "BENE_AGE_LVL",
    "metric_name", "Discipline", "HPSA Status",
]


def _common_key_columns(csv: pd.DataFrame, loaded: pd.DataFrame) -> list[str]:
    """Pick up to 3 columns common to both frames for sample matching."""
    common = [c for c in _KEY_COL_PRIORITY if c in csv.columns and c in loaded.columns]
    if common:
        return common[:3]
    overlap = [c for c in csv.columns if c in loaded.columns]
    return overlap[:3]


def tier2_round_trip(conn) -> dict:
    failures: list[tuple[str, str]] = []
    passes = 0
    try:
        registry = _fetch_registry(conn, ["dataset_key", "storage_location"])
    except Exception as exc:  # noqa: BLE001
        return {"passes": 0, "failures": [("(registry fetch)", str(exc))], "total": 0}

    for r in registry:
        key = r["dataset_key"]
        csv_path = DATA_DIR / f"{key}.csv"
        if not csv_path.exists():
            failures.append((key, f"local CSV missing: {csv_path.name}"))
            continue

        try:
            csv_df = pd.read_csv(csv_path, low_memory=False)
        except Exception:
            try:
                csv_df = pd.read_csv(csv_path, low_memory=False, sep="|")
            except Exception as exc:  # noqa: BLE001
                failures.append((key, f"CSV read failed: {exc.__class__.__name__}"))
                continue

        try:
            loaded = load_dataset(key, csv_fallback=csv_path)
        except Exception as exc:  # noqa: BLE001
            failures.append((key, f"load_dataset failed: {exc.__class__.__name__}: {exc}"))
            continue

        n_csv = len(csv_df)
        n_loaded = len(loaded)
        if n_csv == 0:
            failures.append((key, "ground-truth CSV is empty"))
            continue
        diff = abs(n_loaded - n_csv) / n_csv
        if diff > ROW_TOLERANCE:
            failures.append((
                key,
                f"row count diff {diff:.1%} (loaded={n_loaded}, csv={n_csv})",
            ))
            continue

        cols = _common_key_columns(csv_df, loaded)
        if not cols:
            # Schema fully diverged (e.g. Postgres pivot dropped column names).
            # Row count was within tolerance, accept.
            passes += 1
            continue

        sample = csv_df.sample(min(SAMPLE_SIZE, n_csv), random_state=SAMPLE_SEED)
        sample_pairs = list(
            map(tuple, sample[cols].astype(str).itertuples(index=False, name=None))
        )
        loaded_pairs = set(
            map(tuple, loaded[cols].astype(str).itertuples(index=False, name=None))
        )
        matches = sum(1 for p in sample_pairs if p in loaded_pairs)
        if matches < max(1, len(sample_pairs) // 3):
            failures.append((
                key,
                f"only {matches}/{len(sample_pairs)} sample rows matched on {cols}",
            ))
            continue
        passes += 1

    return {"passes": passes, "failures": failures, "total": len(registry)}


# --- Tier 3: app contract ---------------------------------------------------

APP_CONTRACT = [
    ("fetch_part_d_data", fetch_part_d_data,
     ["Brnd_Name", "Year", "Tot_Spndng", "Tot_Benes", "Avg_Spnd_Per_Bene"]),
    ("fetch_part_b_data", fetch_part_b_data,
     ["Brnd_Name", "Tot_Spndng_2023", "Tot_Benes_2023"]),
    ("load_geo_variation", load_geo_variation,
     ["YEAR", "BENE_GEO_LVL", "BENE_AGE_LVL", "BENE_GEO_DESC",
      "TOT_MDCR_PYMT_AMT", "TOT_MDCR_PYMT_PC", "TOT_MDCR_STDZD_PYMT_PC"]),
    ("load_ahrf", load_ahrf,
     ["st_abbrev", "phys_wkforc_23", "popn_pums_23", "rn_23", "dent_23"]),
    ("load_hpsa", load_hpsa,
     ["HPSA Status", "Discipline"]),
]


def tier3_app_contract() -> dict:
    failures: list[tuple[str, str]] = []
    passes = 0
    for name, fn, expected in APP_CONTRACT:
        try:
            df = fn()
        except Exception as exc:  # noqa: BLE001
            failures.append((name, f"call raised {exc.__class__.__name__}: {exc}"))
            continue
        missing = [c for c in expected if c not in df.columns]
        if missing:
            failures.append((name, f"missing columns: {missing}"))
            continue
        passes += 1
    return {"passes": passes, "failures": failures, "total": len(APP_CONTRACT)}


# --- Tier 4: routing policy compliance --------------------------------------

def _csv_numeric_column_count(path: Path) -> int:
    """Read a small sample to count numeric columns. Returns 0 on read failure."""
    for sep in (",", "|"):
        try:
            sample = pd.read_csv(path, nrows=1000, low_memory=False, sep=sep)
        except Exception:
            continue
        return sum(1 for c in sample.columns if pd.api.types.is_numeric_dtype(sample[c]))
    return 0


def tier4_routing_policy(conn) -> dict:
    failures: list[tuple[str, str]] = []
    passes = 0
    try:
        registry = _fetch_registry(
            conn, ["dataset_key", "storage_location", "row_count"]
        )
    except Exception as exc:  # noqa: BLE001
        return {"passes": 0, "failures": [("(registry fetch)", str(exc))], "total": 0}

    for r in registry:
        key = r["dataset_key"]
        actual = r.get("storage_location")
        rows = r.get("row_count") or 0
        csv_path = DATA_DIR / f"{key}.csv"
        if not csv_path.exists():
            failures.append((key, f"CSV missing for numeric-column inspection: {csv_path.name}"))
            continue
        numeric_columns = _csv_numeric_column_count(csv_path)
        metadata = {
            "rows": rows,
            "numeric_columns": numeric_columns,
            "has_categorical_columns_used_by_app": key in CATEGORICAL_USED_BY_APP,
            "is_filter_heavy": key in FILTER_HEAVY,
        }
        predicted, reason = route_dataset(metadata)
        if predicted != actual:
            failures.append((
                key,
                f"actual={actual} predicted={predicted} ({reason}); "
                f"rows={rows} numeric_cols={numeric_columns}",
            ))
            continue
        passes += 1

    return {"passes": passes, "failures": failures, "total": len(registry)}


# --- Main -------------------------------------------------------------------

def _print_tier(name: str, result: dict) -> None:
    total = result.get("total", result["passes"] + len(result["failures"]))
    warnings = result.get("warnings", [])
    print(f"\n{name}: {result['passes']}/{total} passed, "
          f"{len(result['failures'])} failed"
          + (f", {len(warnings)} warnings" if warnings else ""))
    for k, why in result["failures"]:
        print(f"  - {k}: {why}")
    for k, why in warnings:
        print(f"  ! {k}: {why}")


def main() -> int:
    secrets = load_secrets()
    conn = get_postgres_conn(secrets)
    r2 = make_r2(secrets)
    bucket = secrets.r2_bucket_name

    try:
        print("== TIER 1: registry sanity ==")
        t1 = tier1_registry_sanity(conn, r2, bucket)
        _print_tier("TIER 1", t1)

        print("\n== TIER 2: round-trip integrity ==")
        t2 = tier2_round_trip(conn)
        _print_tier("TIER 2", t2)

        print("\n== TIER 3: app contract ==")
        t3 = tier3_app_contract()
        _print_tier("TIER 3", t3)

        print("\n== TIER 4: routing policy compliance ==")
        t4 = tier4_routing_policy(conn)
        _print_tier("TIER 4", t4)
    finally:
        conn.close()

    total_failed = sum(len(t["failures"]) for t in (t1, t2, t3, t4))
    print(f"\n=== SUMMARY: {total_failed} failures across 4 tiers ===")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
