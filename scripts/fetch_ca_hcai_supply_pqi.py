"""Fetch CA HCAI Physician Supply × Preventable Hospitalizations by County.

CA HCAI is the only U.S. state agency that natively joins physician
supply density to AHRQ Prevention Quality Indicator (PQI) rates at the
county level. PQIs are AHRQ's standard measures of preventable
hospitalizations — admissions for conditions where good outpatient
access should keep patients out of the hospital. Pairing supply with
PQIs lets you ask "where in CA would the next clinician shift the
outcome score most?" — the optimization angle of the CA Workforce
Atlas lens.

Source dataset (CKAN):
    https://data.chhs.ca.gov/dataset/physician-supply-anticipated-retirement-of-practicing-physicians
    Two primary CSV resources:
      - PQI Physicians Data Set (county × PQI condition: supply rate +
        PQI rate + LOS + High/Low flags vs state)
      - Physician Retirement Data Set (county × condition × retirement
        horizon: % of physicians in 0-2 / 3-5 / 6-10 / 11+ year buckets)

The two resources share (county, PQI condition) as their row key. We
pivot the retirement data wide on `YearsToRetirement` so each (county,
condition) cell gets four retirement-bucket columns, then left-join
onto the PQI frame. The result is a single county × condition frame
that carries supply, outcome, and retirement-risk in one place.

Output: data/ca_hcai_supply_pqi.csv (one row per county × PQI
condition). Counties with no measurable supply or no observed
admissions for a given PQI will still appear with zeros.

PQI conditions covered (7):
    Asthma in Younger Adults (Age 18-39), Chronic Obstructive
    Pulmonary Disease (COPD), Community-Acquired Pneumonia, Congestive
    Heart Failure, Diabetes, Hypertension, Urinary Tract Infection.

License: open public data, attribute CA HCAI.
Refresh: annual (HCAI publishes after each license renewal cycle).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ca_hcai_supply_pqi.csv"
TMP = ROOT / "tmp" / "hcai_pqi"

PACKAGE_ID = "physician-supply-anticipated-retirement-of-practicing-physicians"
PKG_URL = f"https://data.chhs.ca.gov/api/3/action/package_show?id={PACKAGE_ID}"


def fetch_resource_urls() -> dict[str, str]:
    """Look up the current resource URLs from CKAN — guards against
    filename drift between extracts."""
    r = requests.get(PKG_URL, timeout=60)
    r.raise_for_status()
    pkg = r.json()["result"]
    urls: dict[str, str] = {}
    for res in pkg["resources"]:
        name = res.get("name", "")
        if res.get("format") == "CSV":
            if "PQI Physicians Data Set" in name:
                urls["pqi"] = res["url"]
            elif "Physician Retirement Data Set" in name:
                urls["retirement"] = res["url"]
    missing = [k for k in ("pqi", "retirement") if k not in urls]
    if missing:
        raise RuntimeError(f"CKAN package_show is missing expected resources: {missing}")
    return urls


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    print(f"  GET {url.rsplit('/', 1)[-1]}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


# Map "0-2 years" -> snake_case suffix for column naming.
RETIREMENT_BUCKET_SUFFIX = {
    "0-2 years": "0_2yr",
    "3-5 years": "3_5yr",
    "6-10 years": "6_10yr",
    "11+ years": "11plus_yr",
}


def main() -> int:
    print(f"[1/4] CKAN package_show -> resource URLs")
    urls = fetch_resource_urls()
    print(f"      pqi:         {urls['pqi']}")
    print(f"      retirement:  {urls['retirement']}")

    print(f"\n[2/4] downloading + parsing")
    pqi_path = download(urls["pqi"], TMP / "pqiphysicians.csv")
    ret_path = download(urls["retirement"], TMP / "physicianretirement.csv")
    pqi = pd.read_csv(pqi_path, low_memory=False)
    ret = pd.read_csv(ret_path, low_memory=False)
    print(f"      pqi:         {pqi.shape}")
    print(f"      retirement:  {ret.shape}")

    print(f"\n[3/4] pivoting retirement wide on YearsToRetirement + joining")
    ret = ret.copy()
    ret["bucket"] = ret["YearsToRetirement"].map(RETIREMENT_BUCKET_SUFFIX)
    unmapped = ret[ret["bucket"].isna()]["YearsToRetirement"].unique()
    if len(unmapped):
        raise RuntimeError(f"Unmapped YearsToRetirement values: {unmapped.tolist()}")

    wide = ret.pivot_table(
        index=["County", "Region", "PQIDescription"],
        columns="bucket",
        values=["CtyRetirePercent", "RegionRetirePercent", "StRetirePercent"],
        aggfunc="first",
    )
    # Flatten the MultiIndex column header to flat snake_case names.
    wide.columns = [f"{metric}_{bucket}".lower()
                    .replace("ctyretirepercent", "cty_retire_pct")
                    .replace("regionretirepercent", "region_retire_pct")
                    .replace("stretirepercent", "st_retire_pct")
                    for metric, bucket in wide.columns]
    wide = wide.reset_index()

    merged = pqi.merge(
        wide, on=["County", "PQIDescription"], how="left", validate="one_to_one"
    )

    # Normalize column names to snake_case.
    rename = {
        "County": "county", "PQIDescription": "pqi_description",
        "CtyPQIRate": "cty_pqi_rate", "CtyPhyRate": "cty_phy_rate",
        "StPQIRate": "st_pqi_rate", "StPhyRate": "st_phy_rate",
        "CtyMeanLengthStay": "cty_mean_los_days",
        "StMeanLengthStay": "st_mean_los_days",
        "PQIRateComp": "pqi_rate_vs_state", "PhySupplyRateComp": "phy_supply_vs_state",
        "Region": "region",
    }
    merged = merged.rename(columns=rename)
    merged["state"] = "CA"

    # Reorder: keys first, then PQI/supply, then retirement buckets.
    key_cols = ["state", "county", "region", "pqi_description"]
    pqi_cols = [c for c in ("cty_pqi_rate", "cty_phy_rate",
                            "st_pqi_rate", "st_phy_rate",
                            "cty_mean_los_days", "st_mean_los_days",
                            "pqi_rate_vs_state", "phy_supply_vs_state")
                if c in merged.columns]
    ret_cols = sorted([c for c in merged.columns
                       if c.startswith(("cty_retire_pct_", "region_retire_pct_",
                                        "st_retire_pct_"))])
    merged = merged[key_cols + pqi_cols + ret_cols]
    merged = merged.sort_values(["county", "pqi_description"]).reset_index(drop=True)

    print(f"      merged:      {merged.shape}")
    print(f"      columns:     {merged.columns.tolist()}")

    print(f"\n[4/4] writing CSV")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT, index=False)
    print(f"      wrote {OUT} ({OUT.stat().st_size/1e3:.1f} KB, "
          f"{len(merged):,} rows × {len(merged.columns)} cols)")

    # Sanity prints
    print()
    print("PQI conditions covered:")
    for c in sorted(merged["pqi_description"].unique()):
        print(f"  - {c}")
    print()
    print(f"Counties:     {merged['county'].nunique()}")
    print(f"Regions:      {merged['region'].nunique()}")

    # Top 5 counties by total physician density (averaged across conditions —
    # since CtyPhyRate is per-specialty-area-treating-that-condition; the
    # MEAN across conditions gives a comparable cross-county supply scalar).
    print()
    print("Top 5 counties by mean physician supply rate (across PQI conditions):")
    print(merged.groupby("county")["cty_phy_rate"].mean()
                .sort_values(ascending=False).head().round(1).to_string())
    print()
    print("Top 5 counties by mean PQI rate (across conditions, higher = worse outcomes):")
    print(merged.groupby("county")["cty_pqi_rate"].mean()
                .sort_values(ascending=False).head().round(1).to_string())

    # Supply-outcome correlation across counties (averaged across conditions)
    summary = merged.groupby("county").agg(
        phy=("cty_phy_rate", "mean"),
        pqi=("cty_pqi_rate", "mean"),
    )
    corr = summary["phy"].corr(summary["pqi"])
    print()
    print(f"County-level Pearson(phy supply, PQI rate) = {corr:+.3f}  "
          "(negative = lower supply -> higher preventable hospitalizations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
