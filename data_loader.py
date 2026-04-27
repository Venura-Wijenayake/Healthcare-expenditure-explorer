"""Hybrid Supabase + Cloudflare R2 data loader.

Architecture:
- `dataset_registry` (Supabase) tells us where each dataset lives.
- Small lookup tables live in the long-format `observations` table — we
  query them through the supabase-py client.
- Large analytical files live as Parquet in R2 — we read them with DuckDB's
  `httpfs`/R2 secret so only the bytes we actually need are fetched.
- Anything that fails (missing secrets, network, schema mismatch, etc.)
  falls back to the local CSV under `data/` and emits a warning.

The historical public API (`fetch_part_d_data`, `fetch_part_b_data`,
`load_geo_variation`, `load_ahrf`, `load_hpsa`) is preserved so `app.py`
keeps working unchanged. New callers should prefer `load_dataset` /
`get_metric`.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import requests

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & local fallbacks
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

# Original CSV URLs — used only as a last-resort fallback if the local CSV
# is missing AND the remote stores aren't reachable.
PART_D_CSV_URL = "https://data.cms.gov/sites/default/files/2026-01/2d43e067-c2f2-4dfd-a991-95655df72052/QDD_PTD_RQ2601_P01_V10_DQT2502_20260106.csv"
PART_B_CSV_URL = "https://data.cms.gov/sites/default/files/2025-05/f52d5fcd-8d93-481d-9173-6219813e4efb/DSD_PTB_RY25_P06_V10_DYT23_HCPCS-%20250430.csv"
GEO_VARIATION_CSV_URL = "https://data.cms.gov/sites/default/files/2025-03/a40ac71d-9f80-4d99-92d2-fd149433d7d8/2014-2023%20Medicare%20Fee-for-Service%20Geographic%20Variation%20Public%20Use%20File.csv"
AHRF_ZIP_URL = "https://data.hrsa.gov/DataDownload/AHRF/AHRF_SN_2024-2025_CSV.zip"
AHRF_ZIP_MEMBER = "NCHWA-2024-2025+AHRF+SN+CSV/ahrfsn2025.csv"

HPSA_FILES = {
    "Primary Care":  ("hpsa_primary_care.csv",  "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv"),
    "Dental":        ("hpsa_dental.csv",        "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_DH.csv"),
    "Mental Health": ("hpsa_mental_health.csv", "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_MH.csv"),
}

SUPABASE_PAGE_SIZE = 1000


# ---------------------------------------------------------------------------
# Caching shim — use streamlit's cache_data if available, else a no-op.
# ---------------------------------------------------------------------------

try:
    import streamlit as st
    cache_data = st.cache_data
except ImportError:  # pragma: no cover - non-streamlit context
    def cache_data(func=None, **_kwargs):
        if func is None:
            return lambda f: f
        return func


# ---------------------------------------------------------------------------
# Lazy clients — initialised once per process, guarded by a lock.
# ---------------------------------------------------------------------------

_clients_lock = threading.Lock()
_secrets: dict | None = None
_supabase_client = None
_duckdb_conn = None
_remote_init_failed = False


def _load_secrets() -> dict | None:
    """Read .streamlit/secrets.toml. Returns None if the file is missing."""
    global _secrets
    if _secrets is not None:
        return _secrets
    if not SECRETS_PATH.exists():
        return None
    with SECRETS_PATH.open("rb") as f:
        _secrets = tomllib.load(f)
    return _secrets


def _get_supabase():
    """Return a cached Supabase client, or None if it can't be built."""
    global _supabase_client, _remote_init_failed
    if _supabase_client is not None:
        return _supabase_client
    if _remote_init_failed:
        return None
    with _clients_lock:
        if _supabase_client is not None:
            return _supabase_client
        secrets = _load_secrets()
        if not secrets:
            return None
        url = secrets.get("SUPABASE_URL")
        key = secrets.get("SUPABASE_SERVICE_KEY") or secrets.get("SUPABASE_ANON_KEY")
        if not (url and key):
            return None
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supabase init failed: %s — using local CSV fallback", exc)
            _remote_init_failed = True
            return None
    return _supabase_client


