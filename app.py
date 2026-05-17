import time
from io import StringIO
from pathlib import Path
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from data_loader import fetch_part_d_data, fetch_part_b_data, load_geo_variation, load_ahrf, load_hpsa
from ai_analyst import (
    query_analyst,
    get_active_provider,
    PROVIDER_LABELS,
    DATASET_DISPLAY,
    SUMMARIZERS,
)
from views import ca_workforce_atlas

st.set_page_config(
    page_title="U.S. Healthcare Intelligence Platform",
    page_icon="🏥",
    layout="wide",
)

# ======================================================================
# STEP 1 — Global CSS (Google Fonts + design system)
# ======================================================================
st.markdown(
    """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg-primary: #080F1A;
  --bg-secondary: #0D1B2E;
  --bg-card: #111F35;
  --bg-card-hover: #162540;
  --border: #1E3A5F;
  --border-light: #243F66;
  --accent-blue: #1B6FE8;
  --accent-blue-light: #3D8EFF;
  --accent-teal: #00BFA6;
  --accent-amber: #F59E0B;
  --accent-red: #EF4444;
  --text-primary: #F0F4FF;
  --text-secondary: #8BA3C7;
  --text-muted: #4A6080;
  --font-ui: 'DM Sans', sans-serif;
  --font-mono: 'DM Mono', monospace;
  --font-heading: 'Space Grotesk', sans-serif;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 4px 24px rgba(0,0,0,0.4);
  --shadow-lg: 0 8px 40px rgba(0,0,0,0.6);
  --transition: all 0.2s ease;
}
.stApp { background-color: var(--bg-primary); font-family: var(--font-ui); }
.stMarkdown, p, li, span { color: var(--text-primary); }
.stMetric {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  transition: var(--transition);
}
.stMetric:hover { background: var(--bg-card-hover); border-color: var(--accent-blue); }
.stMetric label {
  color: var(--text-secondary) !important;
  font-size: 0.75rem !important;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.stMetric [data-testid="metric-value"] {
  font-family: var(--font-mono) !important;
  font-size: 1.8rem !important;
  color: var(--text-primary);
  font-weight: 500;
}
[data-testid="stSidebar"] {
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
}
.stButton button {
  background: var(--accent-blue);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-family: var(--font-ui);
  font-weight: 600;
  padding: 10px 20px;
  transition: var(--transition);
  cursor: pointer;
}
.stButton button:hover {
  background: var(--accent-blue-light);
  transform: translateY(-1px);
  box-shadow: var(--shadow);
}
.stSelectbox, .stMultiSelect { border-radius: var(--radius-sm); }
.stDataFrame { border: 1px solid var(--border); border-radius: var(--radius); }
.stExpander {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.stTabs [data-baseweb="tab-list"] {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  gap: 4px;
  padding: 0 24px;
}
.stTabs [data-baseweb="tab"] {
  font-family: var(--font-ui);
  font-weight: 500;
  color: var(--text-secondary);
  padding: 14px 20px;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  transition: var(--transition);
}
.stTabs [aria-selected="true"] {
  color: var(--accent-blue) !important;
  border-bottom: 2px solid var(--accent-blue);
  background: var(--bg-card);
}
div[data-testid="stHorizontalBlock"] { gap: 16px; }
.stAlert { border-radius: var(--radius); border-left-width: 4px; }
.hei-eyebrow {
  color: var(--text-muted);
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  font-family: var(--font-ui);
  text-transform: uppercase;
  margin-bottom: 4px;
}
.hei-title {
  font-family: var(--font-heading);
  font-size: 2rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.1;
  margin: 0;
}
.hei-subtitle {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin-top: 4px;
}
.hei-pill {
  display: inline-block;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  margin-right: 6px;
}
.hei-rule { border-top: 1px solid var(--border); margin: 16px 0 24px 0; }
.hei-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  border-left: 4px solid var(--accent-blue);
  margin-bottom: 12px;
}
.hei-card.risk { border-left-color: var(--accent-red); }
.hei-card.good { border-left-color: var(--accent-teal); }
.hei-card.warning { border-left-color: var(--accent-amber); }
.hei-card-label {
  text-transform: uppercase;
  font-size: 0.7rem;
  color: var(--text-muted);
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}
.hei-card-value {
  font-size: 1.6rem;
  font-family: var(--font-mono);
  color: var(--text-primary);
  font-weight: 500;
}
.hei-card-delta {
  font-size: 0.8rem;
  margin-top: 4px;
  color: var(--text-secondary);
}
.hei-intro {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent-teal);
  border-radius: var(--radius);
  padding: 16px 20px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}
.hei-sb-section {
  color: var(--text-muted);
  font-size: 0.65rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin: 16px 0 8px 0;
}
.hei-sb-empty {
  color: var(--text-muted);
  font-size: 0.8rem;
  font-style: italic;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
  margin-bottom: 8px;
}
.hei-sb-state-name {
  font-family: var(--font-heading);
  font-size: 18px;
  color: var(--text-primary);
  font-weight: 600;
}
.hei-sb-tier {
  display: inline-block;
  font-size: 0.75rem;
  padding: 2px 10px;
  border-radius: 999px;
  margin-left: 8px;
  font-family: var(--font-ui);
}
.hei-sb-cell-label {
  color: var(--text-muted);
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 2px;
}
.hei-sb-cell-value {
  font-family: var(--font-mono);
  font-size: 1rem;
  font-weight: 500;
}
.hei-sb-foot {
  color: var(--text-muted);
  font-size: 0.65rem;
  text-align: center;
  margin-top: 24px;
}
/* Vertical-menu styling for st.radio (used in the Explore tab nav) */
.stRadio > div { flex-direction: column; gap: 2px; }
.stRadio > div > label {
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  color: var(--text-secondary);
}
.stRadio > div > label:hover {
  background: var(--bg-card);
  color: var(--text-primary);
}
.stRadio [data-testid="stMarkdownContainer"] p { font-size: 0.85rem; }
div[role="radiogroup"] > label > div:first-child { display: none; }
</style>
""",
    unsafe_allow_html=True,
)


# ======================================================================
# Plotly theming helpers
# ======================================================================
PRIMARY_COLORS = ["#1B6FE8", "#00BFA6", "#F59E0B", "#EF4444",
                  "#8B5CF6", "#EC4899", "#3D8EFF", "#34D399"]
RISK_COLORSCALE = [[0, "#00BFA6"], [0.33, "#F59E0B"],
                   [0.66, "#EF4444"], [1.0, "#7F1D1D"]]


def apply_dark_theme(fig: go.Figure, title: str | None = None) -> go.Figure:
    """Apply the global dark theme to a Plotly figure."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,27,46,0.8)",
        font=dict(family="DM Sans", color="#8BA3C7", size=12),
        title=dict(
            text=title if title else "",
            font=dict(family="Space Grotesk", color="#F0F4FF", size=16),
        ),
        xaxis=dict(gridcolor="#1E3A5F", linecolor="#1E3A5F",
                   tickfont=dict(family="DM Mono")),
        yaxis=dict(gridcolor="#1E3A5F", linecolor="#1E3A5F",
                   tickfont=dict(family="DM Mono")),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#8BA3C7")),
        margin=dict(t=60, b=40, l=20, r=20),
        hoverlabel=dict(bgcolor="#111F35",
                        font=dict(family="DM Sans", color="#F0F4FF"),
                        bordercolor="#1E3A5F"),
    )
    return fig


def render_metric_card(label: str, value: str, delta: str | None = None,
                       color: str = "default") -> None:
    """Render a styled metric card via st.markdown HTML."""
    delta_html = f'<div class="hei-card-delta">{delta}</div>' if delta else ""
    css_class = "hei-card" + (f" {color}" if color != "default" else "")
    html = (
        f'<div class="{css_class}">'
        f'<div class="hei-card-label">{label}</div>'
        f'<div class="hei-card-value">{value}</div>'
        f'{delta_html}'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ======================================================================
# State-profile cached lookups
# ======================================================================
US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
]
STATE_NAME_TO_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


@st.cache_data(show_spinner=False)
def _state_risk_lookup() -> pd.DataFrame:
    df = pd.read_csv("data/state_risk_index.csv")
    return df


@st.cache_data(show_spinner=False)
def _state_medicare_pp() -> dict[str, float]:
    """Std payment per beneficiary by state, latest year, all-age."""
    try:
        df = pd.read_csv(
            "data/geo_variation_2014_2023.csv",
            usecols=["YEAR", "BENE_GEO_LVL", "BENE_GEO_DESC", "BENE_AGE_LVL",
                     "TOT_MDCR_STDZD_PYMT_PC"],
            low_memory=False,
        )
        df = df[(df["YEAR"] == df["YEAR"].max())
                & (df["BENE_GEO_LVL"] == "State") & (df["BENE_AGE_LVL"] == "All")]
        df["TOT_MDCR_STDZD_PYMT_PC"] = pd.to_numeric(df["TOT_MDCR_STDZD_PYMT_PC"], errors="coerce")
        return dict(zip(df["BENE_GEO_DESC"], df["TOT_MDCR_STDZD_PYMT_PC"]))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_uninsured() -> dict[str, float]:
    try:
        df = pd.read_csv("data/census_sahie.csv")
        df = df[(df["IPRCAT"] == 0) & (df["AGECAT"] == 0)
                & (df["SEXCAT"] == 0) & (df["RACECAT"] == 0)]
        df = df[df["time"] == df["time"].max()]
        return dict(zip(df["NAME"], pd.to_numeric(df["PCTUI_PT"], errors="coerce")))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_phys_per_100k() -> dict[str, float]:
    try:
        df = pd.read_csv(
            "data/ahrf_state_national_2025.csv",
            usecols=["st_abbrev", "phys_wkforc_23", "popn_pums_23"],
            low_memory=False,
        )
        df = df[df["st_abbrev"] != "US"].copy()
        df["phys_wkforc_23"] = pd.to_numeric(df["phys_wkforc_23"], errors="coerce")
        df["popn_pums_23"] = pd.to_numeric(df["popn_pums_23"], errors="coerce")
        df["per100k"] = df["phys_wkforc_23"] / df["popn_pums_23"] * 1e5
        return dict(zip(df["st_abbrev"], df["per100k"]))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_mrsa_sir() -> dict[str, float]:
    try:
        df = pd.read_csv("data/cdc_hai.csv")
        df = df[df["infection_type"].str.contains("MRSA", case=False, na=False)]
        df["sir"] = pd.to_numeric(df["sir"], errors="coerce")
        return dict(zip(df["state"], df["sir"]))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_ed_wait() -> dict[str, float]:
    try:
        df = pd.read_csv("data/cms_timely_care.csv", low_memory=False)
        df = df[df["Measure ID"] == "OP_18b"].copy()
        df["Score"] = pd.to_numeric(df["Score"], errors="coerce")
        return dict(zip(df["State"], df["Score"]))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_unemployment() -> dict[str, float]:
    try:
        df = pd.read_csv("data/bls_unemployment.csv")
        df["unemployment_rate"] = pd.to_numeric(df["unemployment_rate"], errors="coerce")
        df = df.dropna(subset=["unemployment_rate"])
        # Latest (year, month) per state
        df = df.sort_values(["state", "year", "month"]).groupby("state").tail(1)
        return dict(zip(df["state"], df["unemployment_rate"]))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_hiv_rate() -> dict[str, float]:
    try:
        df = pd.read_csv("data/cdc_hiv.csv", low_memory=False,
                         usecols=["year", "state", "newdx_state_rate_per_100k"])
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
        df = df[df["year"] == df["year"].max()]
        df["rate"] = pd.to_numeric(df["newdx_state_rate_per_100k"], errors="coerce")
        return dict(zip(df["state"], df["rate"]))
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _state_cancer_incidence() -> dict[str, float]:
    try:
        df = pd.read_csv("data/nci_cancer.csv", sep="|", low_memory=False,
                         usecols=["AREA", "YEAR", "SITE", "RACE", "SEX",
                                  "EVENT_TYPE", "AGE_ADJUSTED_RATE"])
        df["YEAR"] = pd.to_numeric(df["YEAR"], errors="coerce")
        df["AGE_ADJUSTED_RATE"] = pd.to_numeric(df["AGE_ADJUSTED_RATE"], errors="coerce")
        df = df[(df["SITE"] == "All Cancer Sites Combined")
                & (df["SEX"] == "Male and Female") & (df["RACE"] == "All Races")
                & (df["EVENT_TYPE"] == "Incidence")]
        df = df.dropna(subset=["AGE_ADJUSTED_RATE", "YEAR"])
        df = df[df["YEAR"] == df["YEAR"].max()]
        return dict(zip(df["AREA"], df["AGE_ADJUSTED_RATE"]))
    except Exception:
        return {}


def _quartile_color(value: float | None, all_values: list[float],
                    lower_is_better: bool = False) -> str:
    """Color a value relative to the distribution: teal/amber/red."""
    if value is None or pd.isna(value):
        return "var(--text-muted)"
    nums = [v for v in all_values if v is not None and not pd.isna(v)]
    if not nums:
        return "var(--text-primary)"
    q1 = pd.Series(nums).quantile(0.25)
    q3 = pd.Series(nums).quantile(0.75)
    if lower_is_better:
        if value <= q1:
            return "var(--accent-teal)"
        if value >= q3:
            return "var(--accent-red)"
    else:  # higher is better
        if value >= q3:
            return "var(--accent-teal)"
        if value <= q1:
            return "var(--accent-red)"
    return "var(--accent-amber)"


# ======================================================================
# STEP 2 — Header
# ======================================================================
header_left, header_right = st.columns([3, 2])
with header_left:
    st.markdown(
        """
        <div class="hei-eyebrow">U.S. HEALTHCARE INTELLIGENCE PLATFORM</div>
        <h1 class="hei-title">Healthcare Intelligence</h1>
        <div class="hei-subtitle">81 federal datasets · AI-powered analysis · Updated through 2026</div>
        """,
        unsafe_allow_html=True,
    )
with header_right:
    st.markdown(
        """
        <div style="text-align: right; margin-top: 24px;">
          <span class="hei-pill">81 datasets</span>
          <span class="hei-pill">7.4M rows</span>
          <span class="hei-pill">23 agencies</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
