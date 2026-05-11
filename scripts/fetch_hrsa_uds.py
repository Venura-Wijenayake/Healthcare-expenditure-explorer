"""Build expanded HRSA UDS Health Center Profile from the raw H80 workbook.

HRSA's Uniform Data System (UDS) is the annual report every federally-
funded health center (FQHC, "Section 330" grantee) files with the
Bureau of Primary Health Care. The H80 ("Health Center Program") full
workbook is the canonical artifact — 37 sheets covering identity,
demographics, insurance/income, special populations, staffing, visits,
clinical quality measures, and financials.

This script reads the workbook (already on disk as
`data/hrsa_uds_h80_2024.xlsx` — HRSA's www.hrsa.gov host returns 403
to programmatic clients, so it was downloaded manually one-time;
re-download via browser for refreshes) and produces a single
awardee-level CSV (`data/hrsa_uds.csv`) that left-joins the most
useful sheets on the BHCMISID grantee key.

Previous state: `data/hrsa_uds.csv` was a thin 17-col extract holding
only Table 3A totals + Table 4/5 highlights. This script REPLACES it
with a much richer (~200-col) version that adds the full Workforce
sheet, Table 4 (income/insurance/special-population designations),
and the Table 6B / Table 7 clinical-measures sheets.

UDS column-name convention:
    Coded columns like `T4_L9_Ca`, `Twfc_L2.1_Ca` use the UDS Reporting
    Manual's table-and-line numbering. We keep them in raw form rather
    than rename per-line: HRSA renumbers lines across reporting years
    and any rename would silently rot. See the UDS instructions PDF
    for the line dictionary:
    https://bphc.hrsa.gov/data-reporting/uds-training-and-technical-assistance/uds-reporting-resources

License: open public data, attribute HRSA.
Refresh: annual (UDS publishes ~9 months after each calendar year).
Output: data/hrsa_uds.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "hrsa_uds_h80_2024.xlsx"
OUT = ROOT / "data" / "hrsa_uds.csv"

# Sheets to fold into the awardee-level frame, paired with the column
# prefix to prepend (None = keep column names verbatim). The Workforce
# sheet's columns already carry a `Twfc_` prefix; we leave it alone.
# Table 4 columns use `T4_` prefix natively. Clinical measure sheets
# use readable English so we keep them as-is.
JOIN_SHEETS: list[tuple[str, str | None]] = [
    ("HealthCenterInfo",       None),
    ("Table4",                 None),  # T4_L*_Ca/Cb already self-prefixed
    ("Workforce",              None),  # Twfc_L*_Ca already self-prefixed
    ("Table6BClinicalmeasures", None),
    # Table 7 (clinical measures stratified by race × ethnicity, 27
    # rows per FQHC) is intentionally NOT joined here — the per-FQHC
    # aggregate isn't a simple sum across strata and the right
    # aggregation depends on the analytical question. Surface the
    # original sheet separately if/when needed.
]

# Top-level convenience columns re-derived from coded source columns
# so downstream consumers don't have to remember the UDS line lookup
# for the headline numbers. Line numbers are from the 2024 UDS reporting
# manual; verify against the manual if HRSA revises the form.
DERIVED_TOTALS = [
    # Table 3A line 39 = age "Total" row; Ca = Male, Cb = Female.
    # Holyoke ground-truth: L39_Ca=9375, L39_Cb=10760, sum=20135.
    ("TotalMalePatients",   "Table3A", "T3a_L39_Ca"),
    ("TotalFemalePatients", "Table3A", "T3a_L39_Cb"),
]


def read_sheet(name: str) -> pd.DataFrame:
    """Read one sheet from the workbook. UDS workbook is on disk."""
    return pd.read_excel(WORKBOOK, sheet_name=name)


def main() -> int:
    if not WORKBOOK.exists():
        print(f"ERROR: {WORKBOOK} not found. The HRSA H80 workbook is "
              "downloaded manually because www.hrsa.gov returns 403 to "
              "programmatic clients. Visit "
              "https://www.hrsa.gov/sites/default/files/hrsa/foia/h80-2024.xlsx "
              "in a browser and save to data/.", file=sys.stderr)
        return 2

    print(f"[1/4] reading workbook  {WORKBOOK.name}")

    # Anchor on HealthCenterInfo — one row per FQHC grantee.
    # IMPORTANT: 294 of the 1,359 HealthCenterInfo rows have BHCMISID
    # encoded as infinity (it's stored as a number in Excel and the
    # cell formula collapsed for newer grantees that hadn't yet been
    # assigned a BHCMIS ID at report time). GrantNumber is filled in
    # for every row and is unique 1:1, so we use it as the canonical
    # join key. BHCMISID stays in the output for joinability with the
    # subset of rows where it's valid.
    anchor = read_sheet("HealthCenterInfo")
    print(f"      HealthCenterInfo: {anchor.shape}")
    anchor = anchor.dropna(subset=["GrantNumber"]).copy()
    anchor["GrantNumber"] = anchor["GrantNumber"].astype(str).str.strip()
    # Tag the inf-BHCMISID rows so they're recoverable post-hoc.
    # Keep BHCMISID as a float-with-NaN: ~22% of rows have inf which
    # we replace with NaN, and Excel sometimes stores small fractions
    # that prevent safe Int64 cast. Float is sufficient for the
    # downstream views that need it (joins use GrantNumber).
    anchor["BHCMISID"] = pd.to_numeric(anchor["BHCMISID"], errors="coerce")
    anchor.loc[~anchor["BHCMISID"].apply(
        lambda x: x is not None and x == x and x != float("inf") and x != float("-inf")
    ), "BHCMISID"] = pd.NA

    # Add a synthetic ReportingYear if not present.
    if "ReportingYear" not in anchor.columns:
        anchor["ReportingYear"] = 2024

    print(f"[2/4] joining sheets to awardee key (GrantNumber)")
    merged = anchor.copy()
    for sheet_name, prefix in JOIN_SHEETS:
        if sheet_name == "HealthCenterInfo":
            continue  # already the anchor
        df = read_sheet(sheet_name)
        df = df.dropna(subset=["GrantNumber"]).copy()
        df["GrantNumber"] = df["GrantNumber"].astype(str).str.strip()
        df = df[df["GrantNumber"].ne("---")]
        # BHCMISID is in every sheet too — drop it on the right side
        # of the merge since it's already in `anchor` and may be inf.
        if "BHCMISID" in df.columns:
            df = df.drop(columns=["BHCMISID"])
        before = len(merged)
        merged = merged.merge(df, on="GrantNumber", how="left", validate="one_to_one")
        print(f"      + {sheet_name:30}  {df.shape}  -> merged: {merged.shape}")
        assert len(merged) == before, f"merge inflated rows on {sheet_name}"

    print(f"[3/4] deriving convenience totals from Table3A / Table5")
    for out_col, sheet, src_col in DERIVED_TOTALS:
        if out_col in merged.columns:
            # Already pulled by the JOIN_SHEETS step (Table 4 fields).
            continue
        try:
            sub = read_sheet(sheet)[["GrantNumber", src_col]].copy()
        except KeyError:
            print(f"      {out_col:35}  SOURCE MISSING ({sheet}.{src_col}) — skipped")
            continue
        sub = sub.dropna(subset=["GrantNumber"])
        sub["GrantNumber"] = sub["GrantNumber"].astype(str).str.strip()
        # UDS sheets occasionally include rows with GrantNumber set to
        # a literal "---" suppression marker; drop those so the merge
        # stays one-to-one.
        sub = sub[sub["GrantNumber"].ne("---")]
        sub[out_col] = pd.to_numeric(sub[src_col], errors="coerce")
        merged = merged.merge(sub[["GrantNumber", out_col]], on="GrantNumber",
                              how="left", validate="one_to_one")
        n_valid = merged[out_col].notna().sum()
        print(f"      {out_col:35}  rows with data: {n_valid:,}/{len(merged):,}")

    # Compute total patients = male + female if not already present.
    if "TotalPatients" not in merged.columns:
        merged["TotalPatients"] = (
            pd.to_numeric(merged.get("TotalMalePatients"), errors="coerce")
            + pd.to_numeric(merged.get("TotalFemalePatients"), errors="coerce")
        ).astype("Int64")

    # Keep `state` as an alias for HealthCenterState so existing
    # _FILTER_COLUMNS["state"] resolves cleanly.
    if "state" not in merged.columns and "HealthCenterState" in merged.columns:
        merged["state"] = merged["HealthCenterState"]

    # Sort columns: identity first, then merged sheet columns, then derived totals.
    identity_cols = [c for c in (
        "BHCMISID", "GrantNumber", "ReportingYear", "HealthCenterName",
        "HealthCenterStreetAddress", "HealthCenterCity", "state",
        "HealthCenterState", "HealthCenterZIPCode", "UrbanRuralFlag",
        "FundingCHC", "FundingMHC", "FundingHO", "FundingPH",
        "ProjectDirector", "ProjectDirectorPhone", "ProjectDirectorPhoneExt",
        "ProjectDirectorFax", "ProjectDirectorEmail",
        "HealthCenterOtherAddress",
    ) if c in merged.columns]
    derived_cols = [c for c, _, _ in DERIVED_TOTALS if c in merged.columns]
    derived_cols.append("TotalPatients")
    other_cols = [c for c in merged.columns
                  if c not in identity_cols and c not in derived_cols]
    merged = merged[identity_cols + derived_cols + other_cols]
    merged = merged.sort_values("BHCMISID").reset_index(drop=True)

    print(f"\n[4/4] writing CSV")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT, index=False)
    print(f"      wrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB, "
          f"{len(merged):,} rows × {len(merged.columns)} cols)")

    # Sanity output
    print()
    print(f"  FQHCs total:        {len(merged):,}")
    print(f"  Distinct states:    {merged['state'].nunique()}")
    print(f"  Top 10 states by FQHC count:")
    print(merged["state"].value_counts().head(10).to_string())
    print()
    if "TotalPatients" in merged.columns:
        tot = pd.to_numeric(merged["TotalPatients"], errors="coerce").sum()
        print(f"  National total patients (sum of TotalPatients): {tot:,.0f}")
    print()
    print("  CA FQHC count:", (merged["state"] == "CA").sum())
    return 0


if __name__ == "__main__":
    sys.exit(main())
