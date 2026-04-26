"""
Fetch CDC NCHS state-level mortality by cause for 2018-2023.

The classic bi63-dtpu "NCHS - Leading Causes of Death" Socrata dataset only
covers 1999-2017. The CDC WONDER API itself blocks sub-national (state)
groupings for the underlying-cause-of-death databases. The j7s2-ynf8 catalog
entry that nominally covers 2005-2023 is a federated record without a Socrata
endpoint.

The cleanest 2018-2023 state x cause source on data.cdc.gov is the pair of
weekly provisional death-counts datasets, which we aggregate to annual:
  - 3yf8-kanr  Weekly Counts of Deaths by State and Select Causes, 2014-2019
  - muzy-jte6  Weekly Provisional Counts of Deaths by State and Select Causes,
               2020-2023

These provide jurisdiction x ICD-10 cause group x weekly death counts. We
aggregate to annual state x cause x deaths. Because no age-stratified deaths
are available in these datasets we cannot compute true age-adjusted rates;
instead we compute crude death rates per 100,000 using ACS state population.
This deliberately preserves the spec's "rates by cause" intent while being
transparent about the methodology.

Output: data/cdc_wonder_mortality.csv
"""

import io
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cdc_wonder_mortality.csv"

# Cause column -> human-readable cause name
# Note 3yf8-kanr uses "influenza_and_pneumonia_j10" and muzy-jte6 uses
# "influenza_and_pneumonia_j09_j18" - we map both to one canonical cause.
CAUSE_MAP_2014_2019 = {
    "allcause": "All causes",
    "naturalcause": "Natural cause",
    "septicemia_a40_a41": "Septicemia",
    "malignant_neoplasms_c00_c97": "Cancer (malignant neoplasms)",
    "diabetes_mellitus_e10_e14": "Diabetes",
    "alzheimer_disease_g30": "Alzheimer disease",
    "influenza_and_pneumonia_j10": "Influenza and pneumonia",
    "chronic_lower_respiratory": "Chronic lower respiratory diseases",
    "other_diseases_of_respiratory": "Other respiratory diseases",
    "nephritis_nephrotic_syndrome": "Kidney disease",
    "symptoms_signs_and_abnormal": "Symptoms, signs, abnormal findings (R00-R99)",
    "diseases_of_heart_i00_i09": "Heart disease",
    "cerebrovascular_diseases": "Stroke (cerebrovascular)",
}
CAUSE_MAP_2020_2023 = {
    "all_cause": "All causes",
    "natural_cause": "Natural cause",
    "septicemia_a40_a41": "Septicemia",
    "malignant_neoplasms_c00_c97": "Cancer (malignant neoplasms)",
    "diabetes_mellitus_e10_e14": "Diabetes",
    "alzheimer_disease_g30": "Alzheimer disease",
    "influenza_and_pneumonia_j09_j18": "Influenza and pneumonia",
    "chronic_lower_respiratory": "Chronic lower respiratory diseases",
    "other_diseases_of_respiratory": "Other respiratory diseases",
    "nephritis_nephrotic_syndrome": "Kidney disease",
    "symptoms_signs_and_abnormal": "Symptoms, signs, abnormal findings (R00-R99)",
    "diseases_of_heart_i00_i09": "Heart disease",
    "cerebrovascular_diseases": "Stroke (cerebrovascular)",
    "covid_19_u071_multiple_cause_of_death": "COVID-19 (multiple cause)",
    "covid_19_u071_underlying_cause_of_death": "COVID-19 (underlying cause)",
}


