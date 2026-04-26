"""
State Risk Index — composite of 7 dimensions across 50 states + DC.

Higher score = WORSE outcome. Each dimension is percentile-ranked 0-100 with
consistent semantics (higher percentile = higher risk), then averaged with
equal weights to produce a composite risk_score.

Dimensions:
  1. SPENDING EFFICIENCY    — Medicare std payment per beneficiary (geo_variation, 2023)
  2. PROVIDER SUPPLY        — physicians per 100k population (AHRF, 2023) [inverted]
  3. SHORTAGE SEVERITY      — HPSA score weighted by FTE needed (HPSA primary care)
  4. DISEASE BURDEN         — mean of diabetes + obesity + CHD prevalence (BRFSS, 2024)
  5. INSURANCE COVERAGE     — % uninsured all-income (SAHIE, most recent)
  6. HOSPITAL QUALITY       — mean hospital overall star rating [inverted]
  7. POVERTY                — poverty rate all ages (SAIPE state, most recent)

Output: data/state_risk_index.csv
"""
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path("data")
OUT = DATA / "state_risk_index.csv"

# 50 states + DC. (abbrev, fips, full_name)
STATES_50_DC = [
    ("AL", 1, "Alabama"), ("AK", 2, "Alaska"), ("AZ", 4, "Arizona"), ("AR", 5, "Arkansas"),
    ("CA", 6, "California"), ("CO", 8, "Colorado"), ("CT", 9, "Connecticut"), ("DE", 10, "Delaware"),
    ("DC", 11, "District of Columbia"), ("FL", 12, "Florida"), ("GA", 13, "Georgia"),
    ("HI", 15, "Hawaii"), ("ID", 16, "Idaho"), ("IL", 17, "Illinois"), ("IN", 18, "Indiana"),
    ("IA", 19, "Iowa"), ("KS", 20, "Kansas"), ("KY", 21, "Kentucky"), ("LA", 22, "Louisiana"),
    ("ME", 23, "Maine"), ("MD", 24, "Maryland"), ("MA", 25, "Massachusetts"), ("MI", 26, "Michigan"),
    ("MN", 27, "Minnesota"), ("MS", 28, "Mississippi"), ("MO", 29, "Missouri"), ("MT", 30, "Montana"),
    ("NE", 31, "Nebraska"), ("NV", 32, "Nevada"), ("NH", 33, "New Hampshire"),
    ("NJ", 34, "New Jersey"), ("NM", 35, "New Mexico"), ("NY", 36, "New York"),
    ("NC", 37, "North Carolina"), ("ND", 38, "North Dakota"), ("OH", 39, "Ohio"),
    ("OK", 40, "Oklahoma"), ("OR", 41, "Oregon"), ("PA", 42, "Pennsylvania"),
    ("RI", 44, "Rhode Island"), ("SC", 45, "South Carolina"), ("SD", 46, "South Dakota"),
    ("TN", 47, "Tennessee"), ("TX", 48, "Texas"), ("UT", 49, "Utah"), ("VT", 50, "Vermont"),
    ("VA", 51, "Virginia"), ("WA", 53, "Washington"), ("WV", 54, "West Virginia"),
    ("WI", 55, "Wisconsin"), ("WY", 56, "Wyoming"),
]
STATE_ABBRS = [s[0] for s in STATES_50_DC]
ABBR_TO_NAME = {a: n for a, _, n in STATES_50_DC}
FIPS_TO_ABBR = {f: a for a, f, _ in STATES_50_DC}


def dim_spending() -> pd.Series:
    """Medicare standardized payment per FFS beneficiary, 2023, state-level all-age."""
    df = pd.read_csv(
        DATA / "geo_variation_2014_2023.csv",
        usecols=["YEAR", "BENE_GEO_LVL", "BENE_GEO_DESC", "BENE_AGE_LVL", "TOT_MDCR_STDZD_PYMT_PC"],
        low_memory=False,
    )
    df = df[(df["YEAR"] == 2023) & (df["BENE_GEO_LVL"] == "State") & (df["BENE_AGE_LVL"] == "All")]
    df = df[df["BENE_GEO_DESC"].isin(STATE_ABBRS)]
    df["TOT_MDCR_STDZD_PYMT_PC"] = pd.to_numeric(df["TOT_MDCR_STDZD_PYMT_PC"], errors="coerce")
    return df.set_index("BENE_GEO_DESC")["TOT_MDCR_STDZD_PYMT_PC"].rename("spending_raw")


