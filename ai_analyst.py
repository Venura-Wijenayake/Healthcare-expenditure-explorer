"""
AI Analyst — RAG-based dataset routing across a hot-swappable provider chain.

Pipeline:
  1. retrieve_context(question) inspects the question against DATASET_REGISTRY
     keyword patterns and selects relevant dataset summaries (always plus
     state_risk_index + geo_variation as base context).
  2. query_analyst(question) walks the provider chain Groq → OpenAI → Gemini
     → Together AI, sized per-provider for rate-limit compliance.

Each provider is tried in order; on any failure (rate limit, network, auth)
the chain silently falls back to the next configured provider.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

import streamlit as st
import pandas as pd

DATA = Path("data")

SYSTEM_PROMPT = (
    "You are an expert healthcare policy analyst and data scientist with access to "
    "73 federal datasets covering Medicare spending, workforce supply, disease burden, "
    "hospital quality, social determinants, vaccination, and more across all 50 US states. "
    "Your job is to answer questions by reasoning across these datasets, identifying "
    "patterns, correlations, and actionable insights. Always cite which datasets you are "
    "drawing from. Be specific, data-driven, and concise. When you don't have enough data "
    "to answer definitively, say so."
)

PROVIDERS = ["groq", "openai", "gemini", "together"]
PROVIDER_LABELS = {
    "groq": "Groq",
    "openai": "GPT-4o mini",
    "gemini": "Gemini",
    "together": "Together AI",
}

GROQ_MODEL = "llama-3.3-70b-versatile"
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-2.0-flash"
TOGETHER_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

KEY_NAMES = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "together": "TOGETHER_API_KEY",
}


# =============================================================================
# Provider handlers
# =============================================================================
def _has_key(provider: str) -> bool:
    try:
        return bool(str(st.secrets.get(KEY_NAMES[provider], "")).strip())
    except Exception:
        return False


def get_active_provider() -> str | None:
    for p in PROVIDERS:
        if _has_key(p):
            return p
    return None


def _user_msg(question: str, context: str) -> str:
    return f"DATA CONTEXT:\n{context}\n\nQUESTION: {question}"


def _call_groq(question: str, context: str) -> str:
    from groq import Groq
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_msg(question, context)},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    return resp.choices[0].message.content or ""


def _call_openai(question: str, context: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_msg(question, context)},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    return resp.choices[0].message.content or ""


def _call_gemini(question: str, context: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=SYSTEM_PROMPT)
    resp = model.generate_content(
        _user_msg(question, context),
        generation_config={"temperature": 0.3, "max_output_tokens": 1500},
    )
    return resp.text or ""


def _call_together(question: str, context: str) -> str:
    from together import Together
    client = Together(api_key=st.secrets["TOGETHER_API_KEY"])
    resp = client.chat.completions.create(
        model=TOGETHER_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_msg(question, context)},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    return resp.choices[0].message.content or ""


_HANDLERS = {
    "groq": _call_groq,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "together": _call_together,
}


# =============================================================================
# Provider-specific context sizing
# =============================================================================
GROQ_CONTEXT_CHAR_LIMIT = 4000
GROQ_TRIM_NOTE = (
    "Note: abbreviated context for rate-limit compliance. "
    "Full context available via Gemini/Together AI."
)


def trim_context_for_provider(context: str, provider: str) -> str:
    """Targeted context should usually fit Groq's TPM cap; trim only if it exceeds 4K chars."""
    if provider == "groq" and len(context) > GROQ_CONTEXT_CHAR_LIMIT:
        return f"{GROQ_TRIM_NOTE}\n\n{context[:GROQ_CONTEXT_CHAR_LIMIT]}"
    return context


# =============================================================================
# Dataset registry (RAG routing)
# =============================================================================
DATASET_REGISTRY: dict[str, list[str]] = {
    "opioid|overdose|fentanyl|heroin|drug": ["cdc_drug_overdose", "samhsa_facilities", "samhsa_nsduh"],
    "hiv|aids": ["cdc_hiv", "hrsa_ryan_white", "census_sahie"],
    "cancer|tumor|oncology|malignant": ["nci_cancer", "cdc_mortality", "cdc_wonder_mortality"],
    "wastewater|nwss|sewage": ["cdc_wastewater"],
    "influenza|flu|rsv|respiratory": ["cdc_wastewater", "cdc_vaccination"],
    "covid|coronavirus|sars": ["cdc_wastewater", "cdc_vaccination"],
    "vaccine|vaccination|immunization": ["cdc_vaccination"],
    "workforce|physician|doctor|nurse|dentist|shortage": ["ahrf_state_national_2025", "hpsa_primary_care", "hrsa_workforce_projections", "gme_residency"],
    "insurance|uninsured|coverage": ["census_sahie", "ahrq_meps", "acs_demographics"],
    "medicaid": ["cms_medicaid_drug", "census_sahie"],
    "medicare|spending|expenditure": ["geo_variation_2014_2023", "cms_inpatient_geo", "cms_physician_payments"],
    "mental health|depression|anxiety|psychiatric": ["nimh_mental_health", "samhsa_nsduh", "samhsa_facilities", "hpsa_mental_health"],
    "maternal|pregnancy|birth|infant|neonatal": ["cdc_births", "cdc_maternal_mortality", "hrsa_mch"],
    "poverty|income|socioeconomic": ["census_saipe", "census_sahie", "acs_demographics"],
    "food|nutrition|hunger|wic": ["usda_food_access", "usda_wic"],
    "broadband|telehealth|telemedicine|rural": ["fcc_broadband", "hrsa_telehealth", "dot_transportation"],
    "hospital|facility|quality|readmission": ["hospital_compare_general_info", "hospital_compare_readmissions_state", "hospital_compare_complications_state"],
    "nursing home|long term care|skilled nursing": ["cms_nursing_home"],
    "hospice|end of life|palliative": ["cms_hospice"],
    "dialysis|kidney|esrd|renal": ["cms_dialysis", "cms_chronic_conditions"],
    "aging|elderly|older adults|senior": ["aoa_aging_services", "cms_nursing_home"],
    "environmental|pollution|air quality|lead": ["epa_ejscreen", "cdc_lead_exposure"],
    "diabetes|obesity|hypertension|chronic": ["brfss_state_prevalence", "cms_chronic_conditions", "cdc_nhanes"],
    "ehr|electronic health|health it|interoperability": ["onc_ehr_adoption"],
    "aco|accountable care|value based": ["cms_aco", "cms_innovation"],
    "grants|funding|investment": ["hrsa_grants", "nih_research_funding"],
    "workforce projection|future|forecast": ["hrsa_workforce_projections"],
    "transportation|access|rural": ["dot_transportation", "fcc_broadband"],
    "sti|sexually transmitted|chlamydia|gonorrhea|syphilis": ["cdc_sti"],
    "oral health|dental|fluoride|tooth": ["cdc_oral_health", "hpsa_dental"],
    "injury|violence|suicide|homicide|firearm": ["cdc_wisqars", "cdc_drug_overdose"],
    "open payments|industry|pharma|manufacturer": ["cms_open_payments"],
}

