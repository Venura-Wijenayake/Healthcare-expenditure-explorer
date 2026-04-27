"""Migrate the 81 CSV datasets in data/ to a hybrid Supabase + Cloudflare R2 store.

Small lookup tables (< 10K rows) are unpivoted into a long-format `observations`
table in Supabase. Large analytical files are converted to Parquet and uploaded
to R2. A `dataset_registry` and `metric_registry` in Supabase track everything.

Usage:
    pip install supabase boto3 pyarrow fastparquet pandas
    python scripts/migrate_to_supabase_r2.py
"""

from __future__ import annotations

import io
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.client import Config as BotoConfig
from supabase import Client, create_client


# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
SCHEMA_OUT_PATH = ROOT / "scripts" / "supabase_schema.sql"

ROW_THRESHOLD = 10_000
INSERT_BATCH = 1000
PARQUET_COMPRESSION = "snappy"
PARQUET_CHUNKSIZE = 100_000

# Files we never migrate (dictionaries, manifests, docs, non-CSV)
SKIP_FILES = {
    "aoa_aging_services_DICTIONARY.csv",
    "usda_food_access_dictionary.csv",
    "uscs_data_dictionary.xlsx",
    "hrsa_uds_h80_2024.xlsx",
    "MANIFEST.md",
}

# Directionality reference taken from app.py:LOWER_IS_BETTER
LOWER_IS_BETTER = {
    "sir": True, "readmission": True, "uninsured": True, "unemployment": True,
    "wait": True, "od_deaths": True, "poverty": True, "shortage": True,
    "mortality": True, "physicians": False, "rn_per": False, "beds": False,
    "vaccination": False,
}

# Datasets the user explicitly wants in Supabase (will be re-routed to R2 if
# the actual row count is over the threshold).
SUPABASE_DATASETS_REQUESTED = [
    "state_risk_index",
    "census_sahie",
    "census_saipe",
    "bls_unemployment",
    "cdc_hai",
    "cms_timely_care",
    "hrsa_nurse_corps",
    "samhsa_nmhss",
    "cdc_hiv",
    "cdc_sti",
    "hpsa_primary_care",
    "hospital_compare_general_info",
]

# Datasets the user explicitly wants in R2 (large analytical files)
R2_DATASETS_REQUESTED = [
    "cms_snf",
    "cdc_nndss",
    "hrsa_mch",
    "nci_cancer",
    "cdc_places_county",
    "cdc_alzheimers",
    "brfss_state_prevalence",
    "rwj_county_health_rankings",
    "cms_physician_payments",
    "cdc_vaccination",
    "geo_variation_2014_2023",
]

# CSV read overrides (custom delimiter, encoding, etc.)
READ_OVERRIDES: dict[str, dict] = {
    "nci_cancer": {"sep": "|"},
}

