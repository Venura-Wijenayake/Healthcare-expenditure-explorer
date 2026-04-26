"""Fetch CDC NNDSS (National Notifiable Diseases Surveillance System) data.

Stacks two complementary Socrata resources from data.cdc.gov:
  1. NNDSS Weekly Data (x9gk-5huc) - weekly state-level case counts for ~115
     notifiable diseases (TB, hepatitis A/B/C, salmonella, pertussis, mumps,
     measles, malaria, meningococcal, etc.) for 2024 onward.
  2. Lyme disease public use aggregated data with geography (x5j9-wybp) -
     annual county/state-level Lyme cases by demographics for 2022-2023
     (Lyme is not included in the weekly comprehensive table).

Output: data/cdc_nndss.csv with a `disease_table` column distinguishing the
two source tables. A unified subset of columns is kept; source-specific
columns are NaN where not applicable.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cdc_nndss.csv"

WEEKLY_RESOURCE = "x9gk-5huc"  # NNDSS Weekly Data
LYME_RESOURCE = "x5j9-wybp"    # Lyme aggregated public use 2022-2023

BASE = "https://data.cdc.gov/resource/{rid}.csv"


def fetch(resource_id: str, params: dict) -> pd.DataFrame:
    """Fetch a Socrata CSV resource with paging."""
    url = BASE.format(rid=resource_id)
    print(f"GET {url}  params={params}")
    r = requests.get(url, params=params, timeout=600)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), low_memory=False)
    print(f"  -> {len(df):,} rows, {df.shape[1]} cols")
    return df


def fetch_paged(resource_id: str, where: str | None, page: int = 50000) -> pd.DataFrame:
    """Fetch a Socrata resource in chunks via $limit/$offset."""
    frames: list[pd.DataFrame] = []
    offset = 0
    while True:
        params = {"$limit": page, "$offset": offset, "$order": ":id"}
        if where:
            params["$where"] = where
        chunk = fetch(resource_id, params)
        if chunk.empty:
            break
        frames.append(chunk)
        if len(chunk) < page:
            break
        offset += page
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    # --- Weekly NNDSS (filter to 2024 to stay under 50 MB cap) ---
    weekly = fetch_paged(WEEKLY_RESOURCE, where="year='2024'")
    weekly["disease_table"] = "weekly_nndss"
    # Standardize columns
    weekly = weekly.rename(
        columns={
            "states": "reporting_area",
            "label": "disease",
            "m1": "current_week_cases",
            "m2": "previous_52wk_max",
            "m3": "cum_ytd_current",
            "m4": "cum_ytd_previous",
        }
    )
    keep_weekly = [
        "disease_table",
        "reporting_area",
        "year",
        "week",
        "disease",
        "current_week_cases",
        "previous_52wk_max",
        "cum_ytd_current",
        "cum_ytd_previous",
        "geocode",
    ]
    weekly = weekly[[c for c in keep_weekly if c in weekly.columns]]

    # --- Lyme disease aggregated 2022-2023 ---
    lyme = fetch_paged(LYME_RESOURCE, where=None)
    lyme["disease_table"] = "lyme_aggregated"
    lyme["disease"] = "Lyme disease"
    lyme = lyme.rename(
        columns={
            "state": "reporting_area",
            "frequency": "annual_cases",
        }
    )
    keep_lyme = [
        "disease_table",
        "reporting_area",
        "year",
        "disease",
        "case_status",
        "sex",
        "age_cat_yrs",
        "annual_cases",
        "fips",
    ]
    lyme = lyme[[c for c in keep_lyme if c in lyme.columns]]

    # --- Stack ---
    combined = pd.concat([weekly, lyme], ignore_index=True, sort=False)
    print(f"\nCombined shape: {combined.shape}")
    print(f"Columns: {list(combined.columns)}")
    print(f"disease_table counts:\n{combined['disease_table'].value_counts()}")
    print(f"Year range: {combined['year'].min()} - {combined['year'].max()}")
    print(f"Unique reporting areas: {combined['reporting_area'].nunique()}")
    print(f"Unique diseases: {combined['disease'].nunique()}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT, index=False)
    size_mb = OUT.stat().st_size / 1e6
    print(f"\nWrote {OUT} ({size_mb:.1f} MB, {len(combined):,} rows)")


if __name__ == "__main__":
    main()