st.markdown('<div class="hei-rule"></div>', unsafe_allow_html=True)


# ======================================================================
# Data loads (Part D / Part B for Enhanced Views)
# ======================================================================
with st.spinner("Loading Medicare Part D data..."):
    df = fetch_part_d_data()
df["Tot_Spndng"] = pd.to_numeric(df["Tot_Spndng"], errors="coerce")
df["Tot_Benes"] = pd.to_numeric(df["Tot_Benes"], errors="coerce")
df["Avg_Spnd_Per_Bene"] = pd.to_numeric(df["Avg_Spnd_Per_Bene"], errors="coerce")
df = df.dropna(subset=["Tot_Spndng"])


# ======================================================================
# STEP 3 — Sidebar (filters + state profile)
# ======================================================================
with st.sidebar:
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;margin-top:4px;">'
        '<span style="font-size:1.2rem;">🏥</span>'
        '<span style="font-family:Space Grotesk;font-size:0.9rem;font-weight:600;color:var(--text-primary);">HEI Platform</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="hei-rule" style="margin:12px 0;"></div>', unsafe_allow_html=True)

    st.markdown('<div class="hei-sb-section">FILTERS</div>', unsafe_allow_html=True)
    selected_state = st.selectbox(
        "State",
        ["— None —"] + US_STATES,
        index=0,
        key="global_state",
    )
    state_filter = None if selected_state == "— None —" else selected_state
    st.caption(
        "📅 Data shown at latest available year per dataset · "
        "Full year filtering coming with Supabase integration"
    )

    st.markdown('<div class="hei-sb-section">STATE PROFILE</div>', unsafe_allow_html=True)

    if state_filter is None:
        st.markdown(
            '<div class="hei-sb-empty">← Select a state above to see its '
            "health intelligence profile</div>",
            unsafe_allow_html=True,
        )
    else:
        risk_df = _state_risk_lookup()
        risk_row = risk_df[risk_df["state"] == state_filter]
        if not risk_row.empty:
            row = risk_row.iloc[0]
            tier = row["risk_tier"]
            tier_emoji = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(tier, "")
            tier_color = {
                "High": "var(--accent-red)",
                "Medium": "var(--accent-amber)",
                "Low": "var(--accent-teal)",
            }.get(tier, "var(--text-secondary)")
            st.markdown(
                f'<div class="hei-sb-state-name">{state_filter}'
                f'<span class="hei-sb-tier" '
                f'style="background:rgba(255,255,255,0.05);color:{tier_color};">'
                f'{tier_emoji} {tier}</span></div>'
                f'<div style="color:var(--text-secondary);font-size:0.8rem;margin:4px 0 12px 0;font-family:var(--font-mono);">'
                f'Risk score {row["risk_score"]:.1f} · #{int(row["risk_rank"])} of 51</div>',
                unsafe_allow_html=True,
            )

        # Pull metric values
        abbr = STATE_NAME_TO_ABBR.get(state_filter)
        unins = _state_uninsured().get(state_filter)
        med_pp = _state_medicare_pp().get(abbr) if abbr else None
        mrsa = _state_mrsa_sir().get(state_filter)
        ed_wait = _state_ed_wait().get(abbr) if abbr else None
        phys_per = _state_phys_per_100k().get(abbr) if abbr else None
        # bls_unemployment.csv keys by 2-letter abbrev (AK, AL, …) — translate
        unemp = _state_unemployment().get(abbr) if abbr else None
        hiv = _state_hiv_rate().get(state_filter)
        # Cancer table sometimes uses "District of Columbia" or "Washington DC"
        cancer = _state_cancer_incidence().get(state_filter) or \
                 _state_cancer_incidence().get("Washington DC" if state_filter == "District of Columbia" else state_filter)

        # Distributions for color-coding
        unins_dist = list(_state_uninsured().values())
        med_dist = list(_state_medicare_pp().values())
        mrsa_dist = list(_state_mrsa_sir().values())
        edw_dist = list(_state_ed_wait().values())
        phys_dist = list(_state_phys_per_100k().values())
        unemp_dist = list(_state_unemployment().values())
        hiv_dist = list(_state_hiv_rate().values())
        cancer_dist = list(_state_cancer_incidence().values())

        def _cell(label: str, value: float | None, fmt: str,
                  dist: list[float], lower_is_better: bool) -> str:
            color = _quartile_color(value, dist, lower_is_better)
            disp = "—" if value is None or pd.isna(value) else fmt.format(value)
            return (
                f'<div class="hei-sb-cell-label">{label}</div>'
                f'<div class="hei-sb-cell-value" style="color:{color};">{disp}</div>'
            )

        # 4 rows × 2 cols using markdown HTML
        rows = [
            (
                _cell("Uninsured %", unins, "{:.1f}%", unins_dist, True),
                _cell("Medicare $/bene", med_pp, "${:,.0f}", med_dist, True),
            ),
            (
                _cell("MRSA SIR", mrsa, "{:.2f}", mrsa_dist, True),
                _cell("ED Wait (min)", ed_wait, "{:.0f}", edw_dist, True),
            ),
            (
                _cell("MDs / 100k", phys_per, "{:.0f}", phys_dist, False),
                _cell("Unemployment %", unemp, "{:.1f}%", unemp_dist, True),
            ),
            (
                _cell("HIV / 100k", hiv, "{:.1f}", hiv_dist, True),
                _cell("Cancer / 100k", cancer, "{:.0f}", cancer_dist, True),
            ),
        ]
        for left, right in rows:
            c1, c2 = st.columns(2)
            c1.markdown(left, unsafe_allow_html=True)
            c2.markdown(right, unsafe_allow_html=True)

    st.markdown('<div class="hei-rule" style="margin:24px 0 8px 0;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hei-sb-foot">Not for clinical use · Public data only</div>',
        unsafe_allow_html=True,
    )


# ======================================================================
# STEP 4/5/9 — Tab declaration + Explore renderer infrastructure
# ======================================================================
# Year dropdown was removed from the sidebar — default to the latest Part D
# year so the Enhanced View (top 10, GLP-1, comparison tool) still has a
# sensible time slice. Each summarizer otherwise loads its own latest year.
selected_year = max(df["Year"].unique())
filtered = df[df["Year"] == selected_year]

LOWER_IS_BETTER = {
    "sir": True, "readmission": True, "uninsured": True, "unemployment": True,
    "wait": True, "od_deaths": True, "poverty": True, "shortage": True,
    "mortality": True, "physicians": False, "rn_per": False, "beds": False,
    "vaccination": False,
}

# Aggregate / non-state row labels that appear inside state columns of several
# federal datasets. Filtering these out keeps per-state bar charts and Top-N
# rankings honest (the US row is ~10× any state and dominates the y-axis;
# summing-with-US double-counts KPI totals).
NON_STATE_ROWS = {
    "United States", "UNITED STATES", "U.S. Territories", "US",
    "National", "NATIONAL",
}


def filter_states_only(df: pd.DataFrame, col: str | None = None) -> pd.DataFrame:
    """Return df with US-aggregate / non-state rows removed.

    `col` defaults to whatever `_detect_state_col` finds; pass an explicit name
    if the caller already knows it.
    """
    if df is None or df.empty:
        return df
    if col is None:
        col = _detect_state_col(df)
    if not col or col not in df.columns:
        return df
    return df[~df[col].astype(str).isin(NON_STATE_ROWS)]


def _is_lower_better(col: str) -> bool:
    """Best-effort lookup against LOWER_IS_BETTER patterns."""
    lc = col.lower()
    for pat, val in LOWER_IS_BETTER.items():
        if pat in lc:
            return val
    return True  # default for unknown metrics — assume "high = bad"


def _clean_label(col: str) -> str:
    return col.replace("_", " ").replace(".", " ").title()


def _detect_state_col(df_in: pd.DataFrame) -> str | None:
    """Find the column that holds state names/codes."""
    candidates = [
        "state", "State", "state_name", "state_abbr", "BENE_GEO_DESC",
        "AREA", "locationabbr", "locationdesc", "reporting_area",
        "State Abbreviation", "State Name", "state_territory",
        "st_abbrev", "NAME", "ACO_State",
    ]
    for c in candidates:
        if c in df_in.columns:
            return c
    return None


def _detect_year_col(df_in: pd.DataFrame) -> str | None:
    candidates = ["year", "Year", "YEAR", "fiscal_year", "yearstart", "period"]
    for c in candidates:
        if c in df_in.columns:
            return c
    return None


def _detect_primary_numeric(df_in: pd.DataFrame) -> str | None:
    """Pick the first numeric column that isn't an identifier or denominator.

    Skips id-ish (fips, state_fips, code, id, rank, _ci), time (year, month, week),
    and denominator-ish (population, count) columns — these aren't the metric of
    interest for the distribution chart or top/bottom tables.
    """
    skip_exact = {"population", "year", "month", "fips", "state_fips",
                  "count", "week", "rank", "risk_rank", "year_start", "year_end"}
    skip_patterns = ["fips", "rank", "id", "code", "week", "month", "_ci",
                     "_lower", "_upper", "population", "count"]
    for c in df_in.columns:
        if not pd.api.types.is_numeric_dtype(df_in[c]):
            continue
        lc = c.lower()
        if lc in skip_exact:
            continue
        if any(p in lc for p in skip_patterns):
            continue
        return c
    return None


# Chart-type overrides per dataset
CHART_OVERRIDES: dict[str, str] = {
    "cdc_hai": "heatmap",
    "cdc_wastewater": "multiline",
    "brfss_state_prevalence": "grouped_bar",
    "cdc_nndss": "grouped_bar",
    "cdc_alzheimers": "grouped_bar",
    "samhsa_nmhss": "grouped_bar",
}


