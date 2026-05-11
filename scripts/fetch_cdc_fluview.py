"""Fetch CDC FluView / ILINet weekly influenza-like-illness surveillance.

Pulls weekly state + national ILINet records from the CMU Delphi Epidata
mirror of CDC FluView, which is the standard programmatic interface for
this data (cleaner schema and pagination than CDC's portal). FluView is
the real-time respiratory illness signal — current-week, weekly cadence
— that NNDSS lacks (NNDSS is reported with a 1-2 week lag).

API base:  https://api.delphi.cmu.edu/epidata/fluview/
Docs:      https://cmu-delphi.github.io/delphi-epidata/api/fluview.html
Coverage:  50 states + DC + Puerto Rico + national ("nat"), starting
           epiweek 201540 (start of the 2015-16 flu season).
License:   open public data, attribution to CDC + CMU Delphi.

Output: data/cdc_fluview_ilinet.csv with one row per (region, epiweek).
Re-runs are safe — the script writes a fresh CSV each invocation.
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cdc_fluview_ilinet.csv"

API = "https://api.delphi.cmu.edu/epidata/fluview/"

# 50 states + DC + Puerto Rico + national. Lowercase 2-letter codes are
# the Delphi convention; "nat" is the U.S. national rollup.
REGIONS: list[str] = [
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma",
    "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny",
    "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx",
    "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "pr", "nat",
]

# 2015-16 flu season starts at MMWR week 40 of 2015.
SEASON_START_EPIWEEK = 201540

# Fields we keep. `release_date` and `lag` carry the provisional-vs-final
# context that downstream views may need (FluView is revised weekly).
# Age-bucket columns (num_age_0..5) are kept but mostly null at the state
# level — they're populated for the national aggregate only.
KEEP_COLS = [
    "region", "epiweek", "issue", "lag", "release_date",
    "num_ili", "num_patients", "num_providers",
    "ili", "wili",
]


def _current_epiweek_floor() -> int:
    """Return today's CDC MMWR epiweek as YYYYWW.

    Uses ISO week-of-year as a proxy. MMWR and ISO week numbering differ
    by at most a day at the year boundary; for "what range to query" this
    is close enough — the API tolerates over-requesting and just returns
    the rows that exist.
    """
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    return iso_year * 100 + iso_week


def _epiweek_range_for_year(year: int) -> str:
    """Return the query string for a single MMWR year's weeks.

    A handful of years (2015, 2020, 2026) have 53 weeks; over-requesting
    is harmless, the API silently drops empty weeks.
    """
    return f"{year}01-{year}53"


def fetch_year(year: int, regions: list[str], retries: int = 3,
               sleep: float = 1.0) -> pd.DataFrame:
    """Pull one MMWR year × all regions in a single request.

    Year-sized requests stay well under any reasonable URL/response
    cap (53 regions × ~52 weeks = ~2,750 rows). Pulling year-by-year
    instead of one mega-request keeps progress visible and lets a
    transient failure retry only one slice.
    """
    params = {
        "regions": ",".join(regions),
        "epiweeks": _epiweek_range_for_year(year),
    }
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(API, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            if data.get("result") != 1:
                # Delphi returns result=1 on success, -2 when no rows match;
                # treat -2 as "no data for this year" rather than an error.
                if data.get("result") == -2:
                    return pd.DataFrame(columns=KEEP_COLS)
                raise RuntimeError(
                    f"Delphi API result={data.get('result')} "
                    f"message={data.get('message')!r}"
                )
            rows = data.get("epidata", [])
            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame(columns=KEEP_COLS)
            keep = [c for c in KEEP_COLS if c in df.columns]
            return df[keep].copy()
        except (requests.RequestException, RuntimeError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(sleep * attempt)
    raise RuntimeError(f"FluView fetch failed for {year} after {retries} retries: {last_err}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--start-year", type=int, default=2015,
        help="First MMWR year to fetch (default 2015 — covers the 2015-16 season onward).",
    )
    p.add_argument(
        "--end-year", type=int, default=None,
        help="Last MMWR year to fetch (default: current calendar year).",
    )
    args = p.parse_args(argv)
    end_year = args.end_year or date.today().year

    print(f"FluView fetch — MMWR years {args.start_year}–{end_year} "
          f"× {len(REGIONS)} regions")
    frames: list[pd.DataFrame] = []
    for year in range(args.start_year, end_year + 1):
        df = fetch_year(year, REGIONS)
        print(f"  {year}: {len(df):>5,} rows")
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if combined.empty:
        raise SystemExit("No FluView data returned — refusing to write an empty CSV.")

    # The 2015-16 flu season starts at MMWR week 40 of 2015. Trim earlier
    # weeks so the dataset starts cleanly at the season boundary.
    if "epiweek" in combined.columns:
        combined = combined[combined["epiweek"].astype("int64") >= SEASON_START_EPIWEEK]

    # epiweek arrives as int; keep it that way for downstream filter
    # pushdown (DuckDB picks int columns up cleanly).
    combined["epiweek"] = combined["epiweek"].astype("int64")
    if "issue" in combined.columns:
        combined["issue"] = pd.to_numeric(combined["issue"], errors="coerce").astype("Int64")
    if "lag" in combined.columns:
        combined["lag"] = pd.to_numeric(combined["lag"], errors="coerce").astype("Int64")
    for c in ("num_ili", "num_patients", "num_providers", "ili", "wili"):
        if c in combined.columns:
            combined[c] = pd.to_numeric(combined[c], errors="coerce")

    combined = combined.sort_values(["region", "epiweek"]).reset_index(drop=True)

    print(f"\nCombined shape: {combined.shape}")
    print(f"Columns: {list(combined.columns)}")
    print(f"Regions: {combined['region'].nunique()} "
          f"(epiweek range {combined['epiweek'].min()}–{combined['epiweek'].max()})")
    print(f"Non-null wili rows: {combined['wili'].notna().sum():,}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT, index=False)
    size_mb = OUT.stat().st_size / 1e6
    print(f"\nWrote {OUT} ({size_mb:.2f} MB, {len(combined):,} rows)")


if __name__ == "__main__":
    main()