BASE_DATASETS = ["state_risk_index", "geo_variation_2014_2023"]


# =============================================================================
# Per-dataset summarizers
# =============================================================================
def _section(header: str, df: pd.DataFrame, max_rows: int = 50) -> tuple[str, str]:
    return header, df.head(max_rows).to_csv(index=False)


def _sum_state_risk_index() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "state_risk_index.csv")
    cols = [
        "state", "state_abbr", "risk_score", "risk_rank", "risk_tier",
        "dim_spending", "dim_supply", "dim_shortage", "dim_disease",
        "dim_insurance", "dim_hospital_quality", "dim_poverty",
    ]
    df = df[cols].copy()
    for c in cols[2:3] + cols[5:]:
        df[c] = df[c].round(1)
    header = (
        "STATE RISK INDEX (all 51 jurisdictions). NOTE: All dimension scores are "
        "percentile-ranked 0-100 where HIGHER = WORSE outcome. A dim_insurance score "
        "of 86 means 86th percentile for uninsured rate — i.e. one of the worst states "
        "for insurance coverage, NOT one of the best."
    )
    return _section(header, df, max_rows=51)


def _sum_geo_variation_2014_2023() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "geo_variation_2014_2023.csv",
        usecols=["YEAR", "BENE_GEO_LVL", "BENE_GEO_DESC", "BENE_AGE_LVL",
                 "TOT_MDCR_STDZD_PYMT_PC", "TOT_MDCR_PYMT_PC",
                 "BENES_FFS_CNT", "TOT_MDCR_PYMT_AMT"],
        low_memory=False,
    )
    df = df[(df["YEAR"] == 2023) & (df["BENE_GEO_LVL"] == "State") & (df["BENE_AGE_LVL"] == "All")]
    for c in ["TOT_MDCR_STDZD_PYMT_PC", "TOT_MDCR_PYMT_PC", "BENES_FFS_CNT", "TOT_MDCR_PYMT_AMT"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["pymt_billions"] = (df["TOT_MDCR_PYMT_AMT"] / 1e9).round(2)
    out = df[["BENE_GEO_DESC", "TOT_MDCR_STDZD_PYMT_PC", "TOT_MDCR_PYMT_PC",
              "BENES_FFS_CNT", "pymt_billions"]].copy()
    out.columns = ["state", "std_pymt_per_bene_2023", "raw_pymt_per_bene_2023",
                   "ffs_beneficiaries", "total_pymt_billions"]
    for c in ["std_pymt_per_bene_2023", "raw_pymt_per_bene_2023"]:
        out[c] = out[c].round(0).astype("Int64")
    out["ffs_beneficiaries"] = out["ffs_beneficiaries"].round(0).astype("Int64")
    return _section("MEDICARE FFS SPENDING 2023 (state, all ages)", out, max_rows=55)


def _sum_cms_medicaid_drug() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cms_medicaid_drug.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest][["state", "year", "total_amount_reimbursed",
                                    "number_of_prescriptions"]].copy()
    df["total_reimbursed_M"] = (df["total_amount_reimbursed"] / 1e6).round(1)
    df = df[["state", "year", "total_reimbursed_M", "number_of_prescriptions"]]
    return _section(f"MEDICAID DRUG SPENDING (latest year: {latest})", df, max_rows=55)


def _sum_ahrf_state_national_2025() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "ahrf_state_national_2025.csv",
        usecols=["st_abbrev", "phys_wkforc_23", "rn_23", "dent_23", "popn_pums_23"],
        low_memory=False,
    )
    df = df[df["st_abbrev"] != "US"].copy()
    for c in ["phys_wkforc_23", "rn_23", "dent_23", "popn_pums_23"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["physicians_per_100k"] = (df["phys_wkforc_23"] / df["popn_pums_23"] * 1e5).round(1)
    df["rn_per_100k"] = (df["rn_23"] / df["popn_pums_23"] * 1e5).round(1)
    df["dentists_per_100k"] = (df["dent_23"] / df["popn_pums_23"] * 1e5).round(1)
    df["population"] = df["popn_pums_23"].round(0).astype("Int64")
    out = df[["st_abbrev", "physicians_per_100k", "rn_per_100k",
              "dentists_per_100k", "population"]]
    return _section("HRSA AHRF WORKFORCE DENSITY 2023 (per 100k population)", out, max_rows=55)


def _sum_cdc_drug_overdose() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cdc_drug_overdose.csv",
        low_memory=False,
        usecols=["state", "state_name", "year", "month", "indicator", "data_value"],
    )
    df = df[df["indicator"] == "Number of Drug Overdose Deaths"].copy()
    df["data_value"] = pd.to_numeric(df["data_value"], errors="coerce")
    df = df.dropna(subset=["data_value"])
    latest_year = int(df["year"].max())
    df = df[df["year"] == latest_year]
    out = (df.sort_values(["state_name", "month"])
             .groupby("state_name", as_index=False)["data_value"].last())
    out.columns = ["state", "od_deaths_12mo_rolling"]
    out["od_deaths_12mo_rolling"] = out["od_deaths_12mo_rolling"].round(0).astype("Int64")
    return _section(
        f"CDC DRUG OVERDOSE DEATHS (year: {latest_year}, 12-month-ending counts)",
        out, max_rows=55,
    )