def render_chart_for_dataset(key: str, df_in: pd.DataFrame, primary_col: str,
                             state_filter: str | None) -> None:
    """Dispatch to the right chart type per dataset."""
    chart_type = CHART_OVERRIDES.get(key, "bar")
    state_col = _detect_state_col(df_in)

    try:
        if chart_type == "heatmap":
            numeric = df_in.select_dtypes(include="number")
            if state_col and not numeric.empty:
                pivot_cols = [c for c in numeric.columns if not c.lower().endswith(("_ci", "_lower", "_upper"))][:8]
                if pivot_cols:
                    fig = px.imshow(
                        df_in.set_index(state_col)[pivot_cols],
                        color_continuous_scale=RISK_COLORSCALE,
                        aspect="auto",
                    )
                    apply_dark_theme(fig)
                    fig.update_layout(height=600)
                    st.plotly_chart(fig, use_container_width=True)
                    return
        elif chart_type == "multiline":
            numeric_cols = [c for c in df_in.select_dtypes(include="number").columns
                            if not c.lower().endswith(("_ci", "_lower", "_upper"))][:6]
            x_col = _detect_year_col(df_in) or numeric_cols[0] if numeric_cols else None
            if x_col and numeric_cols:
                ycols = [c for c in numeric_cols if c != x_col]
                fig = px.line(df_in, x=x_col, y=ycols,
                              color_discrete_sequence=PRIMARY_COLORS)
                apply_dark_theme(fig)
                st.plotly_chart(fig, use_container_width=True)
                return
        elif chart_type == "grouped_bar":
            numeric_cols = [c for c in df_in.select_dtypes(include="number").columns
                            if not c.lower().endswith(("_ci", "_lower", "_upper"))][:5]
            if state_col and numeric_cols:
                long_df = df_in.melt(id_vars=[state_col], value_vars=numeric_cols,
                                     var_name="metric", value_name="value")
                fig = px.bar(long_df, x=state_col, y="value", color="metric",
                             barmode="group",
                             color_discrete_sequence=PRIMARY_COLORS)
                apply_dark_theme(fig)
                fig.update_layout(height=500)
                st.plotly_chart(fig, use_container_width=True)
                return
    except Exception:
        pass  # fall through to default

    # Default: sorted bar chart, color by value
    if state_col and primary_col:
        data = df_in[[state_col, primary_col]].dropna().copy()
        data = data.sort_values(primary_col, ascending=False)
        bar_colors = [
            "#3D8EFF" if state_filter and r == state_filter else "#1B6FE8"
            for r in data[state_col]
        ]
        fig = go.Figure(go.Bar(
            x=data[state_col], y=data[primary_col],
            marker=dict(color=bar_colors),
        ))
        mean_val = data[primary_col].mean()
        fig.add_hline(y=mean_val, line_dash="dash", line_color="#F59E0B",
                      annotation_text=f"Mean {mean_val:.2f}", annotation_position="top right",
                      annotation_font_color="#F59E0B")
        if state_filter and state_filter in data[state_col].values:
            v = data.loc[data[state_col] == state_filter, primary_col].iloc[0]
            fig.add_annotation(
                x=state_filter, y=v,
                text=f"<b>{state_filter}</b>", showarrow=True, arrowhead=2,
                arrowcolor="#3D8EFF", font=dict(color="#3D8EFF"),
            )
        apply_dark_theme(fig, title=_clean_label(primary_col))
        fig.update_layout(xaxis=dict(tickangle=-45), height=500)
        st.plotly_chart(fig, use_container_width=True)


def render_dataset_view(dataset_key: str, state_filter: str | None,
                        year_filter=None) -> None:
    """Dynamic view of any dataset registered in SUMMARIZERS.

    Note: year_filter is currently a no-op — each summarizer loads its own
    latest year. The parameter is preserved for forward-compatibility once
    Supabase-backed datasets support arbitrary year filtering.
    """
    fn = SUMMARIZERS.get(dataset_key)
    if fn is None:
        st.info(
            f"No generic summarizer for `{dataset_key}` — see the Enhanced "
            "View above for this dataset."
        )
        return
    try:
        result = fn()
    except Exception as e:
        st.error(f"Failed to load {dataset_key}: {e}")
        return
    if result is None:
        st.info(f"No data returned by `{dataset_key}` summarizer.")
        return
    header, csv_text = result
    try:
        data = pd.read_csv(StringIO(csv_text))
    except Exception as e:
        st.error(f"Failed to parse {dataset_key} CSV: {e}")
        return

    # Split the US-aggregate row off so it never lands in state-comparison
    # charts or rankings. `data` stays unfiltered (used by the Raw data table
    # so the US row is still visible to users who want it). The "U.S.
    # Territories" row is excluded from states_data but is NOT a national
    # total — only true US-aggregate labels feed the Total KPI.
    state_col = _detect_state_col(data)
    states_data = filter_states_only(data, state_col) if state_col else data
    _us_aggregate_labels = {"United States", "UNITED STATES", "US",
                            "National", "NATIONAL"}
    us_row = (data[data[state_col].astype(str).isin(_us_aggregate_labels)]
              if state_col and state_col in data.columns else pd.DataFrame())

    # A) Key metrics row — pull totals from the US row when the dataset
    # carries one; otherwise sum the per-state rows. Rate-like columns always
    # use a state-level mean (a US-row "rate" is already a national average,
    # but mixing it into a mean-of-states would weight the nation as one
    # extra state).
    numeric_cols = [c for c in data.select_dtypes(include="number").columns
                    if not c.lower().endswith(("_ci", "_lower", "_upper"))
                    and c.lower() not in ("year", "fips", "month", "week",
                                           "rank", "risk_rank", "year_start", "year_end")]
    if numeric_cols:
        cols = st.columns(min(4, len(numeric_cols)))
        for i, col_name in enumerate(numeric_cols[:4]):
            try:
                is_rate = any(p in col_name.lower() for p in (
                    "rate", "pct", "percent", "score", "sir", "ratio"))
                if is_rate:
                    series = states_data[col_name].dropna()
                    if series.empty:
                        continue
                    val = series.mean()
                    suffix = " avg"
                else:
                    if not us_row.empty and col_name in us_row.columns:
                        us_series = us_row[col_name].dropna()
                        if us_series.empty:
                            continue
                        val = us_series.iloc[0] if len(us_series) == 1 else us_series.sum()
                    else:
                        series = states_data[col_name].dropna()
                        if series.empty:
                            continue
                        val = series.sum()
                    suffix = " total"
                if abs(val) >= 1e9:
                    disp = f"{val/1e9:.1f}B"
                elif abs(val) >= 1e6:
                    disp = f"{val/1e6:.1f}M"
                elif abs(val) >= 1e3:
                    disp = f"{val:,.0f}"
                else:
                    disp = f"{val:,.2f}"
                cols[i].metric(_clean_label(col_name) + suffix, disp)
            except Exception:
                continue

    primary = _detect_primary_numeric(data)

    # B) Top / Bottom 10 — states only.
    if state_col and primary:
        try:
            grouped = (states_data.groupby(state_col, as_index=False)[primary].mean()
                          .dropna(subset=[primary]))
            lib = _is_lower_better(primary)
            t1, t2 = st.columns(2)
            with t1:
                top_label = "Top 10 States (worst)" if lib else "Top 10 States (best)"
                st.markdown(f"**{top_label}**")
                top10 = grouped.nlargest(10, primary)
                st.dataframe(top10, use_container_width=True, hide_index=True)
            with t2:
                bot_label = "Bottom 10 States (best)" if lib else "Bottom 10 States (worst)"
                st.markdown(f"**{bot_label}**")
                bot10 = grouped.nsmallest(10, primary)
                st.dataframe(bot10, use_container_width=True, hide_index=True)
        except Exception:
            pass

    # C/D) Distribution chart with state highlight — states only.
    if state_col and primary:
        try:
            grouped = states_data.groupby(state_col, as_index=False)[primary].mean()
            render_chart_for_dataset(dataset_key, grouped, primary, state_filter)
        except Exception:
            try:
                render_chart_for_dataset(dataset_key, states_data, primary, state_filter)
            except Exception:
                pass

    # E) Trend chart if year column present
    year_col = _detect_year_col(data)
    if year_col and primary and data[year_col].nunique() >= 3:
        try:
            if state_filter and state_col:
                trend = data[data[state_col] == state_filter].groupby(year_col, as_index=False)[primary].mean()
                trend_title = f"{state_filter} — {_clean_label(primary)} over time"
            else:
                trend = data.groupby(year_col, as_index=False)[primary].mean()
                trend_title = f"National avg {_clean_label(primary)} over time"
            if not trend.empty:
                fig_t = px.line(trend, x=year_col, y=primary, markers=True,
                                color_discrete_sequence=["#1B6FE8"])
                apply_dark_theme(fig_t, title=trend_title)
                st.plotly_chart(fig_t, use_container_width=True)
        except Exception:
            pass

    # F) Raw data expander + download
    with st.expander("📋 Raw data", expanded=False):
        st.dataframe(data, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download as CSV",
            data=data.to_csv(index=False).encode("utf-8"),
            file_name=f"{dataset_key}.csv",
            mime="text/csv",
            key=f"dl_{dataset_key}",
        )

    # Source caption
    info = DATASET_DISPLAY.get(dataset_key)
    if info:
        st.caption(f"Data source: {info[0]} · {info[1]} · Coverage: {info[2]}")


# ======================================================================
# Tabs
# ======================================================================
# Display order puts the demo headline view second; the tabN variable
# names stay bound to their existing `with tabN:` blocks below (tab2 is
# still AI Analyst, etc.) so nothing downstream needs to change.
tab1, tab_atlas, tab2, tab3, tab4 = st.tabs([
    "🗺️  Risk Map",
    "🩺  CA Workforce Atlas",
    "🧠  AI Analyst",
    "📊  Explore",
    "📚  Sources",
])

with tab_atlas:
    ca_workforce_atlas.render()