def dim_supply() -> pd.Series:
    """Physicians per 100k population from AHRF (2023 fields)."""
    df = pd.read_csv(
        DATA / "ahrf_state_national_2025.csv",
        usecols=["st_abbrev", "phys_wkforc_23", "popn_pums_23"],
        low_memory=False,
    )
    df = df[df["st_abbrev"].isin(STATE_ABBRS)]
    df["phys_wkforc_23"] = pd.to_numeric(df["phys_wkforc_23"], errors="coerce")
    df["popn_pums_23"] = pd.to_numeric(df["popn_pums_23"], errors="coerce")
    df["rate"] = df["phys_wkforc_23"] / df["popn_pums_23"] * 100_000
    return df.set_index("st_abbrev")["rate"].rename("supply_raw")


def dim_shortage() -> pd.Series:
    """HPSA score weighted by FTE practitioners needed; designated primary-care HPSAs only."""
    df = pd.read_csv(
        DATA / "hpsa_primary_care.csv",
        usecols=["HPSA Status", "HPSA Score", "HPSA FTE", "State Abbreviation"],
        low_memory=False,
    )
    df = df[df["HPSA Status"] == "Designated"]
    df = df[df["State Abbreviation"].isin(STATE_ABBRS)]
    df["HPSA Score"] = pd.to_numeric(df["HPSA Score"], errors="coerce")
    df["HPSA FTE"] = pd.to_numeric(df["HPSA FTE"], errors="coerce")
    df = df.dropna(subset=["HPSA Score", "HPSA FTE"])
    df = df[df["HPSA FTE"] > 0]

    def weighted_mean(g):
        return np.average(g["HPSA Score"], weights=g["HPSA FTE"])

    return df.groupby("State Abbreviation").apply(weighted_mean).rename("shortage_raw")


def dim_disease() -> pd.Series:
    """Mean of diabetes + obesity + coronary heart disease prevalence (BRFSS).

    Uses the most recent year that has data per state per measure, so that
    states which skipped a survey year (e.g. TN in 2024) still get a value
    from their last participating year.
    """
    df = pd.read_csv(
        DATA / "brfss_state_prevalence.csv",
        usecols=["year", "locationabbr", "topic", "question", "response", "data_value", "data_value_type"],
        low_memory=False,
    )
    df = df[df["data_value_type"] == "Crude Prevalence"]
    df = df[df["locationabbr"].isin(STATE_ABBRS)]
    df["data_value"] = pd.to_numeric(df["data_value"], errors="coerce")
    df = df.dropna(subset=["data_value"])

    def latest_per_state(subset: pd.DataFrame) -> pd.Series:
        idx = subset.groupby("locationabbr")["year"].idxmax()
        return subset.loc[idx].set_index("locationabbr")["data_value"]

    diabetes = latest_per_state(df[df["topic"] == "Diabetes"])
    obesity = latest_per_state(
        df[(df["topic"] == "BMI Categories") & df["response"].str.startswith("Obese", na=False)]
    )
    chd = latest_per_state(
        df[df["question"].str.contains("coronary heart disease", case=False, na=False) &
           df["question"].str.contains("calculated", case=False, na=False)]
    )

    composite = pd.concat({"diabetes": diabetes, "obesity": obesity, "chd": chd}, axis=1).mean(axis=1)
    return composite.rename("disease_raw")


def dim_insurance() -> pd.Series:
    """% uninsured all-income (IPRCAT=0) for the most recent year."""
    df = pd.read_csv(DATA / "census_sahie.csv")
    df = df[(df["IPRCAT"] == 0) & (df["AGECAT"] == 0) & (df["SEXCAT"] == 0) & (df["RACECAT"] == 0)]
    most_recent = df["time"].max()
    df = df[df["time"] == most_recent]
    df["state_abbr"] = df["state"].map(FIPS_TO_ABBR)
    df = df.dropna(subset=["state_abbr"])
    return df.set_index("state_abbr")["PCTUI_PT"].rename("insurance_raw")


