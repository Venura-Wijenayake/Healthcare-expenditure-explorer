"""Hybrid Postgres (Neon) + Cloudflare R2 data loader.

Architecture:
- `dataset_registry` (Postgres) tells us where each dataset lives.
- Small lookup tables live in the long-format `observations` table.
- Large analytical files live as Parquet in R2 — read with DuckDB.
- Anything that fails (missing secrets, network, schema mismatch)
  falls back to the local CSV under `data/` and emits a warning.

The historical public API (`fetch_part_d_data`, `fetch_part_b_data`,
`load_geo_variation`, `load_ahrf`, `load_hpsa`) is preserved so app.py
keeps working unchanged. New callers should prefer `load_dataset` /
`get_metric`.
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from _pg_loader import (
    inventory_stats as _pg_inventory_stats,
    lookup_storage as _pg_lookup_storage,
    pivot_to_wide as _pg_pivot_to_wide,
    query_observations_long as _pg_query_observations_long,
    update_row_count as _pg_update_row_count,
)
from _r2_loader import query_r2 as _r2_query, refresh_row_count as _r2_refresh_row_count

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Last-resort fallback CSVs for the legacy load_* functions.
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


# Caching shim — streamlit's cache_data if available, else a no-op.
try:
    import streamlit as st
    cache_data = st.cache_data
except ImportError:  # pragma: no cover
    def cache_data(func=None, **_kwargs):
        if func is None:
            return lambda f: f
        return func


@lru_cache(maxsize=256)
def _lookup_storage(dataset_key: str) -> dict | None:
    """Fetch one dataset_registry row, cached for the process lifetime."""
    return _pg_lookup_storage(dataset_key)


@cache_data(ttl=3600, show_spinner=False)
def get_inventory_stats() -> dict:
    """Header-banner inventory counts from dataset_registry, cached 1h.

    Falls back to a non-stale snapshot (captured 2026-05) if Postgres is
    unreachable, so the header never reverts to the old hardcoded
    81/7.4M/23 or breaks.
    """
    stats = _pg_inventory_stats()
    if stats and stats.get("n_datasets"):
        return stats
    # Non-stale snapshot (captured 2026-05, post agency-metadata backfill).
    return {"n_datasets": 98, "total_rows": 17_684_243, "n_agencies": 27}


_row_count_seen: set[str] = set()


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

    Returns a wide DataFrame by default. Pass `long_format=True` to keep
    the raw `observations` shape (only meaningful for Postgres-backed
    datasets). `csv_fallback` is the local CSV path to read if the
    remote path fails.
    """
    filters = {"state": state, "year": year, "county": county,
               "metric_name": metric_name}

    reg = _lookup_storage(dataset_key)
    storage = (reg or {}).get("storage_location")

    if storage == "r2":
        path = reg.get("parquet_path") or f"{dataset_key}.parquet"
        try:
            df = _r2_query(path, filters)
            if dataset_key not in _row_count_seen:
                _row_count_seen.add(dataset_key)
                _r2_refresh_row_count(dataset_key, path, _pg_update_row_count)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("R2 read failed for %s (%s) — falling back to CSV", dataset_key, exc)

    elif storage == "postgres":
        try:
            long_df = _pg_query_observations_long(dataset_key, filters)
            if long_format:
                return long_df
            return _pg_pivot_to_wide(long_df)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres read failed for %s (%s) — falling back to CSV", dataset_key, exc)

    elif reg is None:
        logger.warning("No dataset_registry entry for %s — using CSV fallback", dataset_key)

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
    """Convenience wrapper for a single metric. Returns long-format slice."""
    reg = _lookup_storage(dataset_key)
    storage = (reg or {}).get("storage_location")

    if storage == "postgres":
        try:
            df = _pg_query_observations_long(
                dataset_key,
                {"state": state, "year": year, "county": county,
                 "metric_name": metric_name},
            )
            cols = [c for c in ("state", "county", "year", "month",
                                "metric_name", "metric_value", "sex",
                                "race", "age_group") if c in df.columns]
            return df[cols] if cols else df
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_metric Postgres read failed for %s/%s: %s",
                           dataset_key, metric_name, exc)

    # R2 or fallback: load wide and synthesise the long slice.
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
    """Load HRSA AHRF state+national workforce file (52 rows, 1448 vars)."""
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
    if "state" in df.columns and "st_abbrev" not in df.columns:
        df = df.rename(columns={"state": "st_abbrev"})
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


if __name__ == "__main__":
    fetch_part_d_data()
    fetch_part_b_data()
    load_geo_variation()
    load_ahrf()
    load_hpsa()