# ======================================================================
# TAB 1 — Risk Map (Geography + Compare States)
# ======================================================================
with tab1:
    view = st.radio(
        "View",
        ["🗺️ National Risk Map", "🔍 State Comparator"],
        horizontal=True,
        label_visibility="collapsed",
        key="risk_view",
    )

    if view == "🗺️ National Risk Map":
        st.subheader("🗺️ Medicare Spending by State")
        st.markdown("Medicare Fee-for-Service spending by state, from the CMS Geographic Variation PUF.")

        with st.spinner("Loading Geographic Variation data..."):
            df_geo = load_geo_variation()

        col_yr, col_mode = st.columns([1, 2])
        geo_years = sorted(df_geo["YEAR"].unique().tolist())
        default_idx = geo_years.index(2022) if 2022 in geo_years else len(geo_years) - 1
        geo_year = col_yr.selectbox("Year", geo_years, index=default_idx, key="geo_year")
        view_mode = col_mode.radio(
            "Mode", ["Total Spending", "Per Beneficiary"],
            horizontal=True, key="geo_view_mode",
        )

        NON_STATES = {"PR", "VI", "Territory", "ZZ"}
        state_df = df_geo[
            (df_geo["BENE_GEO_LVL"] == "State")
            & (df_geo["YEAR"] == geo_year)
            & (df_geo["BENE_AGE_LVL"] == "All")
            & (~df_geo["BENE_GEO_DESC"].isin(NON_STATES))
        ].copy()
        state_df["TOT_MDCR_PYMT_AMT"] = pd.to_numeric(state_df["TOT_MDCR_PYMT_AMT"], errors="coerce")
        state_df["TOT_MDCR_PYMT_PC"] = pd.to_numeric(state_df["TOT_MDCR_PYMT_PC"], errors="coerce")
        state_df["Spending_B"] = (state_df["TOT_MDCR_PYMT_AMT"] / 1e9).round(2)

        if view_mode == "Total Spending":
            metric_col, metric_label = "Spending_B", "Spending ($B)"
        else:
            metric_col, metric_label = "TOT_MDCR_PYMT_PC", "Spending per Beneficiary ($)"

        # Risk choropleth (uses state risk index, not Medicare spending)
        df_risk = pd.read_csv("data/state_risk_index.csv")
        fig_map = px.choropleth(
            df_risk,
            locations="state_abbr",
            locationmode="USA-states",
            color="risk_score",
            scope="usa",
            color_continuous_scale=RISK_COLORSCALE,
            range_color=(0, 100),
            labels={"risk_score": "Risk"},
            hover_name="state",
            hover_data={
                "risk_score": ":.1f", "risk_tier": True,
                "dim_spending": ":.1f", "dim_supply": ":.1f",
                "dim_shortage": ":.1f", "dim_disease": ":.1f",
                "dim_insurance": ":.1f", "dim_hospital_quality": ":.1f",
                "dim_poverty": ":.1f", "state_abbr": False,
            },
        )
        fig_map.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            geo=dict(
                bgcolor="#080F1A",
                landcolor="#0D1B2E",
                lakecolor="#080F1A",
                countrycolor="#1E3A5F",
                coastlinecolor="#1E3A5F",
                projection_type="albers usa",
            ),
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            font=dict(family="DM Sans", color="#8BA3C7"),
            annotations=[dict(
                text="Risk Score: Higher = Worse outcomes",
                x=0.99, y=0.02, xref="paper", yref="paper",
                showarrow=False,
                font=dict(size=10, color="#4A6080", family="DM Sans"),
                xanchor="right",
            )],
        )
        st.plotly_chart(fig_map, use_container_width=True)

        # KPIs
        col_g1, col_g2, col_g3 = st.columns(3)
        if view_mode == "Total Spending":
            col_g1.metric("Total FFS Spending", f"${state_df['TOT_MDCR_PYMT_AMT'].sum()/1e9:.1f}B")
            top_state = state_df.loc[state_df["TOT_MDCR_PYMT_AMT"].idxmax()]
            bot_state = state_df.loc[state_df["TOT_MDCR_PYMT_AMT"].idxmin()]
            col_g2.metric("Highest Spend", top_state["BENE_GEO_DESC"], f"${top_state['Spending_B']:.1f}B")
            col_g3.metric("Lowest Spend", bot_state["BENE_GEO_DESC"], f"${bot_state['Spending_B']:.2f}B")
        else:
            col_g1.metric("National Avg / Bene", f"${state_df['TOT_MDCR_PYMT_PC'].mean():,.0f}")
            top_state = state_df.loc[state_df["TOT_MDCR_PYMT_PC"].idxmax()]
            bot_state = state_df.loc[state_df["TOT_MDCR_PYMT_PC"].idxmin()]
            col_g2.metric("Highest / Bene", top_state["BENE_GEO_DESC"], f"${top_state['TOT_MDCR_PYMT_PC']:,.0f}")
            col_g3.metric("Lowest / Bene", bot_state["BENE_GEO_DESC"], f"${bot_state['TOT_MDCR_PYMT_PC']:,.0f}")

        st.divider()

        st.subheader("🎯 State Risk Index")
        st.markdown("Composite healthcare risk score across 7 dimensions, percentile-ranked 0–100. Higher = greater risk.")

        col_r1, col_r2, col_r3 = st.columns(3)
        highest = df_risk.iloc[df_risk["risk_score"].idxmax()]
        lowest = df_risk.iloc[df_risk["risk_score"].idxmin()]
        col_r1.metric("Highest Risk", highest["state"], f"{highest['risk_score']:.1f}")
        col_r2.metric("Lowest Risk", lowest["state"], f"{lowest['risk_score']:.1f}")
        col_r3.metric("National Avg", f"{df_risk['risk_score'].mean():.1f}")

        tier_colors = {"High": "#EF4444", "Medium": "#F59E0B", "Low": "#00BFA6"}
        df_risk_sorted = df_risk.sort_values("risk_score", ascending=True).copy()
        df_risk_sorted["risk_score_display"] = df_risk_sorted["risk_score"].round(1)
        fig_risk = px.bar(
            df_risk_sorted, x="risk_score", y="state_abbr", orientation="h",
            color="risk_tier", color_discrete_map=tier_colors,
            category_orders={
                "state_abbr": df_risk_sorted["state_abbr"].tolist(),
                "risk_tier": ["High", "Medium", "Low"],
            },
            labels={"risk_score": "Risk Score (0–100)", "state_abbr": "State"},
            hover_name="state",
            hover_data={"risk_score_display": ":.1f", "risk_rank": True,
                        "risk_tier": True, "state_abbr": False, "risk_score": False},
            text="risk_score_display",
        )
        fig_risk.update_traces(texttemplate="%{text:.1f}", textposition="outside")
        apply_dark_theme(fig_risk)
        fig_risk.update_layout(height=950)
        st.plotly_chart(fig_risk, use_container_width=True)

        table_df = df_risk[[
            "state", "state_abbr",
            "dim_spending", "dim_supply", "dim_shortage", "dim_disease",
            "dim_insurance", "dim_hospital_quality", "dim_poverty",
            "risk_score", "risk_rank", "risk_tier",
        ]].copy()
        table_df.columns = [
            "State", "Abbr", "Spending", "Supply", "Shortage", "Disease",
            "Insurance", "Hosp. Quality", "Poverty", "Risk Score", "Rank", "Tier",
        ]
        for c in ["Spending", "Supply", "Shortage", "Disease",
                  "Insurance", "Hosp. Quality", "Poverty", "Risk Score"]:
            table_df[c] = table_df[c].round(1)
        table_df_sorted = table_df.sort_values("Rank")
        st.dataframe(table_df_sorted, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download State Risk Index as CSV",
            data=table_df_sorted.to_csv(index=False).encode("utf-8"),
            file_name="state_risk_index.csv",
            mime="text/csv",
            key="dl_state_risk_v2",
        )
        st.caption(
            "Methodology: 7 dimensions percentile-ranked 0–100, equal-weighted average. "
            "Higher = worse outcome. Spending · Supply · Shortage · Disease · Insurance · "
            "Hospital Quality · Poverty."
        )

    else:
        # State Comparator
        st.subheader("🔍 Compare States")
        st.markdown("Side-by-side comparison of any two states across the 7 risk dimensions.")

        df_cmp = pd.read_csv("data/state_risk_index.csv")
        state_options = df_cmp.sort_values("state")["state"].tolist()
        DIM_COLS = ["dim_spending", "dim_supply", "dim_shortage", "dim_disease",
                    "dim_insurance", "dim_hospital_quality", "dim_poverty"]
        DIM_LABELS = {
            "dim_spending": "Spending", "dim_supply": "Supply",
            "dim_shortage": "Shortage", "dim_disease": "Disease",
            "dim_insurance": "Insurance",
            "dim_hospital_quality": "Hospital Quality", "dim_poverty": "Poverty",
        }

        col_a, col_b = st.columns(2)
        default_a = state_options.index("Mississippi") if "Mississippi" in state_options else 0
        default_b = state_options.index("Massachusetts") if "Massachusetts" in state_options else 1
        state_a = col_a.selectbox("State A", state_options, index=default_a, key="cmp_a")
        state_b = col_b.selectbox("State B", state_options, index=default_b, key="cmp_b")

        if state_a == state_b:
            st.info("Pick two different states to compare.")
        else:
            row_a = df_cmp[df_cmp["state"] == state_a].iloc[0]
            row_b = df_cmp[df_cmp["state"] == state_b].iloc[0]
            labels = [DIM_LABELS[c] for c in DIM_COLS]
            vals_a = [row_a[c] for c in DIM_COLS]
            vals_b = [row_b[c] for c in DIM_COLS]

            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=vals_a + [vals_a[0]], theta=labels + [labels[0]],
                fill="toself", name=state_a,
                line=dict(color="#EF4444"),
            ))
            fig_radar.add_trace(go.Scatterpolar(
                r=vals_b + [vals_b[0]], theta=labels + [labels[0]],
                fill="toself", name=state_b,
                line=dict(color="#1B6FE8"),
            ))
            fig_radar.update_layout(
                polar=dict(
                    bgcolor="rgba(13,27,46,0.5)",
                    radialaxis=dict(visible=True, range=[0, 100],
                                    gridcolor="#1E3A5F",
                                    tickfont=dict(color="#8BA3C7")),
                    angularaxis=dict(gridcolor="#1E3A5F",
                                     tickfont=dict(color="#F0F4FF")),
                ),
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=True, height=500,
                font=dict(family="DM Sans", color="#8BA3C7"),
                margin={"l": 40, "r": 40, "t": 30, "b": 30},
            )
            st.plotly_chart(fig_radar, use_container_width=True)

            cmp_table = pd.DataFrame({
                "Dimension": labels,
                state_a: [round(v, 1) for v in vals_a],
                state_b: [round(v, 1) for v in vals_b],
                "Difference (A − B)": [round(a - b, 1) for a, b in zip(vals_a, vals_b)],
            })
            composite_row = pd.DataFrame({
                "Dimension": ["Risk Score"],
                state_a: [round(row_a["risk_score"], 1)],
                state_b: [round(row_b["risk_score"], 1)],
                "Difference (A − B)": [round(row_a["risk_score"] - row_b["risk_score"], 1)],
            })
            cmp_table = pd.concat([cmp_table, composite_row], ignore_index=True)
            st.dataframe(cmp_table, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Download Comparison as CSV",
                data=cmp_table.to_csv(index=False).encode("utf-8"),
                file_name=f"compare_{state_a}_vs_{state_b}.csv".replace(" ", "_"),
                mime="text/csv",
                key="dl_cmp_v2",
            )

            THRESHOLD = 5
            worse, better = [], []
            for col, label in zip(DIM_COLS, labels):
                diff = row_a[col] - row_b[col]
                if diff >= THRESHOLD:
                    worse.append(label)
                elif diff <= -THRESHOLD:
                    better.append(label)
            cd = row_a["risk_score"] - row_b["risk_score"]
            if cd > 0:
                head = f"Overall, **{state_a}** has higher healthcare risk than **{state_b}** ({row_a['risk_score']:.1f} vs {row_b['risk_score']:.1f})."
            elif cd < 0:
                head = f"Overall, **{state_a}** has lower healthcare risk than **{state_b}** ({row_a['risk_score']:.1f} vs {row_b['risk_score']:.1f})."
            else:
                head = f"**{state_a}** and **{state_b}** have nearly identical composite risk scores."
            parts = [head]
            if worse:
                parts.append(f"{state_a} scores **worse** on: " + ", ".join(worse) + ".")
            if better:
                parts.append(f"{state_a} scores **better** on: " + ", ".join(better) + ".")
            if not worse and not better:
                parts.append("No dimensions show a meaningful gap (≥5 points).")
            st.markdown(" ".join(parts))


# ======================================================================
# TAB 2 — AI Analyst (preserved verbatim)
# ======================================================================
with tab2:
    st.subheader("🤖 AI Analyst")
    st.markdown(
        "Ask natural-language questions across the 81 federal datasets that power this dashboard. "
        "The analyst reasons over pre-computed summaries (state risk index, Medicare spending, "
        "Medicaid drug spending, workforce density) and returns specific, data-driven insights."
    )

    active = get_active_provider()
    if active is None:
        st.error(
            "No AI provider API key is configured. Add at least one of "
            "`GROQ_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or "
            "`TOGETHER_API_KEY` to `.streamlit/secrets.toml`."
        )
    else:
        st.caption(
            f"Default first provider: **{PROVIDER_LABELS[active]}**. "
            "Size-based routing: small context (<4K chars) goes Groq → GPT-4o mini → Gemini "
            "→ Together; large context skips Groq's TPM cap and goes GPT-4o mini → Gemini → "
            "Together → Groq*. Each query routes to relevant datasets via keyword retrieval."
        )

    EXAMPLE_QUESTIONS = [
        "Which states have the highest disease burden but lowest provider supply?",
        "Where is telehealth adoption growing fastest post-COVID?",
        "Which states show the biggest gap between Medicare spending and health outcomes?",
        "Where are opioid overdose rates rising despite high treatment facility density?",
        "Which states have improved most on uninsured rates over the last decade?",
    ]

    if "ai_question_input" not in st.session_state:
        st.session_state.ai_question_input = ""
    if "ai_history" not in st.session_state:
        st.session_state.ai_history = []

    def _set_question(q: str):
        st.session_state.ai_question_input = q

    st.markdown("**Example questions** (click to populate):")
    btn_cols = st.columns(2)
    for i, eq in enumerate(EXAMPLE_QUESTIONS):
        btn_cols[i % 2].button(
            eq, key=f"ai_example_{i}",
            on_click=_set_question, args=(eq,), use_container_width=True,
        )

    question = st.text_area(
        "Your question", key="ai_question_input", height=80,
        placeholder="Ask anything about the 81 datasets…",
    )
    submit = st.button("🔍 Ask the analyst", type="primary", disabled=(active is None))

    if submit and question.strip():
        with st.spinner("Thinking…"):
            t0 = time.time()
            try:
                response, provider_used, ctx_chars, route_label, datasets_used = query_analyst(question.strip())
                elapsed = time.time() - t0
                st.session_state.ai_history.insert(0, {
                    "q": question.strip(), "a": response,
                    "provider": provider_used, "seconds": elapsed,
                    "ctx_chars": ctx_chars, "route": route_label,
                    "datasets_used": datasets_used,
                })
                st.session_state.ai_history = st.session_state.ai_history[:5]
            except RuntimeError as e:
                st.error(str(e))

    if st.session_state.ai_history:
        latest = st.session_state.ai_history[0]
        st.markdown("### Response")
        with st.container(border=True):
            st.markdown(latest["a"])
        st.caption(
            f"Answered by **{PROVIDER_LABELS.get(latest['provider'], latest['provider'])}** "
            f"in {latest['seconds']:.1f}s · context {latest.get('ctx_chars', 0):,} chars."
        )

        latest_datasets = latest.get("datasets_used", [])
        if latest_datasets:
            with st.expander(
                f"📊 Data sources used ({len(latest_datasets)} datasets)",
                expanded=False,
            ):
                rows = []
                for key in latest_datasets:
                    info = DATASET_DISPLAY.get(key)
                    if info:
                        rows.append({"Dataset": info[0], "Agency": info[1], "Coverage": info[2]})
                    else:
                        rows.append({"Dataset": key, "Agency": "—", "Coverage": "—"})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if len(st.session_state.ai_history) > 1:
            st.divider()
            st.markdown("### Recent questions")
            for i, item in enumerate(st.session_state.ai_history[1:], start=1):
                with st.expander(f"{i}. {item['q']}", expanded=False):
                    st.markdown(item["a"])
                    st.caption(
                        f"{PROVIDER_LABELS.get(item['provider'], item['provider'])} · "
                        f"{item['seconds']:.1f}s · {item.get('ctx_chars', 0):,} chars · "
                        f"{item.get('route', '').split(' · ')[0] if item.get('route') else ''}"
                    )
                    item_datasets = item.get("datasets_used", [])
                    if item_datasets:
                        with st.expander(
                            f"📊 Data sources used ({len(item_datasets)} datasets)",
                            expanded=False,
                        ):
                            rows = []
                            for key in item_datasets:
                                info = DATASET_DISPLAY.get(key)
                                if info:
                                    rows.append({"Dataset": info[0], "Agency": info[1], "Coverage": info[2]})
                                else:
                                    rows.append({"Dataset": key, "Agency": "—", "Coverage": "—"})
                            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ======================================================================
