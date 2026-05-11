"""Fetch CDC/ATSDR Social Vulnerability Index 2022 at U.S. census-tract level.

SVI ranks every U.S. census tract on 16 underlying social factors grouped
into 4 themes (Socioeconomic Status / Household Characteristics / Racial
& Ethnic Minority Status / Housing Type & Transportation), then composes
those into an overall percentile rank `RPL_THEMES`. This dataset is the
"who is most exposed if an outbreak hits" layer for Outbreak Watch and
the population-vulnerability axis for the future Workforce Atlas.

Geography:
    U.S. database — tracts are ranked nationally (vs. state-level files,
    which rank tracts only against other tracts in the same state). The
    US-database file is the right choice for nationwide analysis.

Source URL construction:
    The CDC portal at https://svi.cdc.gov/dataDownloads/data-download.html
    is JavaScript-driven, but loadXML.js constructs the file path as:
        https://svi.cdc.gov/Documents/Data/{year}/csv/states/SVI_{year}_US.csv
    when territory=US + GeographyType=census. We hardcode that URL here.

Output: data/cdc_svi_2022_tract.csv with all SVI columns intact.
License: open public data, attribute CDC/ATSDR.
Refresh: biennial — next SVI release expected ~late 2026.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
# Filename matches the dataset_key (cdc_svi_tract) so the auto-discovery
# loop in scripts/migrate_to_neon_r2.py picks it up cleanly. Year is
# tracked separately in dataset_registry.year_start / year_end.
OUT = ROOT / "data" / "cdc_svi_tract.csv"

URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/SVI_2022_US.csv"


def main() -> None:
    print(f"GET {URL}")
    r = requests.get(URL, timeout=600, stream=True)
    r.raise_for_status()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with OUT.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)
    print(f"  wrote {OUT} ({total / 1e6:.1f} MB)")

    # Light validation pass — read header + a sample to confirm schema is sane.
    df = pd.read_csv(OUT, low_memory=False)
    # SVI 2022 covers all U.S. census tracts from the 2020 Census redraw,
    # which raised the tract count from ~74K (2010-vintage SVI) to ~84K.
    expected_min = 73_000
    expected_max = 86_000
    print(f"\nShape: {df.shape}")
    print(f"Columns: {len(df.columns)} ({list(df.columns[:8])} ...)")
    if not (expected_min <= len(df) <= expected_max):
        print(f"  WARN:row count {len(df):,} outside expected range "
              f"[{expected_min:,}, {expected_max:,}] — investigate")
    if "FIPS" in df.columns:
        n_unique = df["FIPS"].nunique()
        print(f"FIPS distinct values: {n_unique:,} "
              f"(should equal row count for tract-level data)")
        if n_unique != len(df):
            print(f"  WARN:FIPS not unique — possible duplicate rows")
    if "RPL_THEMES" in df.columns:
        rpl = pd.to_numeric(df["RPL_THEMES"], errors="coerce")
        rpl = rpl[rpl >= 0]  # SVI uses -999 as a missing-data sentinel
        print(f"RPL_THEMES range (non-sentinel): {rpl.min():.4f} – {rpl.max():.4f}")
    if "ST_ABBR" in df.columns:
        print(f"Distinct states (ST_ABBR): {df['ST_ABBR'].nunique()}")


if __name__ == "__main__":
    main()