def _get_duckdb():
    """Return a cached DuckDB connection with httpfs+R2 secret loaded."""
    global _duckdb_conn
    if _duckdb_conn is not None:
        return _duckdb_conn
    with _clients_lock:
        if _duckdb_conn is not None:
            return _duckdb_conn
        secrets = _load_secrets() or {}
        required = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID")
        if any(not secrets.get(k) for k in required):
            return None
        try:
            import duckdb
            con = duckdb.connect(database=":memory:")
            con.execute("INSTALL httpfs; LOAD httpfs;")
            con.execute(
                """
                CREATE OR REPLACE SECRET r2_secret (
                    TYPE R2,
                    KEY_ID ?,
                    SECRET ?,
                    ACCOUNT_ID ?
                )
                """,
                [
                    secrets["R2_ACCESS_KEY_ID"],
                    secrets["R2_SECRET_ACCESS_KEY"],
                    secrets["R2_ACCOUNT_ID"],
                ],
            )
            _duckdb_conn = con
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDB/R2 init failed: %s — using local CSV fallback", exc)
            return None
    return _duckdb_conn


def _r2_bucket() -> str | None:
    secrets = _load_secrets() or {}
    return secrets.get("R2_BUCKET_NAME")


# ---------------------------------------------------------------------------
# Registry lookups
# ---------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _lookup_storage(dataset_key: str) -> dict | None:
    """Fetch one dataset_registry row. Cached for the process lifetime."""
    sb = _get_supabase()
    if sb is None:
        return None
    try:
        resp = (
            sb.table("dataset_registry")
            .select("dataset_key,storage_location,parquet_path,row_count,granularity")
            .eq("dataset_key", dataset_key)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("dataset_registry lookup failed for %s: %s", dataset_key, exc)
        return None
    rows = resp.data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# R2 / DuckDB query path
# ---------------------------------------------------------------------------

_FILTER_COLUMNS = {
    "state": ["state", "State", "STATE", "state_name", "state_abbr", "locationabbr"],
    "year":  ["year", "Year", "YEAR"],
    "county": ["county", "County", "COUNTY", "county_name"],
}


def _resolve_filter_column(con, table_alias: str, parquet_uri: str, logical: str) -> str | None:
    """Pick the parquet column that matches a logical filter name."""
    candidates = _FILTER_COLUMNS.get(logical, [logical])
    cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{parquet_uri}') LIMIT 0").fetchall()
    available = {row[0] for row in cols}
    for c in candidates:
        if c in available:
            return c
    return None


def _query_r2(dataset_key: str, parquet_path: str, filters: dict[str, Any]) -> pd.DataFrame:
    con = _get_duckdb()
    bucket = _r2_bucket()
    if con is None or not bucket:
        raise RuntimeError("R2 / DuckDB not configured")
    uri = f"r2://{bucket}/{parquet_path}"

    where_parts: list[str] = []
    params: list[Any] = []
    for logical, value in filters.items():
        if value is None:
            continue
        col = _resolve_filter_column(con, dataset_key, uri, logical)
        if not col:
            continue
        if isinstance(value, (list, tuple, set)):
            placeholders = ",".join("?" * len(value))
            where_parts.append(f'"{col}" IN ({placeholders})')
            params.extend(value)
        else:
            where_parts.append(f'"{col}" = ?')
            params.append(value)

    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = f"SELECT * FROM read_parquet('{uri}'){where_clause}"
    return con.execute(sql, params).fetch_df()


def _refresh_row_count(dataset_key: str, parquet_path: str) -> None:
    """Side-effect: keep dataset_registry.row_count honest. Best-effort."""
    sb = _get_supabase()
    con = _get_duckdb()
    bucket = _r2_bucket()
    if not (sb and con and bucket):
        return
    try:
        n = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('r2://{bucket}/{parquet_path}')"
        ).fetchone()[0]
        sb.table("dataset_registry").update({"row_count": int(n)}).eq(
            "dataset_key", dataset_key
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.debug("row_count refresh skipped for %s: %s", dataset_key, exc)


_row_count_seen: set[str] = set()


# ---------------------------------------------------------------------------
# Supabase observations query path
# ---------------------------------------------------------------------------

_OBS_FILTER_TO_COL = {
    "state": "state",
    "county": "county",
    "year": "year",
    "month": "month",
    "sex": "sex",
    "race": "race",
    "age_group": "age_group",
    "metric_name": "metric_name",
}


def _query_observations_long(dataset_key: str, filters: dict[str, Any]) -> pd.DataFrame:
    """Page through `observations`, returning a long-format frame."""
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured")

    rows: list[dict] = []
    offset = 0
    while True:
        q = sb.table("observations").select("*").eq("dataset_key", dataset_key)
        for logical, value in filters.items():
            if value is None:
                continue
            col = _OBS_FILTER_TO_COL.get(logical)
            if not col:
                continue
            if isinstance(value, (list, tuple, set)):
                q = q.in_(col, list(value))
            else:
                q = q.eq(col, value)
        resp = q.range(offset, offset + SUPABASE_PAGE_SIZE - 1).execute()
        page = resp.data or []
        rows.extend(page)
        if len(page) < SUPABASE_PAGE_SIZE:
            break
        offset += SUPABASE_PAGE_SIZE
    return pd.DataFrame(rows)


def _pivot_to_wide(long_df: pd.DataFrame) -> pd.DataFrame:
    """Turn observations rows back into a wide DataFrame, dropping all-null cols."""
    if long_df.empty:
        return long_df
    keep_index = [
        c for c in ("state", "county", "year", "month", "sex", "race", "age_group")
        if c in long_df.columns and long_df[c].notna().any()
    ]
    if not keep_index:
        # No grouping keys — just spread metric_name into columns
        keep_index = ["dataset_key"] if "dataset_key" in long_df.columns else None
    wide = long_df.pivot_table(
        index=keep_index,
        columns="metric_name",
        values="metric_value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    return wide


# ---------------------------------------------------------------------------
# Public API: load_dataset / get_metric
# ---------------------------------------------------------------------------

@cache_data(show_spinner=False)
def load_dataset(
    dataset_key: str,
    *,
    state: Any = None,
    year: Any = None,
    county: Any = None,
    metric_name: Any = None,
    long_format: bool = False,
    csv_fallback: str | os.PathLike | None = None,
) -> pd.DataFrame:
    """Load a dataset by `dataset_key`, dispatching to the right backend.

    Returns a wide DataFrame by default. Pass `long_format=True` to keep the
    raw `observations` shape (only meaningful for Supabase-backed datasets).
    `csv_fallback` is the local CSV path to read if the remote path fails.
    """
    filters = {"state": state, "year": year, "county": county,
               "metric_name": metric_name}

    reg = _lookup_storage(dataset_key)
    storage = (reg or {}).get("storage_location")

    # --- R2 path ---
    if storage == "r2":
        path = reg.get("parquet_path") or f"{dataset_key}.parquet"
        try:
            df = _query_r2(dataset_key, path, filters)
            if dataset_key not in _row_count_seen:
                _row_count_seen.add(dataset_key)
                _refresh_row_count(dataset_key, path)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("R2 read failed for %s (%s) — falling back to CSV", dataset_key, exc)

    # --- Supabase path ---
    elif storage == "supabase":
        try:
            long_df = _query_observations_long(dataset_key, filters)
            if long_format:
                return long_df
            return _pivot_to_wide(long_df)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supabase read failed for %s (%s) — falling back to CSV", dataset_key, exc)

    else:
        if reg is None:
            logger.warning("No dataset_registry entry for %s — using CSV fallback", dataset_key)

    # --- CSV fallback ---
    csv_path = Path(csv_fallback) if csv_fallback else DATA_DIR / f"{dataset_key}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"No remote backend reachable and local CSV missing: {csv_path}"
        )
    return pd.read_csv(csv_path, low_memory=False)


def get_metric(
    dataset_key: str,
    metric_name: str,
    *,
    state: Any = None,
    year: Any = None,
    county: Any = None,
) -> pd.DataFrame:
    """Convenience wrapper for a single metric out of `observations`.

    Returns the long-format slice (state/county/year/metric_value), which is
    the natural shape for Supabase-backed datasets. R2-backed datasets are
    pivoted on the fly so the caller gets a uniform schema.
    """
    reg = _lookup_storage(dataset_key)
    storage = (reg or {}).get("storage_location")

    if storage == "supabase":
        try:
            df = _query_observations_long(
                dataset_key,
                {"state": state, "year": year, "county": county,
                 "metric_name": metric_name},
            )
            cols = [c for c in ("state", "county", "year", "month",
                                "metric_name", "metric_value", "sex",
                                "race", "age_group") if c in df.columns]
            return df[cols] if cols else df
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_metric supabase read failed for %s/%s: %s",
                           dataset_key, metric_name, exc)

    # R2 or fallback: load wide and synthesise the long slice
    wide = load_dataset(dataset_key, state=state, year=year, county=county)
    if metric_name not in wide.columns:
        return pd.DataFrame()
    out = wide.copy()
    out["metric_name"] = metric_name
    out["metric_value"] = out[metric_name]
    keep = [c for c in ("state", "county", "year", "month",
                        "metric_name", "metric_value") if c in out.columns]
    return out[keep]