# TAB 3 — Explore (universal renderer + sidebar nav)
# ======================================================================
NAV_STRUCTURE = [
    ("SPENDING", [
        ("💊 Drug Spending (Part D)", "cms_partd"),
        ("🩺 Equipment & Supplies (Part B)", "cms_partb"),
        ("💊 Medicaid Drug", "cms_medicaid_drug"),
        ("💰 Medicare Overview", "geo_variation_2014_2023"),
    ]),
    ("QUALITY", [
        ("🏥 Hospital Compare", "hospital_compare_general_info"),
        ("🦠 Infection Rates (HAI)", "cdc_hai"),
        ("⏱️ ED Wait Times", "cms_timely_care"),
        ("🏨 Skilled Nursing (SNF)", "cms_snf"),
    ]),
    ("DISEASE BURDEN", [
        ("🎗️ Cancer", "nci_cancer"),
        ("🔴 HIV & STI", "cdc_hiv"),
        ("💉 Drug Overdose", "cdc_drug_overdose"),
        ("🧫 Infectious Disease", "cdc_nndss"),
        ("🧠 Alzheimer's & Aging", "cdc_alzheimers"),
        ("🦟 Wastewater Surveillance", "cdc_wastewater"),
    ]),
    ("HEALTH SYSTEM", [
        ("👨‍⚕️ Workforce Supply", "ahrf_state_national_2025"),
        ("📍 Shortage Areas", "hpsa_primary_care"),
        ("🧠 Mental Health Capacity", "samhsa_nmhss"),
        ("👶 Maternal & Child Health", "cdc_maternal_mortality"),
    ]),
    ("ECONOMICS & ACCESS", [
        ("📊 Medicare Spending", "geo_variation_2014_2023"),
        ("🏦 Uninsured Rates", "census_sahie"),
        ("📉 Unemployment", "bls_unemployment"),
        ("🍎 Food & Environment", "usda_food_access"),
    ]),
]


