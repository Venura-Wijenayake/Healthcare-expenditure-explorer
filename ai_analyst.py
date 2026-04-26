"""
AI Analyst — hot-swappable LLM provider chain for the healthcare dashboard.

Provider priority: Groq → Gemini → Together AI. Each is tried in order; on any
failure (rate limit, network, auth) the chain silently falls back to the next.
API keys are read from st.secrets.
"""
from __future__ import annotations
from pathlib import Path
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

PROVIDERS = ["groq", "gemini", "together"]
PROVIDER_LABELS = {"groq": "Groq", "gemini": "Gemini", "together": "Together AI"}

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
TOGETHER_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

KEY_NAMES = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "together": "TOGETHER_API_KEY",
}


def _has_key(provider: str) -> bool:
    try:
        return bool(str(st.secrets.get(KEY_NAMES[provider], "")).strip())
    except Exception:
        return False


def get_active_provider() -> str | None:
    """First provider in priority order with a configured (non-empty) key."""
    for p in PROVIDERS:
        if _has_key(p):
            return p
    return None


def _call_groq(question: str, context: str) -> str:
    from groq import Groq
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"DATA CONTEXT:\n{context}\n\nQUESTION: {question}"},
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
        f"DATA CONTEXT:\n{context}\n\nQUESTION: {question}",
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
            {"role": "user", "content": f"DATA CONTEXT:\n{context}\n\nQUESTION: {question}"},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    return resp.choices[0].message.content or ""


_HANDLERS = {"groq": _call_groq, "gemini": _call_gemini, "together": _call_together}


def query_analyst(question: str, context: str) -> tuple[str, str]:
    """Try each provider in priority order; return (response, provider_used).

    Silently falls back on any error from a provider that has a key configured.
    Raises RuntimeError only if every available provider fails or none is configured.
    """
    last_error: Exception | None = None
    tried = 0
    for provider in PROVIDERS:
        if not _has_key(provider):
            continue
        tried += 1
        try:
            response = _HANDLERS[provider](question, context)
            if response and response.strip():
                return response, provider
        except Exception as e:
            last_error = e
            continue
    if tried == 0:
        raise RuntimeError("No AI provider API keys configured in .streamlit/secrets.toml.")
    raise RuntimeError(f"All {tried} configured AI provider(s) failed. Last error: {last_error}")