# Metadata for dataset_registry entries
DATASET_METADATA: dict[str, dict] = {
    "state_risk_index":              {"name": "State Healthcare Risk Index",        "agency": "Composite",  "category": "Risk"},
    "census_sahie":                  {"name": "Small Area Health Insurance Estimates", "agency": "Census",  "category": "Coverage"},
    "census_saipe":                  {"name": "Small Area Income & Poverty Estimates", "agency": "Census",  "category": "Social Determinants"},
    "bls_unemployment":              {"name": "BLS Unemployment by State",          "agency": "BLS",        "category": "Workforce"},
    "cdc_hai":                       {"name": "CDC Healthcare-Associated Infections", "agency": "CDC",      "category": "Quality"},
    "cms_timely_care":               {"name": "CMS Timely & Effective Care",        "agency": "CMS",        "category": "Quality"},
    "hrsa_nurse_corps":              {"name": "HRSA Nurse Corps Awards",             "agency": "HRSA",       "category": "Workforce"},
    "samhsa_nmhss":                  {"name": "SAMHSA National Mental Health Services Survey", "agency": "SAMHSA", "category": "Behavioral Health"},
    "cdc_hiv":                       {"name": "CDC HIV Surveillance",                "agency": "CDC",        "category": "Disease"},
    "cdc_sti":                       {"name": "CDC STI Surveillance",                "agency": "CDC",        "category": "Disease"},
    "hpsa_primary_care":             {"name": "HRSA HPSA — Primary Care",            "agency": "HRSA",       "category": "Workforce"},
    "hospital_compare_general_info": {"name": "Hospital Compare — General Info",     "agency": "CMS",        "category": "Quality"},
    "cms_snf":                       {"name": "CMS Skilled Nursing Facility",        "agency": "CMS",        "category": "Post-Acute"},
    "cdc_nndss":                     {"name": "CDC NNDSS Notifiable Diseases",       "agency": "CDC",        "category": "Disease"},
    "hrsa_mch":                      {"name": "HRSA Maternal & Child Health",        "agency": "HRSA",       "category": "Maternal/Child"},
    "nci_cancer":                    {"name": "NCI Cancer Incidence & Mortality",    "agency": "NCI",        "category": "Disease"},
    "cdc_places_county":             {"name": "CDC PLACES County-Level",             "agency": "CDC",        "category": "Population Health"},
    "cdc_alzheimers":                {"name": "CDC Alzheimer's Surveillance",        "agency": "CDC",        "category": "Chronic Disease"},
    "brfss_state_prevalence":        {"name": "BRFSS State Prevalence",              "agency": "CDC",        "category": "Population Health"},
    "rwj_county_health_rankings":    {"name": "RWJ County Health Rankings",          "agency": "RWJF",       "category": "Population Health"},
    "cms_physician_payments":        {"name": "CMS Physician Open Payments",         "agency": "CMS",        "category": "Spending"},
    "cdc_vaccination":               {"name": "CDC Vaccination Coverage",            "agency": "CDC",        "category": "Prevention"},
    "geo_variation_2014_2023":       {"name": "CMS Geographic Variation 2014-2023",  "agency": "CMS",        "category": "Spending"},
}


# ---------------------------------------------------------------------------
# Schema (also written to scripts/supabase_schema.sql for manual application)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS dataset_registry (
    dataset_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agency TEXT NOT NULL,
    category TEXT NOT NULL,
    granularity TEXT NOT NULL,
    storage_location TEXT NOT NULL,
    parquet_path TEXT,
    year_start INTEGER,
    year_end INTEGER,
    refresh_schedule TEXT,
    last_refreshed TIMESTAMPTZ,
    row_count INTEGER,
    contributor TEXT DEFAULT 'core-team',
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metric_registry (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT REFERENCES dataset_registry(dataset_key),
    metric_name TEXT NOT NULL,
    metric_label TEXT NOT NULL,
    metric_unit TEXT,
    lower_is_better BOOLEAN,
    description TEXT,
    UNIQUE(dataset_key, metric_name)
);

