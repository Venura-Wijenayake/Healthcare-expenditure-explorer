"""
Fetch FCC Broadband Data Collection (BDC) county-level summary.

Source: ArcGIS Living Atlas hosted feature service published by Esri,
mirroring FCC BDC nationwide data.
  Item:  https://www.arcgis.com/home/item.html?id=22ca3a8bb2ff46c1983fb45414157b08
  Title: "FCC Broadband Data Collection June 2024"
  Layer: 1 (Counties)

Outputs: data/fcc_broadband.csv  (one row per US county / FIPS).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fcc_broadband.csv"

SERVICE = (
    "https://services.arcgis.com/jIL9msH9OI208GCb/arcgis/rest/services/"
    "FCC_Broadband_Data_Collection_June_2022/FeatureServer/1/query"
)

FIELDS = [
    "GEOID", "CountyName", "StateName", "StateAbbr", "StateGEOID",
    "TotalPop", "TotalBSLs",
    "UnservedBSLs", "UnderservedBSLs", "ServedBSLs",
    "UnservedBSLsCopper", "UnderservedBSLsCopper", "ServedBSLsCopper",
    "UnservedBSLsCable", "UnderservedBSLsCable", "ServedBSLsCable",
    "UnservedBSLsFiber", "UnderservedBSLsFiber", "ServedBSLsFiber",
    "UnservedBSLsLTFW", "UnderservedBSLsLTFW", "ServedBSLsLTFW",
    "UnservedBSLsLBRTFW", "UnderservedBSLsLBRTFW", "ServedBSLsLBRTFW",
    "UniqueProviders", "UniqueProvidersCopper", "UniqueProvidersCable",
    "UniqueProvidersFiber", "UniqueProvidersLTFW", "UniqueProvidersLBRTFW",
    "Perc_Change_UnservedBSLs_12monthPrevious",
    "Perc_Change_UnderservedBSLs_12monthPrevious",
    "Perc_Change_ServedBSLs_12monthPrevious",
]


def fetch_page(offset: int, page: int = 2000) -> list[dict]:
    params = {
        "where": "1=1",
        "outFields": ",".join(FIELDS),
        "returnGeometry": "false",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": page,
        "orderByFields": "GEOID",
    }
    for attempt in range(4):
        try:
            r = requests.get(SERVICE, params=params, timeout=60,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            payload = r.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return [feat["attributes"] for feat in payload.get("features", [])]
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  attempt {attempt+1} failed ({exc}); retrying in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up at offset {offset}")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    page = 2000
    offset = 0
    while True:
        chunk = fetch_page(offset, page)
        if not chunk:
            break
        rows.extend(chunk)
        print(f"fetched offset={offset}  cumulative_rows={len(rows)}")
        if len(chunk) < page:
            break
        offset += page

    df = pd.DataFrame(rows)
    # Ensure 5-digit FIPS (drop ".0" if numeric)
    if "GEOID" in df.columns:
        df["GEOID"] = df["GEOID"].astype(str).str.zfill(5)

    # Derived percentages for telehealth analysis convenience
    import numpy as np
    bsl = df["TotalBSLs"].astype(float).replace(0, np.nan)
    df["pct_served_100_20"] = (df["ServedBSLs"].astype(float) / bsl * 100).round(2)
    df["pct_underserved_25_3_to_100_20"] = (df["UnderservedBSLs"].astype(float) / bsl * 100).round(2)
    df["pct_unserved"] = (df["UnservedBSLs"].astype(float) / bsl * 100).round(2)
    df["pct_fiber_served"] = (df["ServedBSLsFiber"].astype(float) / bsl * 100).round(2)
    df["release"] = "FCC BDC June 2024"

    df.to_csv(OUT, index=False)
    print(f"\nwrote {OUT}  shape={df.shape}")
    print(f"unique counties (GEOID): {df['GEOID'].nunique()}")
    print(f"states covered: {df['StateAbbr'].nunique()}")
    print("columns:", list(df.columns))


if __name__ == "__main__":
    main()
