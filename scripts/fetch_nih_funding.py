"""
Fetch NIH RePORTER project data and aggregate to state x fiscal_year x institute.

Source: https://api.reporter.nih.gov/v2/projects/search
Output: data/nih_research_funding.csv (aggregated, not grant-level)
"""
import json
import time
import sys
from collections import defaultdict
from pathlib import Path

import requests
import pandas as pd

API = "https://api.reporter.nih.gov/v2/projects/search"

# 50 states + DC + PR (RePORTER uses USPS abbreviations)
STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM",
    "NY","NC","ND","OH","OK","OR","PA","PR","RI","SC","SD","TN","TX","UT","VT","VA",
    "WA","WV","WI","WY",
]
FISCAL_YEARS = [2020, 2021, 2022, 2023, 2024]
PAGE = 500
MAX_OFFSET = 14_500  # API caps near 15,000


def fetch_state_year(state: str, fy: int):
    """Yield project records for a single state x fiscal_year."""
    offset = 0
    while True:
        body = {
            "criteria": {"fiscal_years": [fy], "org_states": [state]},
            "include_fields": [
                "AwardAmount",
                "FiscalYear",
                "Organization",
                "AgencyIcAdmin",
            ],
            "limit": PAGE,
            "offset": offset,
        }
        for attempt in range(5):
            try:
                r = requests.post(API, json=body, timeout=60)
                if r.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
        results = data.get("results", [])
        total = data["meta"]["total"]
        for rec in results:
            yield rec
        offset += PAGE
        if offset >= total:
            break
        if offset > MAX_OFFSET:
            print(f"  WARN: {state} FY{fy} hit offset cap ({total} total)", file=sys.stderr)
            break
        time.sleep(0.1)


def main():
    out_path = Path("data/nih_research_funding.csv")
    out_path.parent.mkdir(exist_ok=True)

    # key: (fiscal_year, state, institute_code, institute_abbrev) -> {amount, count}
    agg = defaultdict(lambda: {"award_amount_usd": 0.0, "project_count": 0})

    grand_total_records = 0
    for fy in FISCAL_YEARS:
        fy_records = 0
        for state in STATES:
            n = 0
            for rec in fetch_state_year(state, fy):
                amt = rec.get("award_amount") or 0
                ic = rec.get("agency_ic_admin") or {}
                ic_code = ic.get("code") or "UNK"
                ic_abbrev = ic.get("abbreviation") or ic_code
                key = (fy, state, ic_code, ic_abbrev)
                agg[key]["award_amount_usd"] += float(amt)
                agg[key]["project_count"] += 1
                n += 1
            fy_records += n
        print(f"FY{fy}: {fy_records:,} project records aggregated", flush=True)
        grand_total_records += fy_records

    rows = []
    for (fy, state, ic_code, ic_abbrev), v in agg.items():
        rows.append({
            "fiscal_year": fy,
            "state": state,
            "institute_code": ic_code,
            "institute_abbrev": ic_abbrev,
            "award_amount_usd": round(v["award_amount_usd"], 2),
            "project_count": v["project_count"],
        })
    df = pd.DataFrame(rows).sort_values(
        ["fiscal_year", "state", "institute_code"]
    ).reset_index(drop=True)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} -- {len(df):,} aggregated rows from {grand_total_records:,} projects")
    print(df.head())


if __name__ == "__main__":
    main()