def _sum_samhsa_facilities() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "samhsa_facilities.csv",
        low_memory=False,
        usecols=["state", "is_substance_use", "is_mental_health", "is_co_occurring"],
    )
    for c in ["is_substance_use", "is_mental_health", "is_co_occurring"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    out = df.groupby("state", as_index=False).agg(
        total_facilities=("state", "count"),
        substance_use=("is_substance_use", "sum"),
        mental_health=("is_mental_health", "sum"),
        co_occurring=("is_co_occurring", "sum"),
    )
    return _section("SAMHSA TREATMENT FACILITIES (counts per state)", out, max_rows=55)


def _sum_cdc_wastewater() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cdc_wastewater.csv",
        low_memory=False,
        usecols=["state_territory", "week_end", "pathogen_target",
                 "wval_pop_weighted_mean", "n_sites_reporting"],
    )
    df["week_end"] = pd.to_datetime(df["week_end"], errors="coerce")
    df = df.dropna(subset=["week_end"])
    last_4 = sorted(df["week_end"].unique())[-4:]
    df = df[df["week_end"].isin(last_4)].copy()
    df["wval_pop_weighted_mean"] = pd.to_numeric(
        df["wval_pop_weighted_mean"], errors="coerce"
    ).round(2)
    df["week_end"] = df["week_end"].dt.strftime("%Y-%m-%d")
    df = df.sort_values(["state_territory", "pathogen_target", "week_end"])
    first = pd.to_datetime(last_4[0]).date()
    last = pd.to_datetime(last_4[-1]).date()
    # 51 reporting jurisdictions × 4 weeks × 3 pathogens = 612 rows max;
    # raise the cap so late-alphabet states (Texas, New York, …) aren't truncated.
    return _section(
        f"CDC NWSS WASTEWATER (most recent 4 weeks: {first} to {last}, "
        "wval_pop_weighted_mean = population-weighted concentration)",
        df, max_rows=700,
    )


def _sum_brfss_state_prevalence() -> tuple[str, str] | None:
    b = pd.read_csv(
        DATA / "brfss_state_prevalence.csv",
        low_memory=False,
        usecols=["year", "class", "topic", "question", "response",
                 "data_value", "locationabbr", "data_value_type"],
    )
    b = b[b["data_value_type"] == "Crude Prevalence"]
    b["data_value"] = pd.to_numeric(b["data_value"], errors="coerce")
    b = b.dropna(subset=["data_value"])

    def _latest(subset: pd.DataFrame, label: str) -> pd.DataFrame:
        idx = subset.groupby("locationabbr")["year"].idxmax()
        out = subset.loc[idx, ["locationabbr", "year", "data_value"]].copy()
        out.columns = ["locationabbr", f"{label}_year", f"{label}_pct"]
        out[f"{label}_pct"] = out[f"{label}_pct"].round(1)
        return out

    diabetes = _latest(b[b["topic"] == "Diabetes"], "diabetes")
    obesity = _latest(
        b[(b["topic"] == "BMI Categories") & b["response"].str.startswith("Obese", na=False)],
        "obesity",
    )
    smoking = _latest(
        b[(b["class"] == "Tobacco Use")
          & b["question"].str.contains("current smokers", case=False, na=False)],
        "smoking",
    )
    out = (diabetes.merge(obesity, on="locationabbr", how="outer")
                   .merge(smoking, on="locationabbr", how="outer"))
    return _section("BRFSS PREVALENCE (latest year per state per measure)", out, max_rows=55)


def _sum_census_sahie() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "census_sahie.csv")
    df = df[(df["IPRCAT"] == 0) & (df["AGECAT"] == 0)
            & (df["SEXCAT"] == 0) & (df["RACECAT"] == 0)]
    latest = int(df["time"].max())
    df = df[df["time"] == latest][["NAME", "state", "PCTUI_PT", "NUI_PT", "NIPR_PT"]].copy()
    df.columns = ["state", "state_fips", "uninsured_pct", "uninsured_count", "total_pop"]
    df["uninsured_pct"] = pd.to_numeric(df["uninsured_pct"], errors="coerce").round(2)
    return _section(
        f"CENSUS SAHIE UNINSURED RATE (year: {latest}, all incomes/ages/sex/race)",
        df, max_rows=55,
    )


def _sum_cdc_hiv() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cdc_hiv.csv",
        low_memory=False,
        usecols=["year", "state_abbr", "state",
                 "newdx_state_rate_per_100k", "newdx_state_cases"],
    )
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    latest = int(df["year"].max())
    df = df[df["year"] == latest][["state_abbr", "state",
                                    "newdx_state_rate_per_100k", "newdx_state_cases"]].copy()
    df["newdx_state_rate_per_100k"] = pd.to_numeric(
        df["newdx_state_rate_per_100k"], errors="coerce"
    ).round(1)
    return _section(f"CDC HIV NEW DIAGNOSES (year: {latest}, state-level)", df, max_rows=55)


def _sum_nci_cancer() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "nci_cancer.csv", sep="|", low_memory=False,
        usecols=["AREA", "YEAR", "SITE", "RACE", "SEX",
                 "EVENT_TYPE", "AGE_ADJUSTED_RATE", "COUNT"],
    )
    # YEAR is stored as a string in the source bundle; coerce before comparing.
    df["YEAR"] = pd.to_numeric(df["YEAR"], errors="coerce")
    df["AGE_ADJUSTED_RATE"] = pd.to_numeric(df["AGE_ADJUSTED_RATE"], errors="coerce")
    df = df[(df["SITE"] == "All Cancer Sites Combined")
            & (df["SEX"] == "Male and Female") & (df["RACE"] == "All Races")]
    df = df.dropna(subset=["AGE_ADJUSTED_RATE", "YEAR"])
    # Incidence and Mortality have different latest years (Mortality typically
    # lags by one year). Take each event_type's own most-recent year so both
    # are represented for every state.
    latest_per_event = df.groupby("EVENT_TYPE")["YEAR"].transform("max")
    df = df[df["YEAR"] == latest_per_event][[
        "AREA", "EVENT_TYPE", "YEAR", "AGE_ADJUSTED_RATE", "COUNT",
    ]].copy()
    df["AGE_ADJUSTED_RATE"] = df["AGE_ADJUSTED_RATE"].round(1)
    df["YEAR"] = df["YEAR"].astype(int)
    df.columns = ["state", "event_type", "year", "age_adj_rate_per_100k", "count"]
    df = df.sort_values(["state", "event_type"])
    inc_yr = int(df.loc[df["event_type"] == "Incidence", "year"].max()) if (df["event_type"] == "Incidence").any() else None
    mort_yr = int(df.loc[df["event_type"] == "Mortality", "year"].max()) if (df["event_type"] == "Mortality").any() else None
    yr_label = f"Incidence: {inc_yr}, Mortality: {mort_yr}"
    # 52 jurisdictions × 2 event types ≈ 103-104 rows; cap leaves headroom.
    return _section(
        f"NCI/CDC CANCER ({yr_label}; All Sites, Both Sexes, All Races)",
        df, max_rows=120,
    )