# ---------------------------------------------------------------------------
# Legacy public API — preserves the signatures app.py imports.
# ---------------------------------------------------------------------------

def _csv_via_http(url: str, dest: Path, timeout: int = 120) -> Path:
    """Download a CSV to `dest` if it's not already there."""
    if dest.exists():
        return dest
    print(f"Downloading {dest.name}...")
    resp = requests.get(url, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch {url}: {resp.status_code}")
    dest.write_bytes(resp.content)
    return dest


def fetch_part_d_data():
    """Load Medicare Part D drug spending data."""
    csv_path = DATA_DIR / "part_d.csv"
    try:
        df = load_dataset("part_d", csv_fallback=csv_path)
    except FileNotFoundError:
        _csv_via_http(PART_D_CSV_URL, csv_path, timeout=30)
        df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} Part D records")
    return df


def fetch_part_b_data():
    """Load Medicare Part B drug spending data (administered in doctors offices)."""
    csv_path = DATA_DIR / "part_b.csv"
    try:
        df = load_dataset("part_b", csv_fallback=csv_path)
    except FileNotFoundError:
        _csv_via_http(PART_B_CSV_URL, csv_path, timeout=30)
        df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} Part B records")
    return df


def load_geo_variation():
    """Load Medicare FFS geographic variation data (national/state/county, 2014-2023)."""
    csv_path = DATA_DIR / "geo_variation_2014_2023.csv"
    try:
        df = load_dataset("geo_variation_2014_2023", csv_fallback=csv_path)
    except FileNotFoundError:
        _csv_via_http(GEO_VARIATION_CSV_URL, csv_path, timeout=120)
        df = pd.read_csv(csv_path, low_memory=False)
    if "YEAR" in df.columns:
        print(f"Loaded {len(df)} Geographic Variation records "
              f"({df['YEAR'].min()}-{df['YEAR'].max()})")
    else:
        print(f"Loaded {len(df)} Geographic Variation records")
    return df


