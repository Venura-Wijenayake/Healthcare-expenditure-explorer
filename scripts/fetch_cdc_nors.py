"""Fetch CDC National Outbreak Reporting System (NORS) — historical outbreak record.

NORS is the federal record of foodborne, waterborne, and enteric (and as of
2023, fungal) disease outbreak reports submitted by state, local, and
territorial health departments. The streamlined public release on
data.cdc.gov is the canonical programmatic source.

Source:
    https://data.cdc.gov/resource/5xkq-dg7x  (resource id 5xkq-dg7x)
    Catalog page: https://data.cdc.gov/dataset/NORS/5xkq-dg7x

Schema (19 cols): year, month, state, primary_mode, etiology, serotype_or_
    genotype, etiology_status, setting, illnesses, hospitalizations,
    info_on_hospitalizations, deaths, info_on_deaths, food_vehicle,
    food_contaminated_ingredient, ifsac_category, water_exposure,
    water_type, animal_type.

Coverage caveats (also documented in the MANIFEST):
    - Reports begin in 1971 (waterborne) / 1973 (foodborne); the dataset
      runs through the most recent close-out year (currently 2023 at time
      of writing).
    - CDC close-out lag is 12–18 months — this is HISTORICAL DEPTH, not
      real-time surveillance. Pair with FluView/NNDSS for current signal.
    - State/local reporting is voluntary; coverage varies by jurisdiction.

License: open public data, attribute CDC.
Refresh: annual (matches CDC's close-out window).
Output: data/cdc_nors.csv with all 19 columns preserved.
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cdc_nors.csv"

RESOURCE_ID = "5xkq-dg7x"
BASE = f"https://data.cdc.gov/resource/{RESOURCE_ID}.csv"
PAGE_SIZE = 50_000


def fetch_socrata_csv(retries: int = 3, sleep: float = 2.0) -> pd.DataFrame:
    """Page through the Socrata CSV endpoint with retry/backoff.

    NORS is ~66k rows so a single 50k-page pull plus one tail page is
    enough; the loop generalizes in case the dataset grows past one page
    in the future.
    """
    chunks: list[pd.DataFrame] = []
    offset = 0
    while True:
        params = {"$limit": PAGE_SIZE, "$offset": offset, "$order": ":id"}
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                r = requests.get(BASE, params=params, timeout=180)
                r.raise_for_status()
                chunk = pd.read_csv(io.StringIO(r.text), low_memory=False)
                break
            except requests.RequestException as exc:
                last_err = exc
                if attempt < retries:
                    time.sleep(sleep * attempt)
        else:
            raise RuntimeError(
                f"NORS Socrata fetch failed after {retries} retries "
                f"at offset {offset}: {last_err}"
            )
        print(f"  offset={offset:>6,}  rows={len(chunk):,}")
        if chunk.empty:
            break
        chunks.append(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def main() -> int:
    print(f"[1/3] Fetching CDC NORS from {BASE}")
    df = fetch_socrata_csv()
    if df.empty:
        raise SystemExit("NORS fetch returned no rows — refusing to overwrite local CSV.")

    print(f"[2/3] Validating schema ({df.shape})")
    # Year should be 4-digit ints; some Socrata exports come through as
    # strings — coerce defensively.
    for c in ("year", "month", "illnesses", "hospitalizations",
              "info_on_hospitalizations", "deaths", "info_on_deaths"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["year"] = df["year"].astype("Int64")
    if "month" in df.columns:
        df["month"] = df["month"].astype("Int64")

    print(f"[3/3] Writing CSV")
    df = df.sort_values(["year", "month", "state"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    size_mb = OUT.stat().st_size / 1e6

    print()
    print(f"Wrote {OUT} ({size_mb:.2f} MB, {len(df):,} rows × {len(df.columns)} cols)")
    print(f"  year range:   {int(df['year'].min())}–{int(df['year'].max())}")
    print(f"  states:       {df['state'].nunique()}")
    if "etiology" in df.columns:
        print(f"  etiologies:   {df['etiology'].nunique()} distinct")
    print()
    print("Top 5 pathogens by outbreak count:")
    print(df["etiology"].value_counts().head(5).to_string())
    print()
    print("Top 5 settings:")
    print(df["setting"].value_counts().head(5).to_string())
    print()
    print("Year-of-report distribution (last 5 years):")
    print(df["year"].value_counts().sort_index().tail(5).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