def _sum_samhsa_nsduh() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "samhsa_nsduh.csv")
    df = df[df["state"].notna()]
    latest_period = df.sort_values("years")["years"].iloc[-1]
    df = df[df["years"] == latest_period][["years", "table_id", "measure", "state",
                                            "group", "estimate_pct"]].head(50)
    return _section(f"SAMHSA NSDUH SUBSTANCE USE (period: {latest_period})", df, max_rows=50)


def _sum_hrsa_ryan_white() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hrsa_ryan_white.csv", low_memory=False,
        usecols=["Recipient/Sub-Recipient State Abbreviation",
                 "Received Part A Funding Indicator",
                 "Received Part B Funding Indicator",
                 "Received Part C Funding Indicator",
                 "Received Part D Funding Indicator"],
    )
    df.columns = ["state", "part_a", "part_b", "part_c", "part_d"]
    for c in ["part_a", "part_b", "part_c", "part_d"]:
        df[c] = (df[c].astype(str).str.strip().str.lower() == "yes").astype(int)
    out = df.groupby("state", as_index=False).agg(
        recipients=("state", "count"),
        part_a_recipients=("part_a", "sum"),
        part_b_recipients=("part_b", "sum"),
        part_c_recipients=("part_c", "sum"),
        part_d_recipients=("part_d", "sum"),
    )
    return _section("HRSA RYAN WHITE HIV/AIDS PROGRAM (recipients per state)", out, max_rows=55)


def _sum_cdc_mortality() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_mortality.csv", low_memory=False)
    latest = int(df["year"].max())
    df = df[df["year"] == latest][["state", "year", "cause_name", "deaths", "aadr"]].copy()
    df["aadr"] = pd.to_numeric(df["aadr"], errors="coerce").round(1)
    return _section(
        f"CDC NCHS LEADING CAUSES OF DEATH (year: {latest}; aadr=age-adjusted death rate per 100k)",
        df, max_rows=120,
    )


def _sum_cdc_wonder_mortality() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_wonder_mortality.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest][["year", "state", "cause_name",
                                    "deaths", "crude_rate_per_100k"]].copy()
    df["crude_rate_per_100k"] = pd.to_numeric(df["crude_rate_per_100k"], errors="coerce").round(1)
    return _section(f"CDC MORTALITY 2018-2023 (year: {latest})", df, max_rows=120)


def _sum_cdc_vaccination() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cdc_vaccination.csv", low_memory=False,
        usecols=["vaccine", "vaccine_type", "geography_type", "geography",
                 "year_season", "dimension_type", "dimension", "coverage_estimate"],
    )
    # Pick national or state-level overall coverage rows
    df = df[df["dimension"].isin(["18+ Years", "65+ Years", "Overall", "≥6 Months", "≥18 Years"])]
    df["coverage_estimate"] = pd.to_numeric(df["coverage_estimate"], errors="coerce")
    df = df.dropna(subset=["coverage_estimate"])
    # Latest season per state per vaccine_type
    out = (df.sort_values("year_season")
             .groupby(["geography", "vaccine_type"], as_index=False)
             .last()[["geography", "vaccine_type", "year_season",
                      "dimension", "coverage_estimate"]])
    out["coverage_estimate"] = out["coverage_estimate"].round(1)
    return _section(
        "CDC VACCINATION COVERAGE (latest season per state per vaccine type)",
        out, max_rows=200,
    )


def _sum_hpsa_primary_care() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hpsa_primary_care.csv", low_memory=False,
        usecols=["HPSA Status", "HPSA Score", "HPSA FTE",
                 "HPSA Designation Population", "State Abbreviation"],
    )
    df = df[df["HPSA Status"] == "Designated"]
    for c in ["HPSA Score", "HPSA FTE", "HPSA Designation Population"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = df.groupby("State Abbreviation", as_index=False).agg(
        designated_hpsas=("HPSA Status", "count"),
        avg_hpsa_score=("HPSA Score", "mean"),
        total_fte_needed=("HPSA FTE", "sum"),
        total_pop_designated=("HPSA Designation Population", "sum"),
    )
    out["avg_hpsa_score"] = out["avg_hpsa_score"].round(1)
    out["total_fte_needed"] = out["total_fte_needed"].round(1)
    out["total_pop_designated"] = out["total_pop_designated"].round(0).astype("Int64")
    return _section("HPSA PRIMARY CARE (designated, state rollup)", out, max_rows=55)


def _sum_hpsa_dental() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hpsa_dental.csv", low_memory=False,
        usecols=["HPSA Status", "HPSA Score", "HPSA FTE",
                 "HPSA Designation Population", "State Abbreviation"],
    )
    df = df[df["HPSA Status"] == "Designated"]
    for c in ["HPSA Score", "HPSA FTE", "HPSA Designation Population"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = df.groupby("State Abbreviation", as_index=False).agg(
        designated_hpsas=("HPSA Status", "count"),
        avg_hpsa_score=("HPSA Score", "mean"),
        total_fte_needed=("HPSA FTE", "sum"),
    )
    out["avg_hpsa_score"] = out["avg_hpsa_score"].round(1)
    out["total_fte_needed"] = out["total_fte_needed"].round(1)
    return _section("HPSA DENTAL (designated, state rollup)", out, max_rows=55)


def _sum_hpsa_mental_health() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hpsa_mental_health.csv", low_memory=False,
        usecols=["HPSA Status", "HPSA Score", "HPSA FTE",
                 "HPSA Designation Population", "State Abbreviation"],
    )
    df = df[df["HPSA Status"] == "Designated"]
    for c in ["HPSA Score", "HPSA FTE", "HPSA Designation Population"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = df.groupby("State Abbreviation", as_index=False).agg(
        designated_hpsas=("HPSA Status", "count"),
        avg_hpsa_score=("HPSA Score", "mean"),
        total_fte_needed=("HPSA FTE", "sum"),
    )
    out["avg_hpsa_score"] = out["avg_hpsa_score"].round(1)
    out["total_fte_needed"] = out["total_fte_needed"].round(1)
    return _section("HPSA MENTAL HEALTH (designated, state rollup)", out, max_rows=55)


def _sum_hrsa_workforce_projections() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hrsa_workforce_projections.csv", low_memory=False,
        usecols=["Year", "Profession Group", "Profession", "State", "Rurality"],
    )
    df = df[df["Rurality"] == "Total"]  # state-total scenario
    latest = int(pd.to_numeric(df["Year"], errors="coerce").max())
    df = df[df["Year"] == latest][["Year", "Profession Group", "Profession", "State"]]
    return _section(
        f"HRSA WORKFORCE PROJECTIONS (Year={latest}, Rurality=Total)",
        df, max_rows=50,
    )