def load_ahrf():
    """Load HRSA AHRF state+national workforce file (52 rows = 50 states + DC + US, 1448 vars)."""
    csv_path = DATA_DIR / "ahrf_state_national_2025.csv"
    try:
        df = load_dataset("ahrf_state_national_2025", csv_fallback=csv_path)
    except FileNotFoundError:
        print("Downloading AHRF data from HRSA...")
        resp = requests.get(AHRF_ZIP_URL, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch AHRF: {resp.status_code}")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            with z.open(AHRF_ZIP_MEMBER) as src:
                csv_path.write_bytes(src.read())
        df = pd.read_csv(csv_path, low_memory=False)
    print(f"Loaded {len(df)} AHRF state rows, {len(df.columns)} columns")
    return df


def load_hpsa():
    """Load HRSA HPSA designations across all 3 disciplines, filtered to currently Designated."""
    frames = []
    for discipline, (fname, url) in HPSA_FILES.items():
        csv_path = DATA_DIR / fname
        key = csv_path.stem
        try:
            df = load_dataset(key, csv_fallback=csv_path)
        except FileNotFoundError:
            _csv_via_http(url, csv_path, timeout=300)
            df = pd.read_csv(csv_path, low_memory=False)
        if "HPSA Status" in df.columns:
            df = df[df["HPSA Status"] == "Designated"].copy()
        df["Discipline"] = discipline
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(combined)} designated HPSAs across {len(HPSA_FILES)} disciplines")
    return combined


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df_d = fetch_part_d_data()
    print("Part D columns:", df_d.columns.tolist()[:10], "...")
    df_b = fetch_part_b_data()
    print("Part B columns:", df_b.columns.tolist()[:10], "...")
    df_g = load_geo_variation()
    print("Geo Variation shape:", df_g.shape)
    df_a = load_ahrf()
    print("AHRF shape:", df_a.shape)
    df_h = load_hpsa()
    print("HPSA shape:", df_h.shape)
