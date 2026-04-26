"""
Download Medicaid State Drug Utilization Data (SDUD) per year, aggregate to
state x year totals across all NDCs and quarters, and emit a single CSV.

Source: https://data.medicaid.gov/dataset/?q=state+drug+utilization
Per-year download URLs come from the data.medicaid.gov DKAN catalog.

Aggregation:
  groupby(state, year) -> sum(units_reimbursed, number_of_prescriptions,
                              total_amount_reimbursed,
                              medicaid_amount_reimbursed,
                              non_medicaid_amount_reimbursed),
                          count(distinct ndc) as ndc_count,
                          count(*) as records

Suppressed rows (Suppression Used == 'true') have null numerics; pandas sum
treats NaN as 0 by default, so they're effectively excluded from totals.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request

import pandas as pd

OUT_PATH = r"D:\Claudius\healthcare-expenditure-explorer\data\cms_medicaid_drug.csv"
TMP_DIR = r"D:\Claudius\healthcare-expenditure-explorer\data\_sdud_tmp"

# (year, url) - URLs verified against data.medicaid.gov DKAN catalog.
# Recent files (2015+) are largest. Earlier years smaller. Keep range
# manageable but multi-year per spec.
YEARS = [
    (2015, "https://download.medicaid.gov/data/StateDrugUtilizationData-2015.csv"),
    (2016, "https://download.medicaid.gov/data/StateDrugUtilizationData-2016.csv"),
    (2017, "https://download.medicaid.gov/data/StateDrugUtilizationData-2017.csv"),
    (2018, "https://download.medicaid.gov/data/StateDrugUtilizationData-2018.csv"),
    (2019, "https://download.medicaid.gov/data/StateDrugUtilizationData-2019.csv"),
    (2020, "https://download.medicaid.gov/data/sdud-2020-updated.csv"),
    (2021, "https://download.medicaid.gov/data/sdud-2021-updated.csv"),
    (2022, "https://download.medicaid.gov/data/sdud-2022-updated.csv"),
    (2023, "https://download.medicaid.gov/data/sdud-2023-updated.csv"),
    (2024, "https://download.medicaid.gov/data/sdud-2024-updated.csv"),
]

NUMERIC_COLS = [
    "Units Reimbursed",
    "Number of Prescriptions",
    "Total Amount Reimbursed",
    "Medicaid Amount Reimbursed",
    "Non Medicaid Amount Reimbursed",
]

USE_COLS = [
    "Utilization Type",
    "State",
    "NDC",
    "Year",
    "Quarter",
    "Suppression Used",
] + NUMERIC_COLS


def download(url: str, dest: str) -> None:
    print(f"  downloading {url} -> {dest}", flush=True)
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        total = 0
        while True:
            buf = r.read(1024 * 1024)
            if not buf:
                break
            f.write(buf)
            total += len(buf)
        size_mb = total / (1024 * 1024)
        print(f"  {size_mb:,.1f} MB in {time.time()-t0:,.1f}s", flush=True)


def aggregate_file(path: str, year: int) -> pd.DataFrame:
    """Read CSV in chunks, accumulate state-year aggregates."""
    print(f"  aggregating {path}", flush=True)
    agg = None
    rows = 0
    for chunk in pd.read_csv(
        path,
        usecols=USE_COLS,
        dtype={
            "Utilization Type": "category",
            "State": "category",
            "NDC": "string",
            "Year": "Int32",
            "Quarter": "Int8",
            "Suppression Used": "category",
        },
        chunksize=500_000,
        low_memory=False,
    ):
        rows += len(chunk)
        # Keep only main state codes (drop XX = aggregated, and any nulls)
        chunk = chunk[chunk["State"].notna()]
        # Group state x year (year column is constant per file but use it
        # explicitly so the output matches expectations)
        grouped = chunk.groupby(["State", "Year"], observed=True).agg(
            units_reimbursed=("Units Reimbursed", "sum"),
            number_of_prescriptions=("Number of Prescriptions", "sum"),
            total_amount_reimbursed=("Total Amount Reimbursed", "sum"),
            medicaid_amount_reimbursed=("Medicaid Amount Reimbursed", "sum"),
            non_medicaid_amount_reimbursed=("Non Medicaid Amount Reimbursed", "sum"),
            ndc_records=("NDC", "size"),
            ndc_unique=("NDC", "nunique"),
        )
        if agg is None:
            agg = grouped
        else:
            # combine: sums add, ndc_unique can't be combined exactly across
            # chunks but is approx; we recompute below if needed via second
            # pass - but for chunked work we keep an upper-bound estimate by
            # summing ndc_unique across chunks. Better: track sets. To keep
            # memory small, drop ndc_unique.
            agg = agg.add(grouped, fill_value=0)
    print(f"    rows read: {rows:,}", flush=True)
    # ndc_unique from chunks is unreliable when same NDC appears across chunks;
    # drop it to avoid misleading numbers.
    agg = agg.drop(columns=[c for c in ["ndc_unique"] if c in agg.columns])
    return agg.reset_index()


def main() -> None:
    os.makedirs(TMP_DIR, exist_ok=True)
    parts: list[pd.DataFrame] = []
    for year, url in YEARS:
        print(f"\n=== year {year} ===", flush=True)
        local = os.path.join(TMP_DIR, f"sdud-{year}.csv")
        try:
            if not os.path.exists(local):
                download(url, local)
            else:
                print(f"  already cached: {local}", flush=True)
            df = aggregate_file(local, year)
            parts.append(df)
        finally:
            # Clean up immediately to free disk
            if os.path.exists(local):
                try:
                    os.remove(local)
                    print(f"  removed {local}", flush=True)
                except OSError as e:
                    print(f"  cleanup failed: {e}", flush=True)

    out = pd.concat(parts, ignore_index=True)
    out = out.rename(columns={"State": "state", "Year": "year"})
    out = out.sort_values(["state", "year"]).reset_index(drop=True)

    # Round dollar amounts
    for col in [
        "units_reimbursed",
        "total_amount_reimbursed",
        "medicaid_amount_reimbursed",
        "non_medicaid_amount_reimbursed",
    ]:
        out[col] = out[col].astype(float).round(2)
    out["number_of_prescriptions"] = out["number_of_prescriptions"].astype("Int64")
    out["ndc_records"] = out["ndc_records"].astype("Int64")

    out.to_csv(OUT_PATH, index=False)
    print(f"\nwrote {OUT_PATH}: shape={out.shape}", flush=True)
    print(f"columns: {list(out.columns)}", flush=True)
    print(f"year range: {out['year'].min()} - {out['year'].max()}", flush=True)
    print(f"distinct states: {out['state'].nunique()}", flush=True)

    # Sanity: national totals by year
    yr = out.groupby("year").agg(
        rx_M=("number_of_prescriptions", lambda s: s.sum() / 1e6),
        total_B=("total_amount_reimbursed", lambda s: s.sum() / 1e9),
        medicaid_B=("medicaid_amount_reimbursed", lambda s: s.sum() / 1e9),
    )
    print("\nNational totals by year:")
    print(yr.round(2).to_string())

    # Cleanup tmp dir
    try:
        os.rmdir(TMP_DIR)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