def _sum_gme_residency() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "gme_residency.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest]
    return _section(f"GME RESIDENCY (year: {latest})", df, max_rows=55)


def _sum_ahrq_meps() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "ahrq_meps.csv")
    latest = int(pd.to_numeric(df["year"], errors="coerce").max())
    df = df[df["year"] == latest][["year", "state", "indicator", "value"]].head(60)
    return _section(f"AHRQ MEPS Insurance/Household (year: {latest})", df, max_rows=60)


def _sum_acs_demographics() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "acs_demographics.csv")
    return _section("CENSUS ACS 5-YEAR DEMOGRAPHICS (2019-2023)", df, max_rows=52)


def _sum_cms_inpatient_geo() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cms_inpatient_geo.csv", low_memory=False,
        usecols=["Rndrng_Prvdr_Geo_Lvl", "Rndrng_Prvdr_Geo_Desc",
                 "DRG_Cd", "DRG_Desc", "Tot_Dschrgs",
                 "Avg_Submtd_Cvrd_Chrg", "Avg_Tot_Pymt_Amt"],
    )
    df = df[df["Rndrng_Prvdr_Geo_Lvl"] == "State"]
    out = (df.groupby("Rndrng_Prvdr_Geo_Desc", as_index=False)
             .agg(total_discharges=("Tot_Dschrgs", "sum"),
                  avg_submitted_charge=("Avg_Submtd_Cvrd_Chrg", "mean"),
                  avg_total_payment=("Avg_Tot_Pymt_Amt", "mean")))
    out["avg_submitted_charge"] = out["avg_submitted_charge"].round(0).astype("Int64")
    out["avg_total_payment"] = out["avg_total_payment"].round(0).astype("Int64")
    out.columns = ["state", "total_discharges", "avg_submitted_charge", "avg_total_payment"]
    return _section("CMS MEDICARE INPATIENT 2023 (state rollup across DRGs)", out, max_rows=55)


def _sum_cms_physician_payments() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cms_physician_payments.csv", low_memory=False,
        usecols=["Rndrng_Prvdr_Geo_Lvl", "Rndrng_Prvdr_Geo_Desc",
                 "Tot_Rndrng_Prvdrs", "Tot_Benes", "Tot_Srvcs",
                 "Avg_Mdcr_Pymt_Amt", "Avg_Mdcr_Stdzd_Amt"],
    )
    df = df[df["Rndrng_Prvdr_Geo_Lvl"] == "State"]
    for c in ["Tot_Rndrng_Prvdrs", "Tot_Benes", "Tot_Srvcs",
              "Avg_Mdcr_Pymt_Amt", "Avg_Mdcr_Stdzd_Amt"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = (df.groupby("Rndrng_Prvdr_Geo_Desc", as_index=False)
             .agg(unique_providers_total=("Tot_Rndrng_Prvdrs", "sum"),
                  total_services=("Tot_Srvcs", "sum"),
                  avg_pymt=("Avg_Mdcr_Pymt_Amt", "mean"),
                  avg_std_pymt=("Avg_Mdcr_Stdzd_Amt", "mean")))
    out["avg_pymt"] = out["avg_pymt"].round(2)
    out["avg_std_pymt"] = out["avg_std_pymt"].round(2)
    out.columns = ["state", "summed_provider_rows", "total_services",
                   "avg_pymt_per_hcpcs", "avg_std_pymt_per_hcpcs"]
    return _section("CMS MEDICARE PHYSICIAN SERVICES 2023 (state rollup)", out, max_rows=55)


def _sum_nimh_mental_health() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "nimh_mental_health.csv", low_memory=False)
    latest = df["Time Period Start Date"].max() if "Time Period Start Date" in df.columns else None
    if latest is not None:
        df = df[df["Time Period Start Date"] == latest]
    df = df[["Indicator", "Group", "State", "Subgroup",
             "Time Period Label"] + [c for c in df.columns if "Value" in c][:1]].head(80)
    return _section("NIMH MENTAL HEALTH INDICATORS (latest period)", df, max_rows=80)


def _sum_cdc_births() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_births.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest]
    return _section(f"CDC BIRTHS / NATALITY (year: {latest})", df, max_rows=55)


def _sum_cdc_maternal_mortality() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_maternal_mortality.csv")
    latest_period = df["period"].iloc[-1]
    df = df[df["period"] == latest_period]
    return _section(f"CDC MATERNAL MORTALITY (period: {latest_period})", df, max_rows=55)


def _sum_hrsa_mch() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "hrsa_mch.csv", low_memory=False, usecols=[
        "Measure", "Measure Name", "State", "Year", "Stratifier"
    ])
    latest = int(pd.to_numeric(df["Year"], errors="coerce").max())
    df = df[(df["Year"] == latest) & (df["Stratifier"] == "Total")][
        ["Measure", "Measure Name", "State", "Year"]
    ].head(60)
    return _section(f"HRSA MCH TITLE V (year: {latest}, sample)", df, max_rows=60)


def _sum_census_saipe() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "census_saipe.csv")
    df = df[df["geo_lvl"] == "state"]
    latest = int(df["YEAR"].max())
    df = df[df["YEAR"] == latest][["NAME", "YEAR", "SAEPOVRTALL_PT",
                                    "SAEMHI_PT", "SAEPOVRT0_17_PT"]].copy()
    df.columns = ["state", "year", "poverty_pct_all", "median_hh_income", "child_poverty_pct"]
    return _section(f"CENSUS SAIPE (year: {latest}, state-level)", df, max_rows=55)


def _sum_usda_food_access() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "usda_food_access.csv", low_memory=False,
        usecols=["State", "LILATracts_1And10", "LILATracts_halfAnd10",
                 "LowIncomeTracts", "Pop2010"],
    )
    out = df.groupby("State", as_index=False).agg(
        tracts=("State", "count"),
        lila_tracts_1and10=("LILATracts_1And10", "sum"),
        lila_tracts_halfand10=("LILATracts_halfAnd10", "sum"),
        low_income_tracts=("LowIncomeTracts", "sum"),
        population_2010=("Pop2010", "sum"),
    )
    return _section("USDA FOOD ACCESS (food-desert tract counts per state)", out, max_rows=55)


def _sum_usda_wic() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "usda_wic.csv")
    latest = int(df["fiscal_year"].max())
    df = df[df["fiscal_year"] == latest][[
        "state", "fiscal_year", "total_participation_avg_monthly",
        "food_cost_total_usd", "total_program_cost_usd",
        "avg_monthly_benefit_per_person_usd",
    ]]
    return _section(f"USDA WIC PROGRAM (FY {latest})", df, max_rows=55)