CREATE TABLE IF NOT EXISTS observations (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT REFERENCES dataset_registry(dataset_key),
    state TEXT,
    county TEXT,
    granularity TEXT NOT NULL,
    year INTEGER,
    month INTEGER,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC,
    metric_unit TEXT,
    sex TEXT,
    race TEXT,
    age_group TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_obs_state           ON observations(state);
CREATE INDEX IF NOT EXISTS idx_obs_metric          ON observations(metric_name);
CREATE INDEX IF NOT EXISTS idx_obs_dataset         ON observations(dataset_key);
CREATE INDEX IF NOT EXISTS idx_obs_year            ON observations(year);
CREATE INDEX IF NOT EXISTS idx_obs_state_metric_year ON observations(state, metric_name, year);
CREATE INDEX IF NOT EXISTS idx_obs_granularity     ON observations(granularity);

CREATE TABLE IF NOT EXISTS contributor_submissions (
    id BIGSERIAL PRIMARY KEY,
    github_username TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    agency TEXT NOT NULL,
    description TEXT NOT NULL,
    fetch_script_url TEXT,
    estimated_rows INTEGER,
    status TEXT DEFAULT 'pending',
    reviewer TEXT,
    reviewer_notes TEXT,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);
"""


# ---------------------------------------------------------------------------
# Secrets / clients
# ---------------------------------------------------------------------------

@dataclass
class Secrets:
    supabase_url: str
    supabase_service_key: str
    r2_endpoint_url: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str


def load_secrets() -> Secrets:
    if not SECRETS_PATH.exists():
        raise FileNotFoundError(f"Missing secrets file: {SECRETS_PATH}")
    with SECRETS_PATH.open("rb") as f:
        cfg = tomllib.load(f)
    required = [
        "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
        "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME",
    ]
    missing = [k for k in required if k not in cfg or not cfg[k]]
    if missing:
        raise RuntimeError(f"Missing secrets in {SECRETS_PATH}: {missing}")
    return Secrets(
        supabase_url=cfg["SUPABASE_URL"],
        supabase_service_key=cfg["SUPABASE_SERVICE_KEY"],
        r2_endpoint_url=cfg["R2_ENDPOINT_URL"],
        r2_access_key_id=cfg["R2_ACCESS_KEY_ID"],
        r2_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
        r2_bucket_name=cfg["R2_BUCKET_NAME"],
    )


def make_supabase(secrets: Secrets) -> Client:
    return create_client(secrets.supabase_url, secrets.supabase_service_key)


def make_r2(secrets: Secrets):
    return boto3.client(
        "s3",
        endpoint_url=secrets.r2_endpoint_url,
        aws_access_key_id=secrets.r2_access_key_id,
        aws_secret_access_key=secrets.r2_secret_access_key,
        config=BotoConfig(signature_version="s3v4"),
    )


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def write_schema_file() -> None:
    SCHEMA_OUT_PATH.write_text(SCHEMA_SQL, encoding="utf-8")


def apply_schema(client: Client) -> None:
    """Try to apply the schema via an `exec_sql` RPC; fall back to file output.

    Supabase doesn't expose arbitrary DDL through PostgREST, so the project
    needs a one-time `exec_sql(text)` SQL function. If it isn't installed,
    we emit the schema file and ask the user to paste it into the SQL editor.
    """
    write_schema_file()
    try:
        client.rpc("exec_sql", {"sql": SCHEMA_SQL}).execute()
        print("[schema] applied via exec_sql RPC")
    except Exception as exc:  # noqa: BLE001
        print(f"[schema] could not apply via RPC ({exc.__class__.__name__}): "
              f"run {SCHEMA_OUT_PATH.relative_to(ROOT)} in the Supabase SQL editor")


# ---------------------------------------------------------------------------
# Column / dataframe helpers
# ---------------------------------------------------------------------------

STATE_COL_CANDIDATES = [
    "state", "State", "state_name", "state_abbr", "BENE_GEO_DESC", "AREA",
    "locationabbr", "locationdesc", "reporting_area", "State Abbreviation",
    "State Name", "state_territory", "st_abbrev", "NAME", "ACO_State",
]
COUNTY_COL_CANDIDATES = [
    "county", "County", "county_name", "BENE_GEO_DESC2", "fips_county",
]
YEAR_COL_CANDIDATES = ["year", "Year", "YEAR", "fiscal_year", "yearstart", "period"]
MONTH_COL_CANDIDATES = ["month", "Month", "MONTH", "month_num"]
SEX_COL_CANDIDATES = ["sex", "Sex", "SEX", "gender", "Gender"]
RACE_COL_CANDIDATES = ["race", "Race", "RACE", "race_ethnicity", "Race/Ethnicity"]
AGE_COL_CANDIDATES = ["age", "Age", "AGE", "age_group", "AgeGroup", "age_range"]


def _first_present(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def drop_low_value_columns(df: pd.DataFrame, dataset_key: str) -> pd.DataFrame:
    """Drop columns per the user's preservation rules.

    Drop only when:
      - >90% null/empty
      - duplicate of another column (identical values)
      - raw URL/hyperlink with no analytical value
      - internal auto-increment ID with no analytical meaning
    """
    df = df.copy()
    before = list(df.columns)

    # Treat empty strings as null for the purpose of the threshold check
    null_share = (df.isna() | (df.astype(object) == "")).mean()
    high_null = null_share[null_share > 0.9].index.tolist()
    df = df.drop(columns=high_null)

    # Duplicate columns (same values, different name)
    dup_mask = df.T.duplicated(keep="first")
    dup_cols = df.columns[dup_mask].tolist()
    df = df.drop(columns=dup_cols)

    # URL-only columns
    url_cols = []
    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna().astype(str).head(50)
            if len(sample) > 0 and (sample.str.match(URL_RE).mean() > 0.9):
                url_cols.append(col)
    df = df.drop(columns=url_cols)

    # Auto-increment internal IDs: integer column where every value is unique,
    # values look like 1..N, and the name screams "id" without analytical meaning.
    id_cols = []
    name_re = re.compile(r"^(?:id|row_?id|primary_?key|pk|seq|seq_?id|_id)$", re.IGNORECASE)
    for col in df.columns:
        if not name_re.match(str(col)):
            continue
        if not pd.api.types.is_integer_dtype(df[col]):
            continue
        if df[col].is_unique and df[col].min() >= 0:
            id_cols.append(col)
    df = df.drop(columns=id_cols)

    dropped = set(before) - set(df.columns)
    if dropped:
        print(f"  [columns] {dataset_key}: dropped {len(dropped)} "
              f"(null/dup/url/id) -> kept {len(df.columns)}")
    return df


def detect_granularity(df: pd.DataFrame) -> tuple[str, str | None, str | None]:
    state_col = _first_present(df, STATE_COL_CANDIDATES)
    county_col = _first_present(df, COUNTY_COL_CANDIDATES)
    if county_col and state_col:
        return "county", state_col, county_col
    if state_col:
        return "state", state_col, None
    return "national", None, None


def detect_metric_unit(metric_name: str) -> str | None:
    lc = metric_name.lower()
    if "per_100k" in lc or "per 100k" in lc:
        return "per 100k"
    if "pct" in lc or "rate" in lc or "percent" in lc:
        return "%"
    if "dollars" in lc or "amount" in lc or "_usd" in lc or "spending" in lc:
        return "USD"
    return None


def lower_is_better_for(metric_name: str) -> bool | None:
    lc = metric_name.lower()
    for pat, val in LOWER_IS_BETTER.items():
        if pat in lc:
            return val
    return None


def read_csv(path: Path, dataset_key: str, **extra) -> pd.DataFrame:
    opts = {"low_memory": False}
    opts.update(READ_OVERRIDES.get(dataset_key, {}))
    opts.update(extra)
    return pd.read_csv(path, **opts)


def count_rows_fast(path: Path, dataset_key: str) -> int:
    """Cheap row count without loading all columns into memory."""
    opts = {"low_memory": False, "usecols": [0]}
    overrides = READ_OVERRIDES.get(dataset_key, {})
    if "sep" in overrides:
        opts["sep"] = overrides["sep"]
    try:
        return sum(chunk.shape[0] for chunk in pd.read_csv(path, chunksize=200_000, **opts))
    except Exception:
        # Fall back to a full read (rare)
        return read_csv(path, dataset_key).shape[0]


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@dataclass
class Routing:
    supabase: list[tuple[str, Path]] = field(default_factory=list)
    r2: list[tuple[str, Path]] = field(default_factory=list)
    skipped: list[tuple[str, Path, str]] = field(default_factory=list)


def list_datasets() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for p in sorted(DATA_DIR.iterdir()):
        if not p.is_file():
            continue
        if p.name in SKIP_FILES:
            continue
        if p.suffix.lower() != ".csv":
            continue
        out.append((p.stem, p))
    return out


def route_datasets(all_datasets: list[tuple[str, Path]]) -> Routing:
    """Decide Supabase vs R2 for every dataset based on the user's lists +
    the 10K-row threshold."""
    routing = Routing()
    requested_supabase = set(SUPABASE_DATASETS_REQUESTED)
    requested_r2 = set(R2_DATASETS_REQUESTED)

    for key, path in all_datasets:
        try:
            n = count_rows_fast(path, key)
        except Exception as exc:  # noqa: BLE001
            routing.skipped.append((key, path, f"row count failed: {exc}"))
            continue

        in_s = key in requested_supabase
        in_r = key in requested_r2

        if in_r:
            routing.r2.append((key, path))
        elif in_s:
            (routing.supabase if n < ROW_THRESHOLD else routing.r2).append((key, path))
        else:
            (routing.supabase if n < ROW_THRESHOLD else routing.r2).append((key, path))

        loc = "supabase" if (key, path) in routing.supabase else "r2"
        print(f"  [route] {key}: {n:,} rows -> {loc}")

    return routing


# ---------------------------------------------------------------------------
# Supabase migration
# ---------------------------------------------------------------------------

def upsert_dataset_registry(
    client: Client,
    *,
    dataset_key: str,
    storage_location: str,
    granularity: str,
    parquet_path: str | None,
    year_start: int | None,
    year_end: int | None,
    row_count: int,
) -> None:
    meta = DATASET_METADATA.get(dataset_key, {})
    record = {
        "dataset_key": dataset_key,
        "name": meta.get("name", dataset_key.replace("_", " ").title()),
        "agency": meta.get("agency", "Unknown"),
        "category": meta.get("category", "General"),
        "granularity": granularity,
        "storage_location": storage_location,
        "parquet_path": parquet_path,
        "year_start": year_start,
        "year_end": year_end,
        "row_count": row_count,
    }
    client.table("dataset_registry").upsert(record, on_conflict="dataset_key").execute()


def insert_metric_registry(client: Client, dataset_key: str, metric_names: Iterable[str]) -> None:
    rows = []
    for m in metric_names:
        unit = detect_metric_unit(m)
        rows.append({
            "dataset_key": dataset_key,
            "metric_name": m,
            "metric_label": m.replace("_", " ").replace(".", " ").title(),
            "metric_unit": unit,
            "lower_is_better": lower_is_better_for(m),
        })
    if not rows:
        return
    # Upsert in batches; on_conflict on (dataset_key, metric_name)
    for i in range(0, len(rows), INSERT_BATCH):
        batch = rows[i:i + INSERT_BATCH]
        client.table("metric_registry").upsert(
            batch, on_conflict="dataset_key,metric_name"
        ).execute()


def melt_to_observations(df: pd.DataFrame, dataset_key: str) -> tuple[pd.DataFrame, dict]:
    """Unpivot a wide dataset into the long observations schema.

    Returns the long dataframe plus metadata (granularity, year span)."""
    granularity, state_col, county_col = detect_granularity(df)
    year_col = _first_present(df, YEAR_COL_CANDIDATES)
    month_col = _first_present(df, MONTH_COL_CANDIDATES)
    sex_col = _first_present(df, SEX_COL_CANDIDATES)
    race_col = _first_present(df, RACE_COL_CANDIDATES)
    age_col = _first_present(df, AGE_COL_CANDIDATES)

    id_vars: list[str] = [c for c in [state_col, county_col, year_col, month_col,
                                      sex_col, race_col, age_col] if c]

    numeric_cols = [
        c for c in df.columns
        if c not in id_vars and pd.api.types.is_numeric_dtype(df[c])
    ]
    if not numeric_cols:
        raise ValueError(f"{dataset_key}: no numeric columns to unpivot")

    long_df = df.melt(
        id_vars=id_vars,
        value_vars=numeric_cols,
        var_name="metric_name",
        value_name="metric_value",
    )
    long_df = long_df.dropna(subset=["metric_value"])

    # Standardise into the observations schema
    out = pd.DataFrame({
        "dataset_key": dataset_key,
        "state": long_df[state_col] if state_col else None,
        "county": long_df[county_col] if county_col else None,
        "granularity": granularity,
        "year": pd.to_numeric(long_df[year_col], errors="coerce").astype("Int64") if year_col else pd.NA,
        "month": pd.to_numeric(long_df[month_col], errors="coerce").astype("Int64") if month_col else pd.NA,
        "metric_name": long_df["metric_name"].astype(str),
        "metric_value": pd.to_numeric(long_df["metric_value"], errors="coerce"),
        "metric_unit": None,
        "sex": long_df[sex_col].astype(str) if sex_col else None,
        "race": long_df[race_col].astype(str) if race_col else None,
        "age_group": long_df[age_col].astype(str) if age_col else None,
        "notes": None,
    })
    out = out.dropna(subset=["metric_value"])

    years = pd.to_numeric(out["year"], errors="coerce").dropna()
    meta = {
        "granularity": granularity,
        "year_start": int(years.min()) if not years.empty else None,
        "year_end": int(years.max()) if not years.empty else None,
        "metric_names": numeric_cols,
    }
    return out, meta


def _row_to_payload(row: dict) -> dict:
    """Coerce pandas/NumPy values to JSON-friendly types for supabase-py."""
    payload = {}
    for k, v in row.items():
        if v is None:
            payload[k] = None
            continue
        try:
            if pd.isna(v):
                payload[k] = None
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(v, (pd._libs.tslibs.timestamps.Timestamp,)):
            payload[k] = v.isoformat()
        elif hasattr(v, "item"):
            payload[k] = v.item()
        else:
            payload[k] = v
    return payload


def insert_observations(client: Client, df: pd.DataFrame, dataset_key: str) -> int:
    inserted = 0
    records = df.to_dict(orient="records")
    for i in range(0, len(records), INSERT_BATCH):
        batch = [_row_to_payload(r) for r in records[i:i + INSERT_BATCH]]
        client.table("observations").insert(batch).execute()
        inserted += len(batch)
    return inserted


def migrate_to_supabase(client: Client, dataset_key: str, path: Path) -> dict:
    print(f"[supabase] {dataset_key}: reading {path.name}")
    df = read_csv(path, dataset_key)
    df = drop_low_value_columns(df, dataset_key)

    long_df, meta = melt_to_observations(df, dataset_key)
    upsert_dataset_registry(
        client,
        dataset_key=dataset_key,
        storage_location="supabase",
        granularity=meta["granularity"],
        parquet_path=None,
        year_start=meta["year_start"],
        year_end=meta["year_end"],
        row_count=int(len(long_df)),
    )
    n = insert_observations(client, long_df, dataset_key)
    insert_metric_registry(client, dataset_key, meta["metric_names"])
    print(f"  Loaded {n} rows from {dataset_key}")
    return {"rows": n, "metrics": len(meta["metric_names"])}


# ---------------------------------------------------------------------------
# R2 migration
# ---------------------------------------------------------------------------

def csv_to_parquet_bytes(path: Path, dataset_key: str) -> bytes:
    """Stream-read the CSV and write Parquet to an in-memory buffer."""
    overrides = READ_OVERRIDES.get(dataset_key, {})
    sep = overrides.get("sep", ",")

    buffer = io.BytesIO()
    writer: pq.ParquetWriter | None = None
    try:
        for chunk in pd.read_csv(path, sep=sep, low_memory=False,
                                 chunksize=PARQUET_CHUNKSIZE):
            chunk = drop_low_value_columns(chunk, dataset_key)
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(
                    buffer, table.schema, compression=PARQUET_COMPRESSION
                )
            else:
                # Re-cast the chunk schema to the writer's so chunk-to-chunk
                # type drift doesn't break the writer.
                try:
                    table = table.cast(writer.schema)
                except (pa.ArrowInvalid, pa.ArrowTypeError):
                    pass
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()
    return buffer.getvalue()


def detect_year_span_from_csv(path: Path, dataset_key: str) -> tuple[int | None, int | None]:
    """Best-effort year span — peek at year columns chunk-by-chunk."""
    overrides = READ_OVERRIDES.get(dataset_key, {})
    sep = overrides.get("sep", ",")
    y_min: int | None = None
    y_max: int | None = None
    try:
        head = pd.read_csv(path, sep=sep, nrows=5, low_memory=False)
        ycol = _first_present(head, YEAR_COL_CANDIDATES)
        if not ycol:
            return None, None
        for chunk in pd.read_csv(path, sep=sep, usecols=[ycol], low_memory=False,
                                 chunksize=200_000):
            years = pd.to_numeric(chunk[ycol], errors="coerce").dropna()
            if years.empty:
                continue
            y_min = int(years.min()) if y_min is None else min(y_min, int(years.min()))
            y_max = int(years.max()) if y_max is None else max(y_max, int(years.max()))
    except Exception:
        return None, None
    return y_min, y_max


def detect_granularity_from_csv(path: Path, dataset_key: str) -> str:
    overrides = READ_OVERRIDES.get(dataset_key, {})
    sep = overrides.get("sep", ",")
    head = pd.read_csv(path, sep=sep, nrows=5, low_memory=False)
    g, _, _ = detect_granularity(head)
    return g


def migrate_to_r2(client: Client, r2, bucket: str, dataset_key: str, path: Path) -> dict:
    print(f"[r2] {dataset_key}: converting {path.name} to Parquet")
    csv_bytes = path.stat().st_size
    parquet_bytes = csv_to_parquet_bytes(path, dataset_key)
    key = f"{dataset_key}.parquet"

    r2.put_object(
        Bucket=bucket,
        Key=key,
        Body=parquet_bytes,
        ContentType="application/vnd.apache.parquet",
    )

    csv_mb = csv_bytes / 1_000_000
    pq_mb = len(parquet_bytes) / 1_000_000
    reduction = 1 - (len(parquet_bytes) / csv_bytes) if csv_bytes else 0.0
    print(f"  Uploaded {key} — {csv_mb:.1f}MB CSV → {pq_mb:.1f}MB Parquet "
          f"({reduction:.0%} reduction)")

    granularity = detect_granularity_from_csv(path, dataset_key)
    y_start, y_end = detect_year_span_from_csv(path, dataset_key)

    # row count — quick scan of the parquet we just produced
    row_count = pq.read_metadata(io.BytesIO(parquet_bytes)).num_rows

    upsert_dataset_registry(
        client,
        dataset_key=dataset_key,
        storage_location="r2",
        granularity=granularity,
        parquet_path=key,
        year_start=y_start,
        year_end=y_end,
        row_count=int(row_count),
    )
    return {
        "csv_mb": csv_mb,
        "parquet_mb": pq_mb,
        "reduction": reduction,
        "rows": int(row_count),
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def print_report(
    *,
    supabase_results: dict[str, dict],
    r2_results: dict[str, dict],
    failed: list[tuple[str, str]],
    client: Client,
    r2,
    bucket: str,
) -> None:
    print()
    print("=== MIGRATION REPORT ===")

    try:
        obs_count = client.table("observations").select("id", count="exact").limit(1).execute().count
    except Exception:
        obs_count = sum(r["rows"] for r in supabase_results.values())
    try:
        ds_count = client.table("dataset_registry").select("dataset_key", count="exact").limit(1).execute().count
    except Exception:
        ds_count = len(supabase_results) + len(r2_results)
    try:
        m_count = client.table("metric_registry").select("id", count="exact").limit(1).execute().count
    except Exception:
        m_count = sum(r.get("metrics", 0) for r in supabase_results.values())

    print(f"Supabase observations table: {obs_count} rows")
    print(f"Supabase dataset_registry: {ds_count} datasets")
    print(f"Supabase metric_registry: {m_count} metrics")

    try:
        r2_total = 0
        r2_files = 0
        paginator = r2.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []) or []:
                r2_files += 1
                r2_total += obj["Size"]
        print(f"R2 bucket: {r2_files} files uploaded")
        print(f"R2 total size: {r2_total / 1_000_000:.1f} MB")
    except Exception as exc:  # noqa: BLE001
        print(f"R2 listing failed: {exc}")

    print()
    print("Supabase datasets:")
    for k, r in sorted(supabase_results.items()):
        print(f"  ✅ {k} — {r['rows']} rows")

    print()
    print("R2 datasets:")
    for k, r in sorted(r2_results.items()):
        print(f"  ✅ {k}.parquet — {r['csv_mb']:.0f}MB → {r['parquet_mb']:.0f}MB "
              f"({r['reduction']:.0%} reduction)")

    supabase_mb_est = sum(r["rows"] for r in supabase_results.values()) * 200 / 1_000_000
    r2_mb = sum(r["parquet_mb"] for r in r2_results.values())
    print()
    print(f"Supabase storage used: ~{supabase_mb_est:.0f}MB of 500MB free tier")
    print(f"R2 storage used: ~{r2_mb:.0f}MB of 10GB free tier")

    if failed:
        print()
        print("Failed datasets:")
        for k, reason in failed:
            print(f"  ❌ {k} — {reason}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    secrets = load_secrets()
    sb = make_supabase(secrets)
    r2 = make_r2(secrets)

    print("[step 1] applying Supabase schema")
    apply_schema(sb)

    print()
    print("[step 2] discovering & routing datasets")
    all_datasets = list_datasets()
    routing = route_datasets(all_datasets)
    print(f"  -> {len(routing.supabase)} Supabase, {len(routing.r2)} R2, "
          f"{len(routing.skipped)} skipped")

    failed: list[tuple[str, str]] = []
    supabase_results: dict[str, dict] = {}
    r2_results: dict[str, dict] = {}

    print()
    print("[step 4] migrating small datasets to Supabase")
    for key, path in routing.supabase:
        try:
            supabase_results[key] = migrate_to_supabase(sb, key, path)
        except Exception as exc:  # noqa: BLE001
            failed.append((key, f"supabase: {exc}"))
            traceback.print_exc()

    print()
    print("[step 5] migrating large datasets to R2")
    for key, path in routing.r2:
        try:
            r2_results[key] = migrate_to_r2(sb, r2, secrets.r2_bucket_name, key, path)
        except Exception as exc:  # noqa: BLE001
            failed.append((key, f"r2: {exc}"))
            traceback.print_exc()

    for key, _, reason in routing.skipped:
        failed.append((key, reason))

    print_report(
        supabase_results=supabase_results,
        r2_results=r2_results,
        failed=failed,
        client=sb,
        r2=r2,
        bucket=secrets.r2_bucket_name,
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
