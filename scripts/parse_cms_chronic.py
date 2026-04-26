"""Parse the 12 CMS Chronic Conditions state-level XLSX files into one tidy CSV.

Each XLSX has Males / Females sheets, with 3 age bands (All / <65 / 65+) and
21 chronic conditions per band. Output is long-format:
    year, state, state_fips, sex, age_band, condition, prevalence_pct
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SRC_DIR = Path("data/_cms_cc_tmp")
OUTPUT = Path("data/cms_chronic_conditions.csv")

AGE_MAP = {
    "All": "all",
    "Less than 65": "lt65",
    "65 Years and Older": "ge65",
}


def parse_age_band(label: str, sex: str) -> str | None:
    if not isinstance(label, str):
        return None
    s = label.strip().lower()
    s = re.sub(r"^\s*(?:males|females)\s*", "", s).strip()
    if s == "" or s.startswith("all"):
        return "all"
    if "less than 65" in s or "<65" in s or "<= 65" in s:
        return "lt65"
    if "65 years and over" in s or "65 years and older" in s or "65+" in s or "65 and over" in s:
        return "ge65"
    return None


CONDITION_ALIASES = {
    "schizophreniaother_psychotic_disorders": "schizophrenia_other_psychotic_disorders",
    "alzheimers_diseasedementia": "alzheimers_disease_dementia",
    "drug_abusesubstance_abuse": "drug_substance_abuse",
    "hepatitis_chronic_viral_b__c": "hepatitis_b_c",
    "hivaids": "hiv_aids",
}


def normalize_condition(label: str) -> str:
    if not isinstance(label, str):
        return ""
    s = label.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return CONDITION_ALIASES.get(s, s)


def parse_sheet(df: pd.DataFrame, sex: str) -> pd.DataFrame:
    age_row = df.iloc[3].ffill()
    cond_row = df.iloc[4]
    data = df.iloc[6:].reset_index(drop=True)

    records = []
    state_col = data.iloc[:, 0]
    fips_col = data.iloc[:, 1]
    for col_idx in range(2, df.shape[1]):
        age_band = parse_age_band(age_row.iloc[col_idx], sex)
        condition = normalize_condition(cond_row.iloc[col_idx])
        if not condition or age_band is None:
            continue
        vals = data.iloc[:, col_idx]
        for state, fips, v in zip(state_col, fips_col, vals):
            if pd.isna(state):
                continue
            try:
                num = float(str(v).strip())
            except (ValueError, TypeError):
                num = None
            records.append({
                "state": str(state).strip(),
                "state_fips": str(fips).strip() if pd.notna(fips) else "",
                "sex": sex,
                "age_band": age_band,
                "condition": condition,
                "prevalence_pct": num,
            })
    return pd.DataFrame(records)


def main() -> None:
    files = sorted(SRC_DIR.glob("State_Table_Chronic_Conditions_by_Sex_and_Age_*.xlsx"))
    pieces = []
    for f in files:
        m = re.search(r"_(\d{4})\.xlsx$", f.name)
        year = int(m.group(1))
        xl = pd.ExcelFile(f)
        for sheet, sex in [("Males", "male"), ("Females", "female")]:
            df = pd.read_excel(xl, sheet_name=sheet, header=None)
            tidy = parse_sheet(df, sex)
            tidy.insert(0, "year", year)
            pieces.append(tidy)
        print(f"{year} parsed", flush=True)
    final = pd.concat(pieces, ignore_index=True)
    final = final.sort_values(["year", "state_fips", "sex", "age_band", "condition"]).reset_index(drop=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(OUTPUT, index=False)
    print(f"\nWrote {OUTPUT}  shape={final.shape}")
    print("Columns:", list(final.columns))
    print("Years:", sorted(final["year"].unique().tolist()))
    print("Conditions:", sorted(final["condition"].unique().tolist()))
    print("Sex:", sorted(final["sex"].unique().tolist()))
    print("Age bands:", sorted(final["age_band"].unique().tolist()))
    print("Distinct states:", final["state"].nunique())


if __name__ == "__main__":
    main()