def _sum_fcc_broadband() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "fcc_broadband.csv", low_memory=False,
        usecols=["StateAbbr", "TotalPop", "TotalBSLs",
                 "ServedBSLs", "UnderservedBSLs", "UnservedBSLs", "UniqueProviders"],
    )
    out = df.groupby("StateAbbr", as_index=False).agg(
        counties=("StateAbbr", "count"),
        total_pop=("TotalPop", "sum"),
        total_bsls=("TotalBSLs", "sum"),
        served_bsls=("ServedBSLs", "sum"),
        underserved_bsls=("UnderservedBSLs", "sum"),
        unserved_bsls=("UnservedBSLs", "sum"),
        avg_unique_providers=("UniqueProviders", "mean"),
    )
    out["pct_served_100_20"] = (out["served_bsls"] / out["total_bsls"] * 100).round(1)
    out["pct_unserved"] = (out["unserved_bsls"] / out["total_bsls"] * 100).round(1)
    out["avg_unique_providers"] = out["avg_unique_providers"].round(1)
    return _section("FCC BROADBAND June 2024 (state rollup of county BSLs)", out, max_rows=55)


def _sum_hrsa_telehealth() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "hrsa_telehealth.csv", low_memory=False, nrows=80)
    return _section("HRSA TELEHEALTH (Medicare beneficiary stratification, sample)",
                    df, max_rows=80)


def _sum_dot_transportation() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "dot_transportation.csv")
    cols = [c for c in df.columns if df[c].dtype != "object"][:6]
    out = df.groupby("State Name", as_index=False).agg({c: "sum" for c in cols})
    return _section("DOT TRANSPORTATION (state rollup of county counts)", out, max_rows=55)


def _sum_hospital_compare_general_info() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hospital_compare_general_info.csv", low_memory=False,
        usecols=["State", "Hospital overall rating", "Hospital Type",
                 "Hospital Ownership", "Emergency Services"],
    )
    df["rating"] = pd.to_numeric(df["Hospital overall rating"], errors="coerce")
    out = df.groupby("State", as_index=False).agg(
        hospital_count=("State", "count"),
        avg_overall_rating=("rating", "mean"),
        rated_hospitals=("rating", "count"),
        emergency_services_yes=("Emergency Services",
                                lambda s: (s.astype(str).str.lower() == "yes").sum()),
    )
    out["avg_overall_rating"] = out["avg_overall_rating"].round(2)
    return _section("HOSPITAL COMPARE — General Info (state rollup, 1-5★ avg rating)",
                    out, max_rows=55)


def _sum_hospital_compare_readmissions_state() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hospital_compare_readmissions_state.csv", low_memory=False,
        usecols=["State", "Measure ID", "Measure Name",
                 "Number of Hospitals Worse", "Number of Hospitals Same",
                 "Number of Hospitals Better"],
    )
    return _section("HOSPITAL COMPARE — Unplanned Visits state distribution",
                    df, max_rows=80)


def _sum_hospital_compare_complications_state() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hospital_compare_complications_state.csv", low_memory=False,
    )
    return _section("HOSPITAL COMPARE — Complications & Deaths state distribution",
                    df, max_rows=80)


def _sum_cms_nursing_home() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cms_nursing_home.csv", low_memory=False,
        usecols=["State", "Overall Rating", "Health Inspection Rating",
                 "Staffing Rating", "Number of Certified Beds",
                 "Average Number of Residents per Day"],
    )
    for c in ["Overall Rating", "Health Inspection Rating", "Staffing Rating",
              "Number of Certified Beds", "Average Number of Residents per Day"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    out = df.groupby("State", as_index=False).agg(
        nursing_homes=("State", "count"),
        avg_overall_rating=("Overall Rating", "mean"),
        avg_health_inspection=("Health Inspection Rating", "mean"),
        avg_staffing_rating=("Staffing Rating", "mean"),
        total_certified_beds=("Number of Certified Beds", "sum"),
    )
    for c in ["avg_overall_rating", "avg_health_inspection", "avg_staffing_rating"]:
        out[c] = out[c].round(2)
    out["total_certified_beds"] = out["total_certified_beds"].round(0).astype("Int64")
    return _section("CMS NURSING HOMES (state rollup, 5-star ratings)", out, max_rows=55)


def _sum_cms_hospice() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cms_hospice.csv", low_memory=False, usecols=["State"])
    out = df.groupby("State", as_index=False).size()
    out.columns = ["state", "hospice_count"]
    return _section("CMS HOSPICE (count of certified providers per state)",
                    out, max_rows=55)


def _sum_cms_dialysis() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cms_dialysis.csv", low_memory=False, usecols=["State", "Five Star"],
    )
    df["Five Star"] = pd.to_numeric(df["Five Star"], errors="coerce")
    out = df.groupby("State", as_index=False).agg(
        dialysis_facilities=("State", "count"),
        avg_5star=("Five Star", "mean"),
    )
    out["avg_5star"] = out["avg_5star"].round(2)
    return _section("CMS DIALYSIS (state rollup, 5-star ratings)", out, max_rows=55)


def _sum_cms_chronic_conditions() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cms_chronic_conditions.csv")
    latest = int(pd.to_numeric(df["year"], errors="coerce").max())
    # National-aggregable: filter to a manageable cut — most recent year, all sex/age, top conditions
    df = df[df["year"] == latest]
    df = df[(df["sex"] == "All") & (df["age_band"] == "All")]
    df = df[["year", "state", "condition", "prevalence_pct"]].head(120)
    return _section(f"CMS MEDICARE CHRONIC CONDITIONS (year: {latest}, all sex/age)",
                    df, max_rows=120)


def _sum_aoa_aging_services() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "aoa_aging_services.csv", low_memory=False,
        usecols=["Year", "State", "Geo_Abbrv",
                 "AaaFullTime", "AAA_Volunteers", "CommunityStaff"],
    )
    latest = int(pd.to_numeric(df["Year"], errors="coerce").max())
    df = df[df["Year"] == latest]
    return _section(f"AoA AGING SERVICES NAPIS (year: {latest})", df, max_rows=55)


