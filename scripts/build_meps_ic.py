"""
Build a tidy state-level MEPS-IC dataset.

Source: AHRQ MEPS Insurance Component state tables (private-sector, by state).
URL pattern: https://meps.ahrq.gov/data_stats/summ_tables/insr/excel/{year}/{StateName}{year}.xlsx
We pull "Table II" from each workbook, which provides the canonical
state-total private-sector estimates (premium, contribution, enrollment,
deductible, copayment, etc.) plus the standard error.

Output: D:/Claudius/healthcare-expenditure-explorer/data/ahrq_meps.csv
"""
from __future__ import annotations
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd

ROOT = Path(r"D:\Claudius\healthcare-expenditure-explorer")
BUILD = ROOT / ".build" / "meps_ic"
OUT = ROOT / "data" / "ahrq_meps.csv"
BUILD.mkdir(parents=True, exist_ok=True)

# 50 states + DC. The XLSX filenames use the long state name with no spaces,
# except for "District of Columbia" (which we'll handle separately if needed).
STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "DistrictofColumbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "NewHampshire",
    "NewJersey", "NewMexico", "NewYork", "NorthCarolina", "NorthDakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "RhodeIsland",
    "SouthCarolina", "SouthDakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "WestVirginia", "Wisconsin", "Wyoming",
]
PRETTY = {
    "DistrictofColumbia": "District of Columbia",
    "NewHampshire": "New Hampshire",
    "NewJersey": "New Jersey",
    "NewMexico": "New Mexico",
    "NewYork": "New York",
    "NorthCarolina": "North Carolina",
    "NorthDakota": "North Dakota",
    "RhodeIsland": "Rhode Island",
    "SouthCarolina": "South Carolina",
    "SouthDakota": "South Dakota",
    "WestVirginia": "West Virginia",
}
YEARS = [2020, 2021, 2022, 2023, 2024]

URL_TMPL = "https://meps.ahrq.gov/data_stats/summ_tables/insr/excel/{year}/{state}{year}.{ext}"


def download(year: int, state: str) -> Path | None:
    """Try .xlsx (modern years) then .xls (older)."""
    for ext in ("xlsx", "xls"):
        fname = f"{state}{year}.{ext}"
        dest = BUILD / fname
        if dest.exists() and dest.stat().st_size > 5_000:
            return dest
        url = URL_TMPL.format(year=year, state=state, ext=ext)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 5_000:
                continue
            dest.write_bytes(data)
            return dest
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            print(f"  HTTP {e.code} for {url}")
            return None
        except Exception as e:
            print(f"  ERR {e} for {url}")
            return None
    return None


SUPPRESSED = {"suppressed", "suppr.", "*", "--", "n/a", "na", ""}


def parse_value(raw):
    """Convert MEPS cell strings ('7,645�', '55.6%�', 'suppressed') to (numeric, unit)."""
    if pd.isna(raw):
        return (None, None)
    s = str(raw).strip()
    # Strip trailing markers: NBSP ( ), Unicode replacement char, RSE asterisks, footnote letters.
    s_clean = re.sub(r"[^0-9.,%\-]+$", "", s).strip()
    if s_clean.lower() in SUPPRESSED or "suppress" in s_clean.lower():
        return (None, "suppressed")
    is_pct = s_clean.endswith("%")
    if is_pct:
        s_clean = s_clean[:-1]
    s_clean = s_clean.replace(",", "").replace("$", "").strip()
    try:
        v = float(s_clean)
        return (v, "percent" if is_pct else "value")
    except ValueError:
        return (None, "unparsed")


def parse_workbook(path: Path, year: int, state_pretty: str) -> pd.DataFrame:
    """Extract Table II (state totals) from one MEPS-IC workbook."""
    engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
    try:
        df = pd.read_excel(path, sheet_name="Table II", header=None, engine=engine)
    except Exception as e:
        print(f"  parse error {path.name}: {e}")
        return pd.DataFrame()
    # Row 1 is header (Table No., Description, Total, ...)
    # Row 2+ are data. Col 0=table_no, 1=description, 2=Total, then firm-size
    # breakouts and standard errors. We keep the Total + Std. Err. Total.
    rows = []
    n_cols = df.shape[1]
    # Find column indices for Total and Std. Err. Total
    header = df.iloc[1].tolist()
    try:
        i_total = header.index("Total")
    except ValueError:
        i_total = 2
    se_total_col = None
    for j, h in enumerate(header):
        if isinstance(h, str) and h.strip() == "Std. Err. Total":
            se_total_col = j
            break

    for i in range(2, len(df)):
        tno = df.iloc[i, 0]
        desc = df.iloc[i, 1]
        if pd.isna(tno) or pd.isna(desc):
            continue
        raw = df.iloc[i, i_total]
        val, unit = parse_value(raw)
        se_raw = df.iloc[i, se_total_col] if se_total_col is not None else None
        se_val, _ = parse_value(se_raw)
        rows.append({
            "year": year,
            "state": state_pretty,
            "table_no": str(tno).strip(),
            "indicator": str(desc).strip(),
            "value": val,
            "std_error": se_val,
            "unit": unit,
            "raw_value": str(raw) if not pd.isna(raw) else None,
        })
    return pd.DataFrame(rows)


def main() -> int:
    all_frames = []
    for year in YEARS:
        for st in STATES:
            path = download(year, st)
            if path is None:
                continue
            pretty = PRETTY.get(st, st)
            sub = parse_workbook(path, year, pretty)
            if not sub.empty:
                all_frames.append(sub)
                print(f"  {year} {pretty}: {len(sub)} rows")
            time.sleep(0.05)
    if not all_frames:
        print("No data parsed!", file=sys.stderr)
        return 1
    df = pd.concat(all_frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print()
    print(f"Wrote {OUT}")
    print(f"Shape: {df.shape}")
    print(f"Years: {sorted(df['year'].unique().tolist())}")
    print(f"States: {df['state'].nunique()}")
    print(f"Distinct indicators (table_no): {df['table_no'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