@st.cache_data(show_spinner=False)
def build_context() -> str:
    """Pre-computed compact summary inlined into the prompt for every query.

    Cached because the underlying CSVs don't change between queries within a session.
    """
    parts: list[str] = []

    # State Risk Index — all 51 rows compact
    try:
        risk = pd.read_csv(DATA / "state_risk_index.csv")
        cols = [
            "state", "state_abbr", "risk_score", "risk_rank", "risk_tier",
            "dim_spending", "dim_supply", "dim_shortage", "dim_disease",
            "dim_insurance", "dim_hospital_quality", "dim_poverty",
        ]
        rows = risk[cols].copy()
        for c in cols[2:3] + cols[5:]:
            rows[c] = rows[c].round(1)
        parts.append("=== STATE RISK INDEX (all 51 jurisdictions) ===")
        parts.append(
            "NOTE: All dimension scores are percentile-ranked 0-100 where HIGHER = WORSE "
            "outcome. A dim_insurance score of 86 means 86th percentile for uninsured rate "
            "— i.e. one of the worst states for insurance coverage, NOT one of the best."
        )
        parts.append(rows.to_csv(index=False))
    except Exception:
        pass

    # Medicare spending 2023, state-level, all ages
    try:
        gv = pd.read_csv(
            DATA / "geo_variation_2014_2023.csv",
            usecols=[
                "YEAR", "BENE_GEO_LVL", "BENE_GEO_DESC", "BENE_AGE_LVL",
                "TOT_MDCR_STDZD_PYMT_PC", "TOT_MDCR_PYMT_PC",
                "BENES_FFS_CNT", "TOT_MDCR_PYMT_AMT",
            ],
            low_memory=False,
        )
        gv = gv[(gv["YEAR"] == 2023) & (gv["BENE_GEO_LVL"] == "State") & (gv["BENE_AGE_LVL"] == "All")]
        for c in ["TOT_MDCR_STDZD_PYMT_PC", "TOT_MDCR_PYMT_PC", "BENES_FFS_CNT", "TOT_MDCR_PYMT_AMT"]:
            gv[c] = pd.to_numeric(gv[c], errors="coerce")
        gv["total_pymt_billions"] = (gv["TOT_MDCR_PYMT_AMT"] / 1e9).round(2)
        spending = gv[[
            "BENE_GEO_DESC", "TOT_MDCR_STDZD_PYMT_PC", "TOT_MDCR_PYMT_PC",
            "BENES_FFS_CNT", "total_pymt_billions",
        ]].copy()
        spending.columns = [
            "state", "std_pymt_per_bene_2023", "raw_pymt_per_bene_2023",
            "ffs_beneficiaries", "total_pymt_billions",
        ]
        for c in ["std_pymt_per_bene_2023", "raw_pymt_per_bene_2023"]:
            spending[c] = spending[c].round(0).astype("Int64")
        spending["ffs_beneficiaries"] = spending["ffs_beneficiaries"].round(0).astype("Int64")
        parts.append("=== MEDICARE FFS SPENDING 2023 (state, all ages) ===")
        parts.append(spending.to_csv(index=False))
    except Exception:
        pass

    # Medicaid drug spending — latest year by state
    try:
        md = pd.read_csv(DATA / "cms_medicaid_drug.csv")
        latest_year = int(md["year"].max())
        md = md[md["year"] == latest_year][[
            "state", "year", "total_amount_reimbursed", "number_of_prescriptions",
        ]].copy()
        md["total_reimbursed_millions"] = (md["total_amount_reimbursed"] / 1e6).round(1)
        md = md[["state", "year", "total_reimbursed_millions", "number_of_prescriptions"]]
        parts.append(f"=== MEDICAID DRUG SPENDING (latest year: {latest_year}, by state) ===")
        parts.append(md.to_csv(index=False))
    except Exception:
        pass

    # AHRF workforce density (physicians/RN/dentists per 100k) — quick add since AHRF is wide
    try:
        ahrf = pd.read_csv(
            DATA / "ahrf_state_national_2025.csv",
            usecols=["st_abbrev", "phys_wkforc_23", "rn_23", "dent_23", "popn_pums_23"],
            low_memory=False,
        )
        ahrf = ahrf[ahrf["st_abbrev"] != "US"].copy()
        for c in ["phys_wkforc_23", "rn_23", "dent_23", "popn_pums_23"]:
            ahrf[c] = pd.to_numeric(ahrf[c], errors="coerce")
        ahrf["physicians_per_100k"] = (ahrf["phys_wkforc_23"] / ahrf["popn_pums_23"] * 1e5).round(1)
        ahrf["rn_per_100k"] = (ahrf["rn_23"] / ahrf["popn_pums_23"] * 1e5).round(1)
        ahrf["dentists_per_100k"] = (ahrf["dent_23"] / ahrf["popn_pums_23"] * 1e5).round(1)
        ahrf["population"] = ahrf["popn_pums_23"].round(0).astype("Int64")
        wf = ahrf[["st_abbrev", "physicians_per_100k", "rn_per_100k", "dentists_per_100k", "population"]]
        parts.append("=== HRSA AHRF WORKFORCE DENSITY 2023 (per 100k pop) ===")
        parts.append(wf.to_csv(index=False))
    except Exception:
        pass

    # CDC Drug Overdose — total OD deaths by state (12-month-ending), latest year
    try:
        od = pd.read_csv(
            DATA / "cdc_drug_overdose.csv",
            low_memory=False,
            usecols=["state", "state_name", "year", "month", "indicator", "data_value"],
        )
        od = od[od["indicator"] == "Number of Drug Overdose Deaths"].copy()
        od["data_value"] = pd.to_numeric(od["data_value"], errors="coerce")
        od = od.dropna(subset=["data_value"])
        latest_year_od = int(od["year"].max())
        od_latest = od[od["year"] == latest_year_od]
        # Latest 12-month-ending value per state for that year
        od_state = (
            od_latest.sort_values(["state_name", "month"])
            .groupby("state_name", as_index=False)["data_value"].last()
        )
        od_state.columns = ["state", "od_deaths_12mo_rolling"]
        od_state["od_deaths_12mo_rolling"] = od_state["od_deaths_12mo_rolling"].round(0).astype("Int64")
        parts.append(f"=== CDC DRUG OVERDOSE DEATHS (year: {latest_year_od}, 12-month-ending counts) ===")
        parts.append(od_state.to_csv(index=False))
    except Exception:
        pass

    # SAMHSA Facilities — counts of substance use / mental health / co-occurring per state
    try:
        sf = pd.read_csv(
            DATA / "samhsa_facilities.csv",
            low_memory=False,
            usecols=["state", "is_substance_use", "is_mental_health", "is_co_occurring"],
        )
        for c in ["is_substance_use", "is_mental_health", "is_co_occurring"]:
            sf[c] = pd.to_numeric(sf[c], errors="coerce").fillna(0).astype(int)
        counts = sf.groupby("state", as_index=False).agg(
            total_facilities=("state", "count"),
            substance_use=("is_substance_use", "sum"),
            mental_health=("is_mental_health", "sum"),
            co_occurring=("is_co_occurring", "sum"),
        )
        parts.append("=== SAMHSA TREATMENT FACILITIES (counts per state, current snapshot) ===")
        parts.append(counts.to_csv(index=False))
    except Exception:
        pass

    # CDC Wastewater (NWSS) — most recent 4 weeks, by state × pathogen
    try:
        ww = pd.read_csv(
            DATA / "cdc_wastewater.csv",
            low_memory=False,
            usecols=["state_territory", "week_end", "pathogen_target",
                     "wval_pop_weighted_mean", "n_sites_reporting"],
        )
        ww["week_end"] = pd.to_datetime(ww["week_end"], errors="coerce")
        ww = ww.dropna(subset=["week_end"])
        last_4_weeks = sorted(ww["week_end"].unique())[-4:]
        ww_recent = ww[ww["week_end"].isin(last_4_weeks)].copy()
        ww_recent["wval_pop_weighted_mean"] = pd.to_numeric(
            ww_recent["wval_pop_weighted_mean"], errors="coerce"
        ).round(2)
        ww_recent["week_end"] = ww_recent["week_end"].dt.strftime("%Y-%m-%d")
        ww_recent = ww_recent[[
            "state_territory", "week_end", "pathogen_target",
            "wval_pop_weighted_mean", "n_sites_reporting",
        ]].sort_values(["state_territory", "pathogen_target", "week_end"])
        first_week = pd.to_datetime(last_4_weeks[0]).date()
        last_week = pd.to_datetime(last_4_weeks[-1]).date()
        parts.append(
            f"=== CDC NWSS WASTEWATER (most recent 4 weeks: {first_week} to {last_week}, "
            "wval_pop_weighted_mean is population-weighted concentration) ==="
        )
        parts.append(ww_recent.to_csv(index=False))
    except Exception:
        pass

    # BRFSS — latest year per state, diabetes + obesity + current-smoker prevalence
    try:
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
        brfss_combined = (
            diabetes.merge(obesity, on="locationabbr", how="outer")
                    .merge(smoking, on="locationabbr", how="outer")
        )
        parts.append("=== BRFSS PREVALENCE (latest available year per state per measure) ===")
        parts.append(brfss_combined.to_csv(index=False))
    except Exception:
        pass

    # Census SAHIE — uninsured rate, latest year, all-income (IPRCAT=0)
    try:
        sahie = pd.read_csv(DATA / "census_sahie.csv")
        sahie = sahie[
            (sahie["IPRCAT"] == 0) & (sahie["AGECAT"] == 0)
            & (sahie["SEXCAT"] == 0) & (sahie["RACECAT"] == 0)
        ]
        latest_sahie = int(sahie["time"].max())
        sahie = sahie[sahie["time"] == latest_sahie][[
            "NAME", "state", "PCTUI_PT", "NUI_PT", "NIPR_PT",
        ]].copy()
        sahie.columns = ["state", "state_fips", "uninsured_pct", "uninsured_count", "total_pop"]
        sahie["uninsured_pct"] = pd.to_numeric(sahie["uninsured_pct"], errors="coerce").round(2)
        parts.append(f"=== CENSUS SAHIE UNINSURED RATE (year: {latest_sahie}, all incomes/ages/sex/race) ===")
        parts.append(sahie.to_csv(index=False))
    except Exception:
        pass

    # CDC HIV — new diagnosis rate, latest year, state-level
    try:
        hiv = pd.read_csv(
            DATA / "cdc_hiv.csv",
            low_memory=False,
            usecols=["year", "state_abbr", "state",
                     "newdx_state_rate_per_100k", "newdx_state_cases"],
        )
        hiv["year"] = pd.to_numeric(hiv["year"], errors="coerce").astype("Int64")
        latest_hiv = int(hiv["year"].max())
        hiv = hiv[hiv["year"] == latest_hiv][[
            "state_abbr", "state", "newdx_state_rate_per_100k", "newdx_state_cases",
        ]].copy()
        hiv["newdx_state_rate_per_100k"] = pd.to_numeric(
            hiv["newdx_state_rate_per_100k"], errors="coerce"
        ).round(1)
        parts.append(f"=== CDC HIV NEW DIAGNOSES (year: {latest_hiv}, state-level) ===")
        parts.append(hiv.to_csv(index=False))
    except Exception:
        pass

    # NCI Cancer — age-adjusted rates, latest year, All Sites × Both Sexes × All Races
    try:
        cancer = pd.read_csv(
            DATA / "nci_cancer.csv",
            sep="|",
            low_memory=False,
            usecols=["AREA", "YEAR", "SITE", "RACE", "SEX",
                     "EVENT_TYPE", "AGE_ADJUSTED_RATE", "COUNT"],
        )
        cancer = cancer[
            (cancer["SITE"] == "All Cancer Sites Combined")
            & (cancer["SEX"] == "Male and Female")
            & (cancer["RACE"] == "All Races")
        ]
        cancer["AGE_ADJUSTED_RATE"] = pd.to_numeric(cancer["AGE_ADJUSTED_RATE"], errors="coerce")
        cancer = cancer.dropna(subset=["AGE_ADJUSTED_RATE"])
        latest_cancer = int(cancer["YEAR"].max())
        cancer = cancer[cancer["YEAR"] == latest_cancer][[
            "AREA", "EVENT_TYPE", "AGE_ADJUSTED_RATE", "COUNT",
        ]].copy()
        cancer["AGE_ADJUSTED_RATE"] = cancer["AGE_ADJUSTED_RATE"].round(1)
        cancer.columns = ["state", "event_type", "age_adj_rate_per_100k", "count"]
        cancer = cancer.sort_values(["state", "event_type"])
        parts.append(
            f"=== NCI/CDC CANCER (year: {latest_cancer}, All Cancer Sites Combined, "
            "Male+Female, All Races; Incidence + Mortality) ==="
        )
        parts.append(cancer.to_csv(index=False))
    except Exception:
        pass

    return "\n\n".join(parts) if parts else "(no pre-computed context available)"