def _sum_epa_ejscreen() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "epa_ejscreen.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest]
    df["state_fips"] = df["county_fips"].astype(str).str.zfill(5).str[:2]
    out = df.groupby("state_fips", as_index=False).agg(
        counties=("state_fips", "count"),
        total_population=("population", "sum"),
        avg_pm25=("pm25", "mean"),
        avg_ozone=("ozone", "mean"),
        avg_diesel_pm=("diesel_pm", "mean"),
        avg_traffic_proximity=("traffic_proximity", "mean"),
        avg_lead_paint=("lead_paint", "mean"),
    )
    for c in out.columns[3:]:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(3)
    return _section(f"EPA EJSCREEN ENV BURDEN (year: {latest}, state rollup)",
                    out, max_rows=55)


def _sum_cdc_lead_exposure() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_lead_exposure.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest]
    return _section(f"CDC CHILDHOOD LEAD EXPOSURE (year: {latest})", df, max_rows=55)


def _sum_cdc_nhanes() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_nhanes.csv", low_memory=False)
    return _section("CDC NHANES (national summary estimates, sample)",
                    df.head(60), max_rows=60)


def _sum_onc_ehr_adoption() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "onc_ehr_adoption.csv", low_memory=False,
        usecols=["region", "period", "pct_hospitals_cehrt",
                 "pct_hospitals_send_receive_find_integrate",
                 "pct_hospitals_hie_participate"],
    )
    df = df[df["region"] != "United States"]
    latest = int(pd.to_numeric(df["period"], errors="coerce").max())
    df = df[df["period"] == latest]
    return _section(f"ONC HOSPITAL EHR ADOPTION (year: {latest}, state-level)",
                    df, max_rows=55)


def _sum_cms_aco() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cms_aco.csv", low_memory=False,
        usecols=["ACO_State", "ACO_NAME", "N_AB"],
    )
    df["N_AB"] = pd.to_numeric(df["N_AB"], errors="coerce")
    out = df.groupby("ACO_State", as_index=False).agg(
        aco_count=("ACO_NAME", "count"),
        total_assigned_beneficiaries=("N_AB", "sum"),
    )
    out["total_assigned_beneficiaries"] = out["total_assigned_beneficiaries"].round(0).astype("Int64")
    return _section("CMS MSSP ACO (count and assigned beneficiaries per state)",
                    out, max_rows=60)


def _sum_cms_innovation() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "cms_innovation.csv", low_memory=False,
        usecols=["Name of Initiative", "State", "Category"],
    )
    out = (df.groupby(["State", "Category"], as_index=False)
             .size().rename(columns={"size": "participants"}))
    return _section("CMS INNOVATION CENTER (CMMI) participants by state × category",
                    out, max_rows=120)


def _sum_hrsa_grants() -> tuple[str, str] | None:
    df = pd.read_csv(
        DATA / "hrsa_grants.csv", low_memory=False,
        usecols=["Award Year", "Financial Assistance", "Grantee State Abbreviation"]
        if "Grantee State Abbreviation" in pd.read_csv(DATA / "hrsa_grants.csv", nrows=0).columns
        else None,
    )
    latest = int(pd.to_numeric(df["Award Year"], errors="coerce").max())
    df = df[df["Award Year"] == latest]
    df["Financial Assistance"] = pd.to_numeric(df["Financial Assistance"], errors="coerce")
    state_col = [c for c in df.columns if "State" in c][0]
    out = df.groupby(state_col, as_index=False).agg(
        grants_count=(state_col, "count"),
        total_financial_assistance=("Financial Assistance", "sum"),
    )
    out["total_financial_assistance_M"] = (out["total_financial_assistance"] / 1e6).round(2)
    out = out.drop(columns=["total_financial_assistance"])
    return _section(f"HRSA GRANTS (latest year: {latest}, state rollup)",
                    out, max_rows=55)


def _sum_nih_research_funding() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "nih_research_funding.csv")
    latest = int(df["fiscal_year"].max())
    df = df[df["fiscal_year"] == latest]
    out = df.groupby("state", as_index=False).agg(
        total_award_M=("award_amount_usd", lambda x: round(x.sum() / 1e6, 2)),
        project_count=("project_count", "sum"),
    )
    return _section(f"NIH RESEARCH FUNDING (FY {latest}, by state)", out, max_rows=55)


def _sum_cdc_sti() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_sti.csv")
    latest = int(df["year"].max())
    df = df[df["year"] == latest]
    out = df.groupby(["reporting_area", "disease"], as_index=False)["cases"].sum()
    return _section(f"CDC STI SURVEILLANCE (year: {latest}, by state × disease)",
                    out, max_rows=200)


def _sum_cdc_oral_health() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_oral_health.csv", low_memory=False)
    latest = int(pd.to_numeric(df["year"], errors="coerce").max())
    df = df[(df["year"] == latest)
            & df["indicator"].astype(str).str.contains("dental visit", case=False, na=False)]
    df = df[["topic", "year", "location_abbr", "indicator", "data_value"]].head(60)
    return _section(f"CDC ORAL HEALTH NOHSS (year: {latest}, dental visit indicators)",
                    df, max_rows=60)


def _sum_cdc_wisqars() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cdc_wisqars.csv", low_memory=False)
    return _section("CDC WISQARS INJURY (national, recent quarters)",
                    df.head(40), max_rows=40)


def _sum_cms_open_payments() -> tuple[str, str] | None:
    df = pd.read_csv(DATA / "cms_open_payments.csv")
    return _section("CMS OPEN PAYMENTS 2023 (state-aggregated)", df, max_rows=60)