def dim_hospital_quality() -> pd.Series:
    """Mean Hospital Overall Star Rating per state (1-5, excluding 'Not Available')."""
    df = pd.read_csv(
        DATA / "hospital_compare_general_info.csv",
        usecols=["State", "Hospital overall rating"],
        low_memory=False,
    )
    df = df[df["State"].isin(STATE_ABBRS)]
    df["rating"] = pd.to_numeric(df["Hospital overall rating"], errors="coerce")
    df = df.dropna(subset=["rating"])
    return df.groupby("State")["rating"].mean().rename("hospital_quality_raw")


def dim_poverty() -> pd.Series:
    """Poverty rate (all ages) at state level, most recent year."""
    df = pd.read_csv(
        DATA / "census_saipe.csv",
        usecols=["YEAR", "SAEPOVRTALL_PT", "state", "geo_lvl"],
    )
    df = df[df["geo_lvl"] == "state"]
    most_recent = df["YEAR"].max()
    df = df[df["YEAR"] == most_recent]
    df["state_abbr"] = df["state"].map(FIPS_TO_ABBR)
    df = df.dropna(subset=["state_abbr"])
    return df.set_index("state_abbr")["SAEPOVRTALL_PT"].rename("poverty_raw")


def to_risk_percentile(series: pd.Series, higher_is_riskier: bool) -> pd.Series:
    """Percentile-rank to 0-100 where higher = more risky."""
    return series.rank(pct=True, ascending=higher_is_riskier) * 100


def main():
    raw = pd.DataFrame(index=STATE_ABBRS)
    raw.index.name = "state_abbr"

    raw["spending_raw"] = dim_spending()
    raw["supply_raw"] = dim_supply()
    raw["shortage_raw"] = dim_shortage()
    raw["disease_raw"] = dim_disease()
    raw["insurance_raw"] = dim_insurance()
    raw["hospital_quality_raw"] = dim_hospital_quality()
    raw["poverty_raw"] = dim_poverty()

    # Direction: True = higher raw value means higher risk
    direction = {
        "spending_raw": True,           # high Medicare spend = inefficient = higher risk
        "supply_raw": False,            # more docs = lower risk
        "shortage_raw": True,           # high HPSA score = severe shortage
        "disease_raw": True,            # high prevalence = higher burden
        "insurance_raw": True,          # high uninsured = higher risk
        "hospital_quality_raw": False,  # high stars = lower risk
        "poverty_raw": True,            # high poverty = higher risk
    }

    out = pd.DataFrame(index=STATE_ABBRS)
    out.index.name = "state_abbr"
    for raw_col, higher_riskier in direction.items():
        dim_col = "dim_" + raw_col.replace("_raw", "")
        out[dim_col] = to_risk_percentile(raw[raw_col], higher_is_riskier=higher_riskier)

    dim_cols = [c for c in out.columns if c.startswith("dim_")]
    out["risk_score"] = out[dim_cols].mean(axis=1)
    out["risk_rank"] = out["risk_score"].rank(ascending=False, method="min").astype(int)

    n = len(out)
    third = n // 3
    out["risk_tier"] = "Medium"
    out.loc[out["risk_rank"] <= third, "risk_tier"] = "High"
    out.loc[out["risk_rank"] > n - third, "risk_tier"] = "Low"

    out = out.reset_index()
    out.insert(0, "state", out["state_abbr"].map(ABBR_TO_NAME))

    column_order = [
        "state", "state_abbr",
        "dim_spending", "dim_supply", "dim_shortage", "dim_disease",
        "dim_insurance", "dim_hospital_quality", "dim_poverty",
        "risk_score", "risk_rank", "risk_tier",
    ]
    out = out[column_order].sort_values("risk_rank").reset_index(drop=True)

    OUT.parent.mkdir(exist_ok=True)
    out.to_csv(OUT, index=False, float_format="%.2f")
    print(f"Wrote {OUT} -- {len(out)} states\n")

    print("=" * 70)
    print("TOP 10 HIGHEST RISK STATES")
    print("=" * 70)
    print(out.head(10).to_string(index=False))
    print()
    print("=" * 70)
    print("BOTTOM 10 LOWEST RISK STATES")
    print("=" * 70)
    print(out.tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
