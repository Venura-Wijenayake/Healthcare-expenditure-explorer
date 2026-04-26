"""Fetch CDC NHSN 2024 HAI Progress Report state-level SIR data and build a tidy CSV.

Source: CDC HAI Progress Report (Acute Care Hospitals), 2024 data.
URL: https://www.cdc.gov/healthcare-associated-infections/media/excel/2024-SIR-ACH.xlsx
"""
import io
import os
import sys
import urllib.request
import pandas as pd

XLSX_URL = "https://www.cdc.gov/healthcare-associated-infections/media/excel/2024-SIR-ACH.xlsx"
LOCAL_XLSX = os.path.join(os.path.dirname(__file__), "..", "tmp", "2024-SIR-ACH.xlsx")
OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "cdc_hai.csv")

# Map of source sheet -> (infection_type label, has_procedures column)
# Acute care state-level SIR sheets (header row at index 4)
SHEETS = [
    ("Table 3a-State CLABSI Data", "CLABSI", False),
    ("Table 4a-State CAUTI Data",  "CAUTI",  False),
    ("Table 6a-State SSI Data",    "SSI_COLON", True),
    ("Table 6b-State SSI Data",    "SSI_HYST",  True),
    ("Table 7-State MRSA Data",    "MRSA_BSI", False),
    ("Table 8-State CDI Data",     "CDI",      False),
]


def download():
    os.makedirs(os.path.dirname(LOCAL_XLSX), exist_ok=True)
    if not os.path.exists(LOCAL_XLSX):
        req = urllib.request.Request(XLSX_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r, open(LOCAL_XLSX, "wb") as f:
            f.write(r.read())
    print(f"local xlsx: {os.path.getsize(LOCAL_XLSX):,} bytes")


def parse_sheet(xl: pd.ExcelFile, sheet: str, infection: str, has_proc: bool) -> pd.DataFrame:
    raw = pd.read_excel(xl, sheet_name=sheet, header=None)
    # Header row is index 4; data starts row 5. Drop trailing footnote rows beyond 56 states/territories.
    if has_proc:
        # Columns: 0 State, 1 Mandate, 2 Validation, 3 NumHospitals, 4 NumProcedures,
        # 5 Observed, 6 Predicted, 7 SIR, 8 LowerCI, 9 UpperCI
        cols = {0: "state", 1: "state_nhsn_mandate", 2: "any_validation",
                3: "num_hospitals_reporting", 4: "num_procedures",
                5: "observed", 6: "predicted", 7: "sir", 8: "sir_ci_lower", 9: "sir_ci_upper"}
    else:
        cols = {0: "state", 1: "state_nhsn_mandate", 2: "any_validation",
                3: "num_hospitals_reporting",
                4: "observed", 5: "predicted", 6: "sir", 7: "sir_ci_lower", 8: "sir_ci_upper"}
    sub = raw.iloc[5:, list(cols.keys())].copy()
    sub.columns = list(cols.values())
    # Drop rows where state is NaN or footnote text
    sub = sub.dropna(subset=["state"])
    sub = sub[sub["state"].astype(str).str.match(r"^[A-Za-z][A-Za-z\.\s]+$")]
    # Trim known non-state strings (e.g. footnotes that match the regex)
    sub = sub[~sub["state"].astype(str).str.lower().str.startswith(("the table", "footnote", "note", "ssi following", "abbreviations"))]
    # Normalize state name variants seen in the workbook
    sub["state"] = sub["state"].astype(str).str.strip().replace({"D.C": "D.C.", "Washington, D.C.": "D.C."})
    sub.insert(0, "infection_type", infection)
    sub.insert(0, "year", 2024)
    if not has_proc:
        sub["num_procedures"] = pd.NA
    # Coerce numeric columns; "." indicates suppressed
    for c in ["num_hospitals_reporting", "num_procedures", "observed", "predicted",
              "sir", "sir_ci_lower", "sir_ci_upper"]:
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
    return sub.reset_index(drop=True)


def main():
    download()
    xl = pd.ExcelFile(LOCAL_XLSX)
    frames = [parse_sheet(xl, s, inf, has_proc) for s, inf, has_proc in SHEETS]
    out = pd.concat(frames, ignore_index=True)
    # Order columns
    out = out[[
        "year", "state", "infection_type",
        "num_hospitals_reporting", "num_procedures",
        "observed", "predicted",
        "sir", "sir_ci_lower", "sir_ci_upper",
        "state_nhsn_mandate", "any_validation",
    ]]
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"wrote {OUT_CSV}: {out.shape[0]} rows x {out.shape[1]} cols")
    print("\ninfection_type counts:")
    print(out["infection_type"].value_counts().to_string())
    print("\nstate count (unique):", out["state"].nunique())
    print("states:", sorted(out["state"].unique().tolist()))
    print("\nsample:")
    print(out.head(8).to_string(index=False))


if __name__ == "__main__":
    main()