SUMMARIZERS: dict[str, Callable[[], tuple[str, str] | None]] = {
    "state_risk_index": _sum_state_risk_index,
    "geo_variation_2014_2023": _sum_geo_variation_2014_2023,
    "cms_medicaid_drug": _sum_cms_medicaid_drug,
    "ahrf_state_national_2025": _sum_ahrf_state_national_2025,
    "cdc_drug_overdose": _sum_cdc_drug_overdose,
    "samhsa_facilities": _sum_samhsa_facilities,
    "cdc_wastewater": _sum_cdc_wastewater,
    "brfss_state_prevalence": _sum_brfss_state_prevalence,
    "census_sahie": _sum_census_sahie,
    "cdc_hiv": _sum_cdc_hiv,
    "nci_cancer": _sum_nci_cancer,
    "samhsa_nsduh": _sum_samhsa_nsduh,
    "hrsa_ryan_white": _sum_hrsa_ryan_white,
    "cdc_mortality": _sum_cdc_mortality,
    "cdc_wonder_mortality": _sum_cdc_wonder_mortality,
    "cdc_vaccination": _sum_cdc_vaccination,
    "hpsa_primary_care": _sum_hpsa_primary_care,
    "hpsa_dental": _sum_hpsa_dental,
    "hpsa_mental_health": _sum_hpsa_mental_health,
    "hrsa_workforce_projections": _sum_hrsa_workforce_projections,
    "gme_residency": _sum_gme_residency,
    "ahrq_meps": _sum_ahrq_meps,
    "acs_demographics": _sum_acs_demographics,
    "cms_inpatient_geo": _sum_cms_inpatient_geo,
    "cms_physician_payments": _sum_cms_physician_payments,
    "nimh_mental_health": _sum_nimh_mental_health,
    "cdc_births": _sum_cdc_births,
    "cdc_maternal_mortality": _sum_cdc_maternal_mortality,
    "hrsa_mch": _sum_hrsa_mch,
    "census_saipe": _sum_census_saipe,
    "usda_food_access": _sum_usda_food_access,
    "usda_wic": _sum_usda_wic,
    "fcc_broadband": _sum_fcc_broadband,
    "hrsa_telehealth": _sum_hrsa_telehealth,
    "dot_transportation": _sum_dot_transportation,
    "hospital_compare_general_info": _sum_hospital_compare_general_info,
    "hospital_compare_readmissions_state": _sum_hospital_compare_readmissions_state,
    "hospital_compare_complications_state": _sum_hospital_compare_complications_state,
    "cms_nursing_home": _sum_cms_nursing_home,
    "cms_hospice": _sum_cms_hospice,
    "cms_dialysis": _sum_cms_dialysis,
    "cms_chronic_conditions": _sum_cms_chronic_conditions,
    "aoa_aging_services": _sum_aoa_aging_services,
    "epa_ejscreen": _sum_epa_ejscreen,
    "cdc_lead_exposure": _sum_cdc_lead_exposure,
    "cdc_nhanes": _sum_cdc_nhanes,
    "onc_ehr_adoption": _sum_onc_ehr_adoption,
    "cms_aco": _sum_cms_aco,
    "cms_innovation": _sum_cms_innovation,
    "hrsa_grants": _sum_hrsa_grants,
    "nih_research_funding": _sum_nih_research_funding,
    "cdc_sti": _sum_cdc_sti,
    "cdc_oral_health": _sum_cdc_oral_health,
    "cdc_wisqars": _sum_cdc_wisqars,
    "cms_open_payments": _sum_cms_open_payments,
}


# =============================================================================
# RAG retrieval
# =============================================================================
def retrieve_context(question: str) -> str:
    """Pick datasets matching keyword patterns + base datasets, summarize each.

    Always includes BASE_DATASETS (state_risk_index + geo_variation). Iterates
    DATASET_REGISTRY; for each pattern that matches the lowercased question,
    queues those datasets. Loads each summarizer (deduplicated) and joins
    with section headers.
    """
    q_lower = question.lower()
    # Matched datasets first (highest relevance), BASE_DATASETS last so the
    # Groq trim — which keeps the leading 4000 chars — preserves the
    # query-relevant sections rather than the generic baseline.
    matched: list[str] = []
    for pattern, datasets in DATASET_REGISTRY.items():
        if re.search(pattern, q_lower):
            for d in datasets:
                if d not in matched:
                    matched.append(d)
    selected: list[str] = matched + [b for b in BASE_DATASETS if b not in matched]

    print(f"[retrieve_context] question: {question[:100]!r}", file=sys.stderr)
    print(f"[retrieve_context] retrieved datasets ({len(selected)}): {selected}",
          file=sys.stderr)

    parts: list[str] = []
    for name in selected:
        fn = SUMMARIZERS.get(name)
        if fn is None:
            continue
        try:
            result = fn()
            if result is None:
                continue
            header, csv_text = result
            parts.append(f"=== {header} ===")
            parts.append(csv_text)
        except Exception as e:
            print(f"[retrieve_context] WARN: {name} failed: {e}", file=sys.stderr)
            continue
    return "\n\n".join(parts) if parts else "(no context retrieved)"


# =============================================================================
# Size-based provider routing
# =============================================================================
SMALL_CONTEXT_THRESHOLD = 4000  # chars

# Small contexts fit Groq's free TPM cap → try the free, fast path first.
SMALL_CONTEXT_CHAIN = ["groq", "openai", "gemini", "together"]

# Large contexts can't fit Groq without lossy trimming → spend OpenAI's
# cheap paid tokens (gpt-4o-mini ~$0.0002/1k input) before falling back.
# Groq is appended as last resort, where trim_context_for_provider() will
# truncate to 4K chars.
LARGE_CONTEXT_CHAIN = ["openai", "gemini", "together", "groq"]

PROVIDER_DISPLAY = {p: PROVIDER_LABELS[p] for p in PROVIDER_LABELS}


def _format_chain(chain: list[str]) -> str:
    return " → ".join(PROVIDER_DISPLAY[p] for p in chain)


# =============================================================================
# Public entry point
# =============================================================================
def query_analyst(question: str) -> tuple[str, str, int, str]:
    """Walks a size-routed provider chain; returns (response, provider_used, context_chars, route_label).

    1. retrieve_context(question) builds a keyword-targeted context.
    2. If len(context) < 4000 chars → SMALL chain (Groq first, free + fast).
    3. If len(context) >= 4000 chars → LARGE chain (OpenAI first, full
       context; Groq appended as last resort with trimming).
    4. Each provider receives a context sized for its rate-limit profile via
       trim_context_for_provider() (only Groq trims).
    """
    context = retrieve_context(question)
    context_chars = len(context)

    if context_chars < SMALL_CONTEXT_THRESHOLD:
        chain = SMALL_CONTEXT_CHAIN
        route_label = f"Small context ({context_chars:,} chars) · {_format_chain(chain)}"
    else:
        chain = LARGE_CONTEXT_CHAIN
        route_label = (
            f"Large context ({context_chars:,} chars) · {_format_chain(chain)} "
            "(Groq trimmed to 4K chars if reached)"
        )

    last_error: Exception | None = None
    tried = 0
    for provider in chain:
        if not _has_key(provider):
            continue
        tried += 1
        try:
            sized_context = trim_context_for_provider(context, provider)
            response = _HANDLERS[provider](question, sized_context)
            if response and response.strip():
                return response, provider, context_chars, route_label
        except Exception as e:
            last_error = e
            continue
    if tried == 0:
        raise RuntimeError("No AI provider API keys configured in .streamlit/secrets.toml.")
    raise RuntimeError(f"All {tried} configured AI provider(s) failed. Last error: {last_error}")
