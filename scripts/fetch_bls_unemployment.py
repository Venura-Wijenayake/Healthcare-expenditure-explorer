"""
Fetch monthly state-level unemployment rates from BLS Local Area Unemployment
Statistics (LAUS), 2020-2025.

Series ID format: LASST{FIPS}0000000000003
  - LAS  : LAUS program prefix
  - ST   : state-level
  - FIPS : 2-digit state FIPS code
  - 00000000 : zero-padded area code (state-level)
  - 03   : measure code 3 = unemployment rate
  - Note: full series ID is 20 chars: LASST + FIPS(2) + 00000000000(11) + 03(2)

Public BLS API tier (no key) limits:
  - 25 series per request
  - 10 years per series
  - 25 requests per day
"""
import json
import time
from io import StringIO

import pandas as pd
import requests

# 50 states + DC FIPS codes (2-digit)
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
    "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56",
}
FIPS_TO_STATE = {v: k for k, v in STATE_FIPS.items()}

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Correct LAUS state series ID is 20 chars:
#   "LAU" (3) + "ST" prefix (2) + state_fips (2) + area_code padded to 13 zeros + measure(2) ?
# Actually verified format from BLS docs:
#   prefix "LAS"(3) + seasonal "S"/"U"(1) + area_type "ST"(2) + state_fips(2) + area_code(13 zeros) + measure(2) -> too long
# Real format (from BLS LAUS series ID structure handbook):
#   positions 1-2: "LA" (survey)
#   pos 3: seasonal adjustment (S or U)
#   pos 4-5: area type ("ST" = state)
#   pos 6-20: 15-char area code -> for state = state_fips (2) + 13 zeros
#   pos 21-22: measure code (03 = unemployment rate)
# Total length = 22 chars. Example: LASST010000000000000003
# Use "U" for not-seasonally-adjusted.
def build_series_id(fips: str, seasonal: str = "U") -> str:
    # LA + S(seasonal) + ST + fips(2) + 13 zeros + 03 = 22 chars
    return f"LA{seasonal}ST{fips}0000000000000" + "03"


def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def fetch_bls(series_ids, start_year, end_year):
    headers = {"Content-type": "application/json"}
    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    r = requests.post(BLS_URL, data=json.dumps(payload), headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_fred_fallback():
    """Fallback: download FRED's monthly state unemployment series (UR<STATE>)."""
    rows = []
    base = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
    for state in STATE_FIPS:
        # FRED IDs: state unemployment rate not seasonally adjusted = <STATE>URN, seasonally adjusted = <STATE>UR
        sid = f"{state}URN"
        url = f"{base}{sid}&cosd=2020-01-01&coed=2025-12-31"
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
            df.columns = ["date", "unemployment_rate"]
            df["date"] = pd.to_datetime(df["date"])
            df["state"] = state
            df["year"] = df["date"].dt.year
            df["month"] = df["date"].dt.month
            df = df[df["year"].between(2020, 2025)]
            df["unemployment_rate"] = pd.to_numeric(df["unemployment_rate"], errors="coerce")
            rows.append(df[["state", "year", "month", "unemployment_rate"]])
            time.sleep(0.3)
            print(f"  FRED {sid}: {len(df)} rows")
        except Exception as e:
            print(f"  FRED {sid} FAILED: {e}")
    return pd.concat(rows, ignore_index=True)


def main():
    series_ids = [build_series_id(f) for f in STATE_FIPS.values()]
    print(f"Built {len(series_ids)} series IDs. Example: {series_ids[0]} (length={len(series_ids[0])})")

    all_rows = []
    bls_succeeded = True
    try:
        for batch_idx, batch in enumerate(chunked(series_ids, 17), start=1):
            print(f"\nBatch {batch_idx}: {len(batch)} series, years 2020-2025")
            resp = fetch_bls(batch, 2020, 2025)
            status = resp.get("status")
            print(f"  status={status}, message={resp.get('message')}")
            if status != "REQUEST_SUCCEEDED":
                bls_succeeded = False
                print("  BLS request did not succeed. Aborting BLS path.")
                break
            series_list = resp.get("Results", {}).get("series", [])
            n_with_data = sum(1 for s in series_list if s.get("data"))
            print(f"  series returned: {len(series_list)}, with data: {n_with_data}")
            if n_with_data == 0:
                bls_succeeded = False
                print("  No series had data. Aborting BLS path.")
                break
            for series in resp["Results"]["series"]:
                sid = series["seriesID"]
                # 22-char ID: LA + S + ST + fips(2) at positions 5-6 (0-indexed)
                fips = sid[5:7]
                state = FIPS_TO_STATE.get(fips, "??")
                for d in series["data"]:
                    period = d["period"]  # M01..M12, M13=annual
                    if not period.startswith("M") or period == "M13":
                        continue
                    month = int(period[1:])
                    try:
                        rate = float(d["value"])
                    except ValueError:
                        rate = None
                    all_rows.append({
                        "state": state,
                        "fips": fips,
                        "year": int(d["year"]),
                        "month": month,
                        "unemployment_rate": rate,
                    })
            time.sleep(1.0)
    except Exception as e:
        print(f"BLS API path failed with exception: {e}")
        bls_succeeded = False

    if not bls_succeeded or not all_rows:
        print("\nFalling back to FRED (mirrors BLS LAUS)...")
        df = fetch_fred_fallback()
        df["source"] = "FRED (BLS LAUS mirror)"
    else:
        df = pd.DataFrame(all_rows)
        df["source"] = "BLS public API v2 LAUS"

    df = df.sort_values(["state", "year", "month"]).reset_index(drop=True)
    out_path = r"D:\Claudius\healthcare-expenditure-explorer\data\bls_unemployment.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} rows to {out_path}")
    print(f"Columns: {list(df.columns)}")
    print(f"States: {df['state'].nunique()}")
    print(f"Year range: {df['year'].min()}-{df['year'].max()}")
    print(f"Month range: {df['month'].min()}-{df['month'].max()}")
    print(df.head(3).to_string(index=False))


if __name__ == "__main__":
    main()