def _render_partd_enhanced(filtered_df: pd.DataFrame, full_df: pd.DataFrame,
                           year_label) -> None:
    """All Part D enhanced views: top 10, GLP-1, comparison, YoY, brand vs generic, expensive, anomalies, manufacturers."""
    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Drugs", f"{filtered_df['Brnd_Name'].nunique():,}")
    c2.metric("Total Spending", f"${filtered_df['Tot_Spndng'].sum()/1e9:.1f}B")
    c3.metric("Total Beneficiaries", f"{filtered_df['Tot_Benes'].sum()/1e6:.1f}M")

    st.divider()
    st.subheader(f"Top 10 Drugs by Total Spending ({year_label})")
    top10 = filtered_df.groupby("Brnd_Name")["Tot_Spndng"].sum().nlargest(10).reset_index()
    top10["Spending_B"] = (top10["Tot_Spndng"] / 1e9).round(1)
    fig = px.bar(top10, x="Spending_B", y="Brnd_Name", orientation="h",
                 color="Spending_B", color_continuous_scale=[[0, "#1B6FE8"], [1, "#3D8EFF"]],
                 text="Spending_B")
    fig.update_traces(texttemplate="%{text}B", textposition="outside")
    apply_dark_theme(fig)
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

    # CMS publishes one Mftr_Name='Overall' aggregate row per (Brnd, Gnrc, Year)
    # plus identical per-manufacturer rows. Filter to 'Overall' to get exactly
    # one row per drug-period without double-counting or arbitrary first-row picks.
    full_overall = full_df[full_df["Mftr_Name"] == "Overall"]

    st.divider()
    st.subheader("🔬 GLP-1 Spotlight — Ozempic & Mounjaro")
    glp1_drugs = ["Ozempic", "Mounjaro", "Trulicity", "Victoza", "Rybelsus", "Wegovy"]
    glp1_df = full_overall[full_overall["Brnd_Name"].isin(glp1_drugs)].copy()
    glp1_df["Spending_B"] = (glp1_df["Tot_Spndng"] / 1e9).round(2)
    if not glp1_df.empty:
        fig2 = px.bar(glp1_df, x="Year", y="Spending_B", color="Brnd_Name",
                      barmode="group", color_discrete_sequence=PRIMARY_COLORS,
                      labels={"Spending_B": "Total Medicare Spending ($B)",
                              "Brnd_Name": "Drug",
                              "Year": "Period"})
        apply_dark_theme(fig2)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No GLP-1 data found.")

    st.divider()
    st.subheader("🔍 Drug Comparison Tool")
    cmp_drugs = sorted(full_overall["Brnd_Name"].dropna().unique().tolist())
    selected_drugs = st.multiselect(
        "Select drugs to compare (pick 2–5)", options=cmp_drugs,
        default=[], max_selections=5, key="partd_cmp_drugs",
    )
    if len(selected_drugs) < 2:
        st.info("Select at least 2 drugs to see the comparison chart.")
    else:
        cmp_long = full_overall[full_overall["Brnd_Name"].isin(selected_drugs)].copy()
        cmp_long["Spending_B"] = cmp_long["Tot_Spndng"] / 1e9
        fig_cmp = px.bar(
            cmp_long.sort_values("Year"),
            x="Year", y="Spending_B", color="Brnd_Name", barmode="group",
            labels={"Spending_B": "Total Medicare Spending ($B)",
                    "Brnd_Name": "Drug", "Year": "Period"},
        )
        apply_dark_theme(fig_cmp)
        st.plotly_chart(fig_cmp, use_container_width=True)
        st.caption("2025 reflects partial year (Q1–Q2 only); the visual drop from 2024 isn't a spending decline.")

        cmp_summary = (
            cmp_long.groupby("Brnd_Name")
            .agg(total_spending=("Tot_Spndng", "sum"),
                 total_benes=("Tot_Benes", "sum"))
            .reset_index()
        )
        cmp_summary["Total Spending ($B)"] = (cmp_summary["total_spending"] / 1e9).round(2)
        cmp_summary["Total Beneficiaries (M)"] = (cmp_summary["total_benes"] / 1e6).round(2)
        cmp_summary["Avg Spending / Beneficiary ($)"] = (
            cmp_summary["total_spending"] / cmp_summary["total_benes"]
        ).round(0).apply(lambda x: f"${x:,.0f}")
        cmp_disp = cmp_summary.rename(columns={"Brnd_Name": "Drug"})[
            ["Drug", "Total Spending ($B)", "Total Beneficiaries (M)",
             "Avg Spending / Beneficiary ($)"]
        ]
        st.dataframe(cmp_disp, use_container_width=True, hide_index=True)
        st.download_button("📥 Download Comparison",
                           data=cmp_disp.to_csv(index=False).encode("utf-8"),
                           file_name=f"drug_comparison_{year_label}.csv",
                           mime="text/csv", key="dl_partd_cmp_v2")

    st.divider()
    yrs = sorted(full_overall["Year"].unique().tolist())
    if len(yrs) >= 2:
        c0, c1y = yrs[0], yrs[1]
        # CMS labels mid-release periods as "(Q1-Q2)" or "(Q1-Q3)"; full
        # years are "(Q1-Q4)". Annualize partial periods so the YoY %
        # compares like-for-like; full years pass through unchanged.
        if "Q1-Q2" in str(c1y):
            annualize_factor = 2
            c1y_label = c1y.replace("(Q1-Q2)", "(H1 annualized)")
        elif "Q1-Q3" in str(c1y):
            annualize_factor = 4 / 3
            c1y_label = c1y.replace("(Q1-Q3)", "(Q1-Q3 annualized)")
        else:
            annualize_factor = 1
            c1y_label = c1y
        st.subheader(f"📈 Fastest Growing Drugs ({c0} → {c1y_label})")

        yoy_df = full_overall.groupby(["Brnd_Name", "Year"])["Tot_Spndng"].sum().reset_index()
        pivot = yoy_df.pivot(index="Brnd_Name", columns="Year", values="Tot_Spndng").reset_index()
        pivot.columns.name = None
        pivot = pivot.dropna(subset=[c0, c1y])
        pivot = pivot[pivot[c0] >= 1e8]
        pivot[c1y] = pivot[c1y] * annualize_factor
        pivot["YoY_%"] = ((pivot[c1y] - pivot[c0]) / pivot[c0] * 100).round(1)
        top_growers = pivot.nlargest(10, "YoY_%")[["Brnd_Name", c0, c1y, "YoY_%"]].copy()
        top_growers[c0] = (top_growers[c0] / 1e9).round(2)
        top_growers[c1y] = (top_growers[c1y] / 1e9).round(2)
        top_growers.columns = ["Drug", f"{c0} ($B)", f"{c1y_label} ($B)", "Growth %"]
        fig6 = px.bar(top_growers, x="Growth %", y="Drug", orientation="h",
                      text="Growth %", color="Growth %",
                      color_continuous_scale=[[0, "#00BFA6"], [1, "#34D399"]])
        fig6.update_traces(texttemplate="%{text}%", textposition="outside")
        apply_dark_theme(fig6)
        fig6.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
        st.plotly_chart(fig6, use_container_width=True)
        st.dataframe(top_growers, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("💰 Most Expensive Drugs Per Beneficiary")
    afford = (filtered_df[filtered_df["Tot_Benes"] >= 100]
              .groupby("Brnd_Name")["Avg_Spnd_Per_Bene"].mean().nlargest(10).reset_index())
    afford["Avg_Spnd_Per_Bene"] = afford["Avg_Spnd_Per_Bene"].round(0)
    fig3 = px.bar(afford, x="Avg_Spnd_Per_Bene", y="Brnd_Name", orientation="h",
                  color="Avg_Spnd_Per_Bene",
                  color_continuous_scale=[[0, "#F59E0B"], [1, "#EF4444"]],
                  text="Avg_Spnd_Per_Bene")
    fig3.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
    apply_dark_theme(fig3)
    fig3.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
    st.plotly_chart(fig3, use_container_width=True)


def _render_partb_enhanced() -> None:
    st.subheader("💉 Medicare Part B — Doctor-Administered Drugs")
    with st.spinner("Loading Part B data..."):
        df_b = fetch_part_b_data()
    df_b["Tot_Spndng"] = pd.to_numeric(df_b["Tot_Spndng_2023"], errors="coerce")
    df_b["Tot_Benes"] = pd.to_numeric(df_b["Tot_Benes_2023"], errors="coerce")
    df_b = df_b.dropna(subset=["Tot_Spndng"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Part B Drugs", f"{df_b['Brnd_Name'].nunique():,}")
    c2.metric("Total Spending (2023)", f"${df_b['Tot_Spndng'].sum()/1e9:.1f}B")
    c3.metric("Total Beneficiaries", f"{df_b['Tot_Benes'].sum()/1e6:.1f}M")

    top_b = df_b.groupby("Brnd_Name")["Tot_Spndng"].sum().nlargest(10).reset_index()
    top_b["Spending_B"] = (top_b["Tot_Spndng"] / 1e9).round(2)
    fig_b = px.bar(top_b, x="Spending_B", y="Brnd_Name", orientation="h",
                   text="Spending_B", color="Spending_B",
                   color_continuous_scale=[[0, "#F59E0B"], [1, "#EF4444"]])
    fig_b.update_traces(texttemplate="%{text}B", textposition="outside")
    apply_dark_theme(fig_b)
    fig_b.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
    st.plotly_chart(fig_b, use_container_width=True)

    st.subheader("🔗 Drugs in Both Part B and Part D")
    part_d_drugs = set(df["Brnd_Name"].dropna().unique())
    part_b_drugs = set(df_b["Brnd_Name"].dropna().unique())
    overlap = part_d_drugs.intersection(part_b_drugs)
    if overlap:
        overlap_d = df[df["Brnd_Name"].isin(overlap)].groupby("Brnd_Name")["Tot_Spndng"].sum().reset_index()
        overlap_b = df_b[df_b["Brnd_Name"].isin(overlap)].groupby("Brnd_Name")["Tot_Spndng"].sum().reset_index()
        merged = overlap_d.merge(overlap_b, on="Brnd_Name", suffixes=("_PartD", "_PartB"))
        merged["Total_Combined"] = merged["Tot_Spndng_PartD"] + merged["Tot_Spndng_PartB"]
        merged = merged.nlargest(10, "Total_Combined")
        merged["Part D ($B)"] = (merged["Tot_Spndng_PartD"] / 1e9).round(2)
        merged["Part B ($B)"] = (merged["Tot_Spndng_PartB"] / 1e9).round(2)
        fig_o = px.bar(merged, x="Brnd_Name", y=["Part D ($B)", "Part B ($B)"],
                       barmode="group",
                       color_discrete_map={"Part D ($B)": "#1B6FE8", "Part B ($B)": "#F59E0B"})
        apply_dark_theme(fig_o)
        st.plotly_chart(fig_o, use_container_width=True)
        st.caption(f"{len(overlap):,} drugs appear in both Part B and Part D.")


def _render_geovariation_enhanced() -> None:
    st.subheader("👩‍⚕️ Healthcare Workforce Supply per 100k")
    with st.spinner("Loading HRSA AHRF data..."):
        df_ahrf = load_ahrf()
    states_only = df_ahrf[df_ahrf["st_abbrev"] != "US"].copy()
    for c in ["phys_wkforc_23", "rn_23", "dent_23", "popn_pums_23"]:
        states_only[c] = pd.to_numeric(states_only[c], errors="coerce")
    states_only["Physicians"] = states_only["phys_wkforc_23"] / states_only["popn_pums_23"] * 1e5
    states_only["Registered Nurses"] = states_only["rn_23"] / states_only["popn_pums_23"] * 1e5
    states_only["Dentists"] = states_only["dent_23"] / states_only["popn_pums_23"] * 1e5

    top15 = states_only.nlargest(15, "popn_pums_23")[
        ["st_abbrev", "Physicians", "Registered Nurses", "Dentists"]
    ].copy()
    long = top15.melt(id_vars="st_abbrev",
                      value_vars=["Physicians", "Registered Nurses", "Dentists"],
                      var_name="Profession", value_name="Per 100k")
    long["Per 100k"] = long["Per 100k"].round(1)
    fig_w = px.bar(long, x="st_abbrev", y="Per 100k", color="Profession",
                   barmode="group", color_discrete_sequence=PRIMARY_COLORS)
    apply_dark_theme(fig_w)
    fig_w.update_layout(xaxis={"categoryorder": "array",
                               "categoryarray": top15["st_abbrev"].tolist()})
    st.plotly_chart(fig_w, use_container_width=True)

    st.subheader("🚨 Provider Shortage — Practitioners Needed")
    with st.spinner("Loading HRSA HPSA data..."):
        df_hpsa = load_hpsa()
    df_hpsa["HPSA Shortage"] = pd.to_numeric(df_hpsa["HPSA Shortage"], errors="coerce")
    rollup = (df_hpsa.groupby(["Primary State Abbreviation", "Discipline"])["HPSA Shortage"]
              .sum().unstack(fill_value=0))
    rollup["Total"] = rollup.sum(axis=1)
    top15s = rollup.nlargest(15, "Total").drop(columns="Total").reset_index()
    long2 = top15s.melt(id_vars="Primary State Abbreviation", var_name="Discipline",
                        value_name="Practitioners Needed")
    long2["Practitioners Needed"] = long2["Practitioners Needed"].round(0)
    fig_s = px.bar(long2, x="Primary State Abbreviation", y="Practitioners Needed",
                   color="Discipline", barmode="group",
                   color_discrete_map={"Primary Care": "#EF4444",
                                       "Dental": "#8B5CF6",
                                       "Mental Health": "#F59E0B"})
    apply_dark_theme(fig_s)
    fig_s.update_layout(xaxis={"categoryorder": "array",
                               "categoryarray": top15s["Primary State Abbreviation"].tolist()})
    st.plotly_chart(fig_s, use_container_width=True)


with tab3:
    nav_col, content_col = st.columns([1, 4])

    with nav_col:
        st.markdown('<div class="hei-sb-section">EXPLORE BY DOMAIN</div>',
                    unsafe_allow_html=True)
        nav_options = []
        nav_keys = []
        for section, items in NAV_STRUCTURE:
            nav_options.append(f"— {section} —")
            nav_keys.append(None)
            for label, key in items:
                nav_options.append(f"   {label}")
                nav_keys.append(key)
        # Default to the first real selection (Drug Spending)
        default_idx = next((i for i, k in enumerate(nav_keys) if k is not None), 0)
        choice_idx = st.radio(
            "Select a topic", options=range(len(nav_options)),
            format_func=lambda i: nav_options[i],
            index=default_idx, label_visibility="collapsed", key="explore_nav",
        )
        active_key = nav_keys[choice_idx]
        active_label = nav_options[choice_idx].strip()

    with content_col:
        if active_key is None:
            st.info("Pick a topic from the left navigation to explore.")
        else:
            st.subheader(active_label)

            # Enhanced Views for the three special datasets
            if active_key == "cms_partd":
                _render_partd_enhanced(filtered, df, selected_year)
            elif active_key == "cms_partb":
                _render_partb_enhanced()
            elif active_key == "geo_variation_2014_2023":
                _render_geovariation_enhanced()
                st.divider()

            # Generic dynamic renderer (only if a summarizer exists)
            if active_key in SUMMARIZERS:
                st.markdown("---")
                st.markdown("**📊 State-level overview**")
                render_dataset_view(active_key, state_filter)
            elif active_key not in {"cms_partd", "cms_partb"}:
                st.info(f"No generic summarizer registered for `{active_key}`.")


# ======================================================================
# TAB 4 — Sources (intro card + existing inventory table)
# ======================================================================
with tab4:
    st.markdown(
        '<div class="hei-intro">The U.S. Healthcare Intelligence Platform '
        "aggregates 81 federal datasets from 23 agencies into a single "
        "queryable intelligence layer. This platform is open source — "
        "contributors can add datasets by following the contributor "
        "guide in the GitHub repository.</div>",
        unsafe_allow_html=True,
    )
    st.subheader("📚 Data Sources")
    st.markdown(
        "Every dataset that powers this dashboard, what it measures, and where it comes from. "
        "Use the filters below to narrow by agency, category, or keyword."
    )

    DATASETS = [
        # CMS — Medicare core (1–9)
        {"name": "CMS Medicare Geographic Variation", "agency": "CMS", "category": "Medicare Spending", "year_range": "2014–2023", "year_start": 2014, "year_end": 2023, "granularity": "State / County / National", "description": "Medicare FFS spending, beneficiary counts, and 200+ service-line breakdowns including utilization and quality.", "rows": 33639},
        {"name": "CMS Medicare Monthly Enrollment", "agency": "CMS", "category": "Medicare Enrollment", "year_range": "2013–2025", "year_start": 2013, "year_end": 2025, "granularity": "State", "description": "Part D, dual eligibility, and ESRD enrollment counts (additive fields only, no overlap with Geographic Variation).", "rows": 9802},
        {"name": "CMS Medicare Inpatient by Geography & Service", "agency": "CMS", "category": "Hospital Spending", "year_range": "2023", "year_start": 2023, "year_end": 2023, "granularity": "State × DRG", "description": "Medicare inpatient discharges, average submitted charges, and payment amounts by state and DRG.", "rows": 26479},
        {"name": "CMS Medicare Physician & Other Practitioners", "agency": "CMS", "category": "Medicare Spending", "year_range": "2023", "year_start": 2023, "year_end": 2023, "granularity": "State × HCPCS", "description": "Medicare physician services, providers, beneficiaries, and payments by HCPCS code and place of service.", "rows": 268634},
        {"name": "CMS Medicare Part D Prescribers (state × specialty)", "agency": "CMS", "category": "Prescribing Patterns", "year_range": "2023", "year_start": 2023, "year_end": 2023, "granularity": "State × Specialty", "description": "Part D prescribing volume, cost, opioid/brand/generic shares aggregated to state and provider specialty.", "rows": 5299},
        {"name": "Medicare Part D Drug Spending", "agency": "CMS", "category": "Medicare Spending", "year_range": "Multi-year", "year_start": 2018, "year_end": 2025, "granularity": "Drug × Year", "description": "Annual Medicare Part D spending and beneficiary counts by drug.", "rows": 28255},
        {"name": "Medicare Part B Drug Spending", "agency": "CMS", "category": "Medicare Spending", "year_range": "Multi-year", "year_start": 2018, "year_end": 2023, "granularity": "HCPCS × Year", "description": "Annual Medicare Part B physician-administered drug spending by HCPCS code.", "rows": 734},
        {"name": "CMS Chronic Conditions Prevalence", "agency": "CMS", "category": "Disease Burden", "year_range": "Multi-year", "year_start": 2017, "year_end": 2022, "granularity": "State × Sex × Age", "description": "Beneficiary-level prevalence rates for the 21 CMS-tracked chronic conditions.", "rows": 83160},
        {"name": "CMS Open Payments (state-aggregated)", "agency": "CMS", "category": "Industry Payments", "year_range": "2023", "year_start": 2023, "year_end": 2023, "granularity": "State", "description": "Pharmaceutical/device manufacturer payments to physicians and teaching hospitals; $3.31B total in 2023.", "rows": 60},
        # CMS — Hospital quality & facilities (10–19)
        {"name": "Hospital Compare — HCAHPS State", "agency": "CMS", "category": "Hospital Quality", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "State", "description": "Patient satisfaction (HCAHPS top-box %) by state across 12 dimensions.", "rows": 2856},
        {"name": "Hospital Compare — Unplanned Visits State", "agency": "CMS", "category": "Hospital Quality", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "State", "description": "Distribution of hospitals on readmission and ED-visit measures (worse / same / better than national).", "rows": 784},
        {"name": "Hospital Compare — Complications & Deaths State", "agency": "CMS", "category": "Hospital Quality", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "State", "description": "Distribution of hospitals on PSI-90, surgical complications, and 30-day mortality measures.", "rows": 1120},
        {"name": "Hospital Compare — General Info", "agency": "CMS", "category": "Hospital Quality", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "Facility", "description": "Hospital roster with overall 1–5★ rating, ownership, and per-domain measure counts.", "rows": 5426},
        {"name": "CMS Nursing Home Provider Information", "agency": "CMS", "category": "Long-term Care", "year_range": "Mar 2026 snapshot", "year_start": 2026, "year_end": 2026, "granularity": "Facility", "description": "Nursing home identity, beds, 5-star ratings, staffing hours per resident, deficiencies, and penalties.", "rows": 14703},
        {"name": "CMS Home Health Care Agencies", "agency": "CMS", "category": "Long-term Care", "year_range": "Apr 2026 snapshot", "year_start": 2026, "year_end": 2026, "granularity": "Facility", "description": "Home health agency services, 5-star quality rating, and process measures (timely care, flu vax, falls).", "rows": 12392},
        {"name": "CMS Hospice Provider Information", "agency": "CMS", "category": "Long-term Care", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "Facility", "description": "Hospice provider info, CAHPS Hospice Survey scores, HQRP star rating, family caregiver experience.", "rows": 6943},
        {"name": "CMS Dialysis Facility Compare", "agency": "CMS", "category": "Long-term Care", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "Facility", "description": "ESRD facility 5-star rating, transplant waitlist %, hospitalization rate, vascular access type, fluid management.", "rows": 7557},
        {"name": "CMS Hospital Price Transparency Enforcement", "agency": "CMS", "category": "Hospital Pricing", "year_range": "Multi-year", "year_start": 2021, "year_end": 2025, "granularity": "Facility action", "description": "CMS notices and enforcement actions against hospitals under the price transparency rule.", "rows": 10726},
        {"name": "CMS Medicare Advantage Star Ratings", "agency": "CMS", "category": "Insurance Quality", "year_range": "Multi-year", "year_start": 2020, "year_end": 2025, "granularity": "Contract", "description": "Medicare Advantage / PDP plan 1–5★ quality ratings on Part C, Part D, and overall composite.", "rows": 2415},
        # CMS — Programs (20–22)
        {"name": "CMS Medicare Shared Savings ACOs", "agency": "CMS", "category": "Accountable Care", "year_range": "Multi-year", "year_start": 2013, "year_end": 2024, "granularity": "ACO", "description": "Shared Savings Program ACO assigned beneficiaries, benchmarks, savings/losses, and quality scores.", "rows": 5001},
        {"name": "CMS Innovation Center (CMMI) Model Participants", "agency": "CMS", "category": "Payment Models", "year_range": "Feb 2026 snapshot", "year_start": 2026, "year_end": 2026, "granularity": "Organization × Model", "description": "Active CMMI alternative payment model participants across 17 models (PCF, MD TCOC, BPCI, ACO REACH).", "rows": 3498},
        {"name": "CMS Medicaid State Drug Utilization", "agency": "CMS", "category": "Medicaid Spending", "year_range": "Multi-year", "year_start": 2018, "year_end": 2024, "granularity": "State", "description": "Medicaid prescription utilization, total reimbursement, and Medicaid-vs-non-Medicaid splits by state.", "rows": 522},
        # HRSA (23–34)
        {"name": "HRSA Area Health Resources File (AHRF)", "agency": "HRSA", "category": "Workforce", "year_range": "2024–2025", "year_start": 2023, "year_end": 2024, "granularity": "State + National", "description": "Health workforce supply by profession (physicians, RNs, dentists, PAs), with population denominators.", "rows": 52},
        {"name": "HPSA — Primary Care", "agency": "HRSA", "category": "Provider Shortage", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "HPSA designation", "description": "Primary care HPSA designations: score, FTEs needed, designated population, lat/lon, county FIPS.", "rows": 77724},
        {"name": "HPSA — Dental", "agency": "HRSA", "category": "Provider Shortage", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "HPSA designation", "description": "Dental HPSA designations using the same schema as Primary Care.", "rows": 45176},
        {"name": "HPSA — Mental Health", "agency": "HRSA", "category": "Provider Shortage", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "HPSA designation", "description": "Mental health HPSA designations using the same schema as Primary Care.", "rows": 39517},
        {"name": "HRSA FQHC Site Roster", "agency": "HRSA", "category": "Health Centers", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "Facility", "description": "FQHC and Look-Alike service-delivery sites with locations, hours, and county/region/district codes.", "rows": 18880},
        {"name": "HRSA UDS — FQHC Patients Served (cleaned)", "agency": "HRSA", "category": "Health Centers", "year_range": "2024", "year_start": 2024, "year_end": 2024, "granularity": "Health center awardee", "description": "FQHC awardee patients served, demographics, insurance mix, and visit counts (32.4M total patients).", "rows": 1359},
        {"name": "HRSA UDS — H80 raw archive", "agency": "HRSA", "category": "Health Centers", "year_range": "2024", "year_start": 2024, "year_end": 2024, "granularity": "Health center awardee", "description": "Full UDS reporting workbook with 37 source tables (chronic conditions, procedures, financials).", "rows": 37},
        {"name": "HRSA Grants", "agency": "HRSA", "category": "Federal Grants", "year_range": "Multi-year", "year_start": 2010, "year_end": 2025, "granularity": "Grantee", "description": "Federal financial assistance awarded by HRSA (Health Centers, MCH, Workforce, Ryan White, etc.).", "rows": 114289},
        {"name": "HRSA Maternal & Child Health (Title V)", "agency": "HRSA", "category": "Maternal/Child Health", "year_range": "Multi-year", "year_start": 2014, "year_end": 2024, "granularity": "State × Measure × Stratifier", "description": "Title V National Performance and Outcome Measures across the MCH lifecourse.", "rows": 630430},
        {"name": "HRSA Ryan White HIV/AIDS Program", "agency": "HRSA", "category": "HIV/AIDS", "year_range": "Current", "year_start": 2024, "year_end": 2025, "granularity": "Recipient", "description": "Ryan White recipients and sub-recipients with HAB Provider Type and indicators for Parts A–F funding.", "rows": 2200},
        {"name": "HRSA Telehealth (Medicare beneficiary)", "agency": "HRSA", "category": "Telehealth", "year_range": "Multi-year", "year_start": 2020, "year_end": 2024, "granularity": "Quarter × Beneficiary stratification", "description": "Medicare telehealth utilization rates broken out by demographics and Medicaid/Medicare enrollment status.", "rows": 33712},
        {"name": "HRSA Workforce Projections", "agency": "HRSA", "category": "Workforce", "year_range": "Long horizon", "year_start": 2020, "year_end": 2037, "granularity": "State × Profession × Rurality", "description": "Modeled supply, demand, and shortage projections for ~30 health professions under multiple scenarios.", "rows": 102528},
        # CDC (35–50)
        {"name": "CDC NCHS Leading Causes of Death", "agency": "CDC", "category": "Mortality", "year_range": "1999–2017", "year_start": 1999, "year_end": 2017, "granularity": "State × Cause", "description": "Age-adjusted death rate and counts by state and cause (11 leading causes + all-causes).", "rows": 10868},
        {"name": "CDC Mortality 2018–2023 (extends NCHS)", "agency": "CDC", "category": "Mortality", "year_range": "2018–2023", "year_start": 2018, "year_end": 2023, "granularity": "State × Cause", "description": "Crude death rate per 100k and counts by state and cause; fills the 2018+ gap left by the NCHS file.", "rows": 4644},
        {"name": "CDC PLACES — County Chronic Disease", "agency": "CDC", "category": "Disease Burden", "year_range": "2022–2023", "year_start": 2022, "year_end": 2023, "granularity": "County", "description": "Model-based small-area chronic disease prevalence across 40 measures and 6 categories.", "rows": 229298},
        {"name": "CDC BRFSS Prevalence", "agency": "CDC", "category": "Disease Burden", "year_range": "2018–2024", "year_start": 2018, "year_end": 2024, "granularity": "State", "description": "State-level chronic disease prevalence across 21 classes and 63 topics.", "rows": 64290},
        {"name": "CDC VSRR — Drug Overdose Deaths", "agency": "CDC", "category": "Mortality", "year_range": "2015–2025", "year_start": 2015, "year_end": 2025, "granularity": "State (monthly)", "description": "Provisional drug overdose death counts by state, month, and 12 drug-class indicators.", "rows": 82530},
        {"name": "CDC Births / Natality", "agency": "CDC", "category": "Maternal/Child Health", "year_range": "Multi-year", "year_start": 2014, "year_end": 2023, "granularity": "State", "description": "State-level fertility rate, total births, % preterm, % low-birthweight.", "rows": 502},
        {"name": "CDC Maternal Mortality", "agency": "CDC", "category": "Maternal/Child Health", "year_range": "Multi-period", "year_start": 2018, "year_end": 2023, "granularity": "State", "description": "Maternal death counts and rates per 100k live births over rolling multi-year periods.", "rows": 260},
        {"name": "CDC HIV Surveillance", "agency": "CDC", "category": "Communicable Disease", "year_range": "Multi-year", "year_start": 2008, "year_end": 2023, "granularity": "State", "description": "New HIV diagnosis rates per 100k and case counts by state, with sex and demographic stratifications.", "rows": 832},
        {"name": "CDC STI Surveillance", "agency": "CDC", "category": "Communicable Disease", "year_range": "Multi-year", "year_start": 2017, "year_end": 2024, "granularity": "State (weekly)", "description": "Reported chlamydia, gonorrhea, syphilis, and congenital syphilis cases by jurisdiction and week.", "rows": 1918},
        {"name": "CDC Childhood Lead Exposure (CBLPP)", "agency": "CDC", "category": "Environmental Health", "year_range": "Multi-year", "year_start": 2018, "year_end": 2022, "granularity": "State", "description": "Children <72 months tested for lead and counts/percentages above 3.5/5/10/25/45 µg/dL thresholds.", "rows": 198},
        {"name": "CDC Oral Health (NOHSS)", "agency": "CDC", "category": "Oral Health", "year_range": "Multi-year", "year_start": 2010, "year_end": 2024, "granularity": "State × Indicator", "description": "Adult dental visits, edentulism, water fluoridation %, sealant prevalence, caries.", "rows": 34332},
        {"name": "CDC NHANES Summary Estimates", "agency": "CDC", "category": "Health Surveillance", "year_range": "Multi-cycle", "year_start": 2015, "year_end": 2023, "granularity": "National", "description": "Pre-aggregated NHANES estimates for biomarkers, nutrition, body measurements, dental, vision.", "rows": 6072},
        {"name": "CDC Social Vulnerability Index (SVI)", "agency": "CDC", "category": "Social Determinants", "year_range": "2022", "year_start": 2022, "year_end": 2022, "granularity": "County", "description": "Composite social vulnerability percentile and 4 thematic subscores plus 16 underlying indicators.", "rows": 3144},
        {"name": "CDC WISQARS — Injury Surveillance", "agency": "CDC", "category": "Injury", "year_range": "Multi-year", "year_start": 2018, "year_end": 2023, "granularity": "National (quarterly)", "description": "Injury and violent death rates (homicide, suicide, unintentional) with demographic stratifications.", "rows": 840},
        {"name": "CDC National Wastewater Surveillance (NWSS)", "agency": "CDC", "category": "Surveillance", "year_range": "Recent", "year_start": 2022, "year_end": 2025, "granularity": "State (weekly)", "description": "Population-weighted wastewater concentrations for SARS-CoV-2, flu, RSV, mpox by state and week.", "rows": 27761},
        {"name": "CDC Vaccination Coverage (combined)", "agency": "CDC", "category": "Immunization", "year_range": "2015–2025", "year_start": 2015, "year_end": 2025, "granularity": "State × Vaccine type", "description": "Coverage rates with 95% CI for flu (FluVaxView), childhood (NIS-Child), teen (NIS-Teen), and COVID-19.", "rows": 252883},
        # Other federal health agencies (51–58)
        {"name": "AHRQ MEPS (Insurance + Household)", "agency": "AHRQ", "category": "Insurance", "year_range": "Multi-year", "year_start": 2015, "year_end": 2023, "granularity": "State", "description": "Employer-sponsored insurance estimates (premium, contribution, take-up) and household expenditure data.", "rows": 32793},
        {"name": "NCI / CDC US Cancer Statistics", "agency": "NCI/CDC", "category": "Cancer", "year_range": "1999–2023", "year_start": 1999, "year_end": 2023, "granularity": "State × Site × Race × Sex", "description": "Cancer incidence and mortality with age-adjusted rates and confidence intervals; 27 cancer sites.", "rows": 1140819},
        {"name": "NIH RePORTER Research Funding", "agency": "NIH", "category": "Research Funding", "year_range": "FY 2020–2024", "year_start": 2020, "year_end": 2024, "granularity": "State × NIH Institute", "description": "NIH research grant dollars and project counts by state and NIH Institute (NCI, NIA, NHLBI, etc.).", "rows": 7243},
        {"name": "NIMH Mental Health Indicators", "agency": "NIMH", "category": "Mental Health", "year_range": "Pandemic-era", "year_start": 2020, "year_end": 2024, "granularity": "State", "description": "Anxiety/depression symptom prevalence, mental health treatment access and unmet need.", "rows": 16794},
        {"name": "ONC / ASTP Hospital Health IT Adoption", "agency": "ONC/ASTP", "category": "Health IT", "year_range": "2008–2020", "year_start": 2008, "year_end": 2020, "granularity": "State + National", "description": "Hospital EHR adoption % (CEHRT), interoperability, HIE participation, and patient engagement metrics.", "rows": 624},
        {"name": "FDA Adverse Events (FAERS summary)", "agency": "FDA", "category": "Pharmacovigilance", "year_range": "Multi-year", "year_start": 2015, "year_end": 2024, "granularity": "National", "description": "Annual FAERS report counts by indicator (serious / non-serious / death / hospitalization).", "rows": 288},
        {"name": "SAMHSA FindTreatment.gov Facilities", "agency": "SAMHSA", "category": "Behavioral Health", "year_range": "Current", "year_start": 2025, "year_end": 2025, "granularity": "Facility", "description": "Substance use and mental health treatment facilities with services, payment, and program flags.", "rows": 87549},
        {"name": "SAMHSA NSDUH State Estimates", "agency": "SAMHSA", "category": "Behavioral Health", "year_range": "Multi-period", "year_start": 2018, "year_end": 2023, "granularity": "State", "description": "Substance use, mental illness prevalence, and treatment receipt with 95% CIs.", "rows": 10136},
        # Workforce / Occupational (59–61)
        {"name": "BLS OES Healthcare Wages", "agency": "BLS", "category": "Workforce", "year_range": "May 2024", "year_start": 2024, "year_end": 2024, "granularity": "State × SOC", "description": "Healthcare occupation employment counts and wage percentiles (10/25/50/75/90).", "rows": 4136},
        {"name": "GME Residency Programs", "agency": "Public/AAMC", "category": "Workforce", "year_range": "Multi-year", "year_start": 2018, "year_end": 2024, "granularity": "State", "description": "Counts of teaching hospitals, resident FTEs, total hospitals, and beds by state.", "rows": 275},
        {"name": "OSHA Healthcare Injuries (SOII)", "agency": "OSHA/BLS", "category": "Workforce Safety", "year_range": "Multi-year", "year_start": 2018, "year_end": 2023, "granularity": "State × NAICS", "description": "Recordable injury and illness rates per 100 FTE in healthcare industries (hospitals, NF, ambulatory).", "rows": 2892},
        # Census (62–64)
        {"name": "Census ACS Demographics (5-year)", "agency": "Census", "category": "Demographics", "year_range": "2019–2023", "year_start": 2019, "year_end": 2023, "granularity": "State", "description": "Total population, median household income, education attainment, disability subcomponents.", "rows": 52},
        {"name": "Census SAHIE — Insurance Estimates", "agency": "Census", "category": "Insurance", "year_range": "2006–2023", "year_start": 2006, "year_end": 2023, "granularity": "State × IPR bracket", "description": "% uninsured and insured by state and income-to-poverty bracket; supports income-stratified analysis.", "rows": 4998},
        {"name": "Census SAIPE — Income & Poverty", "agency": "Census", "category": "Income/Poverty", "year_range": "2003–2023", "year_start": 2003, "year_end": 2023, "granularity": "County + State", "description": "Poverty rate (all ages and 0–17), median household income, count in poverty.", "rows": 67059},
        # Social determinants & infrastructure (65–72)
        {"name": "EPA EJSCREEN — Environmental Justice", "agency": "EPA", "category": "Environmental Health", "year_range": "Multi-year", "year_start": 2020, "year_end": 2024, "granularity": "County", "description": "Environmental burden indicators: PM2.5, ozone, diesel PM, traffic proximity, lead paint risk.", "rows": 32133},
        {"name": "USDA Food Access Research Atlas", "agency": "USDA", "category": "Social Determinants", "year_range": "2019", "year_start": 2019, "year_end": 2019, "granularity": "Census tract", "description": "Food desert flags (Low-Income + Low-Access at 0.5/1/10/20-mile thresholds), distance, vehicle access.", "rows": 72531},
        {"name": "USDA WIC Program", "agency": "USDA", "category": "Nutrition", "year_range": "FY 2021–2025", "year_start": 2021, "year_end": 2025, "granularity": "State", "description": "WIC participation (women/infants/children breakouts), food cost, NSA cost, total program cost.", "rows": 275},
        {"name": "HUD Fair Market Rents", "agency": "HUD", "category": "Housing", "year_range": "FY 2026", "year_start": 2026, "year_end": 2026, "granularity": "County / FMR area", "description": "40th-percentile fair market rent for 0/1/2/3/4-bedroom units by HUD area.", "rows": 4764},
        {"name": "DOT Transportation Infrastructure", "agency": "DOT", "category": "Transportation", "year_range": "Current", "year_start": 2024, "year_end": 2024, "granularity": "County", "description": "Counts of airports, public airfields, bridges, transit stations, and highway miles by county.", "rows": 3142},
        {"name": "FCC Broadband Availability", "agency": "FCC", "category": "Broadband Infrastructure", "year_range": "June 2024", "year_start": 2024, "year_end": 2024, "granularity": "County", "description": "Broadband availability at 25/3 and 100/20 Mbps thresholds, per-tech splits, unique provider counts.", "rows": 3234},
        {"name": "AoA / ACL Aging Services (NAPIS)", "agency": "ACL", "category": "Aging Services", "year_range": "Multi-year", "year_start": 2015, "year_end": 2023, "granularity": "State", "description": "Older Americans Act services: nutrition, transportation, supportive services, caregiver, expenditures.", "rows": 610},
        {"name": "RWJF County Health Rankings", "agency": "RWJF", "category": "Population Health", "year_range": "Annual", "year_start": 2010, "year_end": 2024, "granularity": "County", "description": "Composite county health rankings (Outcomes + Factors) plus ~390 underlying measures.", "rows": 3205},
        # State-specific (73)
        {"name": "California HCAI Hospital Utilization", "agency": "CA HCAI", "category": "Hospital Utilization", "year_range": "2012–2017", "year_start": 2012, "year_end": 2017, "granularity": "Facility (CA only)", "description": "California hospital annual utilization measures, characteristics, and administrative geography.", "rows": 226902},
        # Final batch (74-81)
        {"name": "CDC NHSN Healthcare-Associated Infections", "agency": "CDC", "category": "Hospital Quality", "year_range": "2024", "year_start": 2024, "year_end": 2024, "granularity": "State × Infection type", "description": "Standardized Infection Ratios (SIRs) for CLABSI, CAUTI, MRSA-BSI, C. difficile, and surgical site infections (colon, abdominal hysterectomy) by state.", "rows": 330},
        {"name": "CMS Timely & Effective Care — State", "agency": "CMS", "category": "Hospital Quality", "year_range": "2024", "year_start": 2024, "year_end": 2024, "granularity": "State × Measure", "description": "Process-of-care scores by state: ED throughput, sepsis bundle compliance, healthcare personnel flu vaccination, head-CT-within-45-min for stroke, opioid safety.", "rows": 1736},
        {"name": "CDC NNDSS Notifiable Disease Surveillance", "agency": "CDC", "category": "Communicable Disease", "year_range": "2022–2024", "year_start": 2022, "year_end": 2024, "granularity": "State × Week × Disease", "description": "Weekly case counts for ~115 notifiable infectious diseases (TB, hepatitis, salmonella, Lyme, pertussis, mumps, measles, etc.); stacked NNDSS Weekly + Lyme aggregated.", "rows": 430925},
        {"name": "BLS State Unemployment (LAUS)", "agency": "BLS", "category": "Economy", "year_range": "2020–2025", "year_start": 2020, "year_end": 2025, "granularity": "State × Month", "description": "Monthly state unemployment rates from BLS Local Area Unemployment Statistics (LAUS); fetched via FRED mirror (URN series).", "rows": 3672},
        {"name": "HRSA Nurse Corps", "agency": "HRSA", "category": "Workforce", "year_range": "FY 2024", "year_start": 2024, "year_end": 2024, "granularity": "State", "description": "Nurse Corps Loan Repayment + Scholarship Program participants and federal investment by state. SP $ apportioned (HRSA does not publish per-state SP $).", "rows": 53},
        {"name": "CDC Alzheimer's & Healthy Aging", "agency": "CDC", "category": "Aging Services", "year_range": "2015–2022", "year_start": 2015, "year_end": 2022, "granularity": "State × Topic", "description": "BRFSS-based older-adult indicators: subjective cognitive decline, caregiver burden/duration/intensity, frequent mental distress; deliberately excludes overlap with brfss_state_prevalence.", "rows": 69859},
        {"name": "SAMHSA N-MHSS State Profiles", "agency": "SAMHSA", "category": "Behavioral Health", "year_range": "2023", "year_start": 2023, "year_end": 2023, "granularity": "State", "description": "National Mental Health Services Survey state aggregates: facility counts by type, bed capacity (88,893 beds nationally), treatment approaches, payer mix.", "rows": 54},
        {"name": "CMS SNF Quality Reporting Program", "agency": "CMS", "category": "Long-term Care", "year_range": "Mar 2026 release", "year_start": 2022, "year_end": 2025, "granularity": "Facility × Measure", "description": "SNF QRP underlying measure scores (PPR-PD readmission, MSPB spending efficiency, IMPACT Act outcomes, HAI risk-standardized) — distinct from cms_nursing_home's rolled-up 5-stars.", "rows": 838071},
    ]

    df_sources = pd.DataFrame(DATASETS)

    # KPIs across all 81 datasets (computed BEFORE filtering)
    total_rows = int(df_sources["rows"].sum())
    year_start_min = int(df_sources["year_start"].min())
    year_end_max = min(int(df_sources["year_end"].max()), 2026)
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    col_k1.metric("Total Datasets", f"{len(df_sources):,}")
    col_k2.metric("Total Rows", f"~{total_rows / 1e6:.1f}M")
    col_k3.metric("Agencies", f"{df_sources['agency'].nunique()}")
    col_k4.metric("Year Span", f"{year_start_min}–{year_end_max}")

    st.divider()

    col_f1, col_f2 = st.columns([2, 1])
    search_q = col_f1.text_input("Search (matches name, agency, or category)", "", key="ds_search")
    category_choice = col_f2.selectbox(
        "Category", options=["All"] + sorted(df_sources["category"].unique().tolist()),
        key="ds_category",
    )
    filtered_sources = df_sources.copy()
    if search_q:
        q = search_q.lower()
        mask = (
            filtered_sources["name"].str.lower().str.contains(q, na=False)
            | filtered_sources["agency"].str.lower().str.contains(q, na=False)
            | filtered_sources["category"].str.lower().str.contains(q, na=False)
        )
        filtered_sources = filtered_sources[mask]
    if category_choice != "All":
        filtered_sources = filtered_sources[filtered_sources["category"] == category_choice]

    st.markdown(f"**Showing {len(filtered_sources)} of {len(df_sources)} datasets.**")
    display = filtered_sources[["name", "agency", "category", "year_range",
                                "granularity", "rows", "description"]].rename(columns={
        "name": "Dataset", "agency": "Agency", "category": "Category",
        "year_range": "Year Range", "granularity": "Granularity",
        "rows": "Rows", "description": "Description",
    })
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "Rows": st.column_config.NumberColumn("Rows", format="%d"),
            "Description": st.column_config.TextColumn("Description", width="large"),
        },
    )
    st.download_button(
        "📥 Download Data Sources as CSV",
        data=display.to_csv(index=False).encode("utf-8"),
        file_name="data_sources.csv", mime="text/csv", key="dl_data_sources",
    )
    st.caption(
        "Inventory hand-curated from `data/MANIFEST.md`. Year ranges marked 'Current' or "
        "'Multi-year' use a best estimate of the dataset's coverage window for the year-span KPI. "
        "Row counts reflect the cleaned files on disk at fetch time."
    )
