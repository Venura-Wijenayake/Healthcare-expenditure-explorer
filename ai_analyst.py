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
GEMINI_MODEL = "gemini-1.5-flash"
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
        parts.append("=== STATE RISK INDEX (all 51 jurisdictions; 0–100 percentile, higher=worse) ===")
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

    return "\n\n".join(parts) if parts else "(no pre-computed context available)"