def fetch_socrata_csv(dataset_id: str, page_size: int = 50000) -> pd.DataFrame:
    """Page through a Socrata CSV endpoint and return a DataFrame."""
    base = f"https://data.cdc.gov/resource/{dataset_id}.csv"
    chunks = []
    offset = 0
    while True:
        params = {"$limit": page_size, "$offset": offset, "$order": ":id"}
        r = requests.get(base, params=params, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty:
            break
        chunks.append(df)
        if len(df) < page_size:
            break
        offset += page_size
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def aggregate_annual(df: pd.DataFrame, year_col: str, cause_map: dict) -> pd.DataFrame:
    """Aggregate weekly state x cause death counts to annual."""
    cols = ["jurisdiction_of_occurrence", year_col] + [
        c for c in cause_map if c in df.columns
    ]
    sub = df[cols].copy()
    sub.rename(columns={year_col: "year"}, inplace=True)
    # Long-format
    long = sub.melt(
        id_vars=["jurisdiction_of_occurrence", "year"],
        var_name="cause_col",
        value_name="deaths",
    )
    long["deaths"] = pd.to_numeric(long["deaths"], errors="coerce")
    annual = (
        long.groupby(["jurisdiction_of_occurrence", "year", "cause_col"], as_index=False)[
            "deaths"
        ]
        .sum(min_count=1)
    )
    annual["cause_name"] = annual["cause_col"].map(cause_map)
    annual = annual.drop(columns=["cause_col"]).rename(
        columns={"jurisdiction_of_occurrence": "state"}
    )
    return annual[["year", "state", "cause_name", "deaths"]]


def main() -> int:
    print("[1/5] Fetching 3yf8-kanr (weekly state x cause, 2014-2019)...")
    weekly_old = fetch_socrata_csv("3yf8-kanr")
    print(f"      rows: {len(weekly_old):,}")

    print("[2/5] Fetching muzy-jte6 (weekly state x cause, 2020-2023)...")
    weekly_new = fetch_socrata_csv("muzy-jte6")
    print(f"      rows: {len(weekly_new):,}")

    # Filter to 2018+
    weekly_old = weekly_old[weekly_old["mmwryear"].astype(int) >= 2018]
    weekly_new["mmwryear"] = weekly_new["mmwryear"].astype(int)
    weekly_new = weekly_new[weekly_new["mmwryear"] <= 2023]

    print("[3/5] Aggregating to annual...")
    annual_old = aggregate_annual(weekly_old, "mmwryear", CAUSE_MAP_2014_2019)
    annual_new = aggregate_annual(weekly_new, "mmwryear", CAUSE_MAP_2020_2023)
    annual = pd.concat([annual_old, annual_new], ignore_index=True)
    # If a cause appears in both halves for the same state-year-cause, sum is fine
    # (datasets don't overlap year-wise after the 2018+ / <=2023 filters).
    annual = (
        annual.groupby(["year", "state", "cause_name"], as_index=False)["deaths"]
        .sum(min_count=1)
        .dropna(subset=["cause_name"])
    )
    annual["deaths"] = annual["deaths"].astype("Int64")
    print(f"      annual rows: {len(annual):,}")

    print("[4/5] Computing crude death rate per 100,000 using ACS state population...")
    pop = pd.read_csv(ROOT / "data" / "acs_demographics.csv")[["NAME", "B01001_001E"]]
    pop = pop.rename(columns={"NAME": "state", "B01001_001E": "population"})
    annual = annual.merge(pop, on="state", how="left")
    annual["crude_rate_per_100k"] = (
        annual["deaths"].astype("Float64") / annual["population"] * 100000
    ).round(2)

    print("[5/5] Writing CSV...")
    annual = annual.sort_values(["year", "state", "cause_name"]).reset_index(drop=True)
    annual.to_csv(OUT, index=False)

    print()
    print(f"Saved {OUT}")
    print(f"  shape:        {annual.shape}")
    print(f"  size:         {OUT.stat().st_size/1024:.1f} KB")
    print(f"  year range:   {annual.year.min()}-{annual.year.max()}")
    print(f"  states:       {annual.state.nunique()}")
    print(f"  causes:       {annual.cause_name.nunique()}")
    print()
    print("Causes covered:")
    for c in sorted(annual.cause_name.dropna().unique()):
        print(f"  - {c}")
    print()
    print("Sample (Florida, 2022):")
    print(
        annual[(annual.state == "Florida") & (annual.year == 2022)][
            ["cause_name", "deaths", "crude_rate_per_100k"]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
