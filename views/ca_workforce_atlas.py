"""CA Workforce Atlas — single-county view anchored on the Glenn County demo.

Answers "where in California does the next clinician matter most?" by
converging three already-ingested datasets at render time:

  - ca_hcai_supply_pqi  : county x PQI condition, with the relevant
                          ambulatory-care specialty supply rate and the
                          preventable-hospitalization rate vs the state
                          (analytical core).
  - ca_hcai_physicians  : active CA physicians by specialty x county.
  - cdc_svi             : county population, % age 65+, Social
                          Vulnerability Index percentile.
  - aamc_workforce      : CA vs US physicians-per-100k context (state
                          level; AMA PPD via AAMC, 2012 vintage).

Cross-dataset realities verified during discovery (see handoff):
  * acs_demographics is STATE-level in this build — county population /
    age / SVI come from cdc_svi, NOT acs_demographics.
  * HCAI uses bare county names ("Glenn"); cdc_svi uses the suffixed
    form ("Glenn County") — normalized here.
  * ca_hcai_physicians is missing Alpine & Sierra (present in
    supply_pqi); the supply panels degrade gracefully for those.

Pure view layer — no ingestion, no new data, numbers queried at render
time so the county selector is a real tool, not a hardcoded slide.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import load_dataset

# Plotly can't read the app's CSS variables; mirror the palette
# (app.py :root) as literals so charts match the shell.
_BG = "rgba(0,0,0,0)"
_GRID = "#1E3A5F"
_TXT = "#F0F4FF"
_TXT2 = "#8BA3C7"
_RED = "#EF4444"      # concerning gap
_TEAL = "#00BFA6"     # healthy benchmark
_AMBER = "#F59E0B"    # emphasis
_BLUE = "#3D8EFF"     # neutral context
_MUTED = "#4A6080"

_FEATURED = "Glenn"   # default-selected showcase county


def _layout(fig: go.Figure, height: int = 360, title: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=_TXT,
                                         family="Space Grotesk")),
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_TXT2, family="DM Sans", size=12),
        margin=dict(l=10, r=20, t=44 if title else 16, b=10),
        height=height, legend=dict(bgcolor=_BG, font=dict(color=_TXT2)),
        hoverlabel=dict(bgcolor="#162540", font=dict(color=_TXT)),
    )
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    return fig


@st.cache_data(show_spinner=False)
def _load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load + normalize the four datasets. Cached for the process."""
    sp = load_dataset("ca_hcai_supply_pqi")
    ph = load_dataset("ca_hcai_physicians")
    svi = load_dataset("cdc_svi")
    aamc = load_dataset("aamc_workforce")

    svi = svi[svi["ST_ABBR"] == "CA"].copy()
    # HCAI county names are bare ("Glenn"); SVI carries the suffix.
    svi["county"] = (svi["COUNTY"].astype(str)
                     .str.replace(r"\s+County$", "", regex=True).str.strip())
    # SVI uses -999 as a missing sentinel.
    for c in ("RPL_THEMES", "EP_AGE65", "E_TOTPOP"):
        svi[c] = pd.to_numeric(svi[c], errors="coerce")
        svi.loc[svi[c] < 0, c] = np.nan
    return sp, ph, svi, aamc


@st.cache_data(show_spinner=False)
def _physicians_per_100k(ph: pd.DataFrame, svi: pd.DataFrame) -> pd.DataFrame:
    """County x specialty patient-care physicians-per-100k + CA reference.

    Cached: this powers the cross-county supply comparison and is the
    most expensive aggregation in the view.

    CRITICAL: ca_hcai_physicians lists a physician once per
    (activity_category x activity_hours_bucket). Summing all rows
    double-counts ~7x (a doctor active in Patient Care + Administration
    + Training appears in each). We restrict to ``Patient Care`` — the
    clinically-relevant "active patient care" headcount the spec wants
    and the supply concept the HCAI Supply×PQI pairing is built on.
    """
    ph = ph[ph["activity_category"] == "Patient Care"]
    pop = svi.set_index("county")["E_TOTPOP"]
    ca_pop = pop.sum()
    by_cs = (ph.groupby(["county", "specialty"])["estimated_count"]
               .sum().reset_index())
    by_cs["pop"] = by_cs["county"].map(pop)
    by_cs["per_100k"] = by_cs["estimated_count"] / by_cs["pop"] * 1e5
    ca_rate = (ph.groupby("specialty")["estimated_count"].sum()
               / ca_pop * 1e5).rename("ca_per_100k")
    by_cs = by_cs.join(ca_rate, on="specialty")
    return by_cs


def _svi_row(svi: pd.DataFrame, county: str) -> pd.Series | None:
    r = svi[svi["county"] == county]
    return None if r.empty else r.iloc[0]


def _ca_context_caption(aamc: pd.DataFrame) -> str:
    a = aamc[(aamc["state"] == "California")
             & (aamc["physician_group"] == "Total")
             & (aamc["metric"] == "active_physicians_per_100k")]
    us = aamc[(aamc["physician_group"] == "Total")
              & (aamc["metric"] == "active_physicians_per_100k")
              & (~aamc["state"].isin(["Puerto Rico", "United States"]))]
    if a.empty or us.empty:
        return ""
    ca_v = a["value"].iloc[0]
    vint = str(aamc["vintage"].iloc[0])
    return (f"State context: California has **{ca_v:,.0f}** active "
            f"physicians per 100k vs a US median of **{us['value'].median():,.0f}** "
            f"(AAMC / AMA Physician Professional Data, {vint} vintage — "
            f"licensee headcount, not employment-based).")


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------
def _panel_header(county: str, sp: pd.DataFrame, ph: pd.DataFrame,
                  svi: pd.DataFrame, aamc: pd.DataFrame) -> None:
    s = _svi_row(svi, county)
    pop = int(s["E_TOTPOP"]) if s is not None and pd.notna(s["E_TOTPOP"]) else None
    age65 = s["EP_AGE65"] if s is not None else np.nan
    svi_pct = (round(s["RPL_THEMES"] * 100) if s is not None
               and pd.notna(s["RPL_THEMES"]) else None)

    # Patient-care only — see _physicians_per_100k for the double-count rationale.
    pc = ph[ph["activity_category"] == "Patient Care"]
    cty_docs = pc.loc[pc["county"] == county, "estimated_count"].sum()
    ca_docs = pc["estimated_count"].sum()
    ca_pop = svi["E_TOTPOP"].sum()
    per100k = (cty_docs / pop * 1e5) if pop else np.nan
    ca_per100k = ca_docs / ca_pop * 1e5
    delta = (per100k - ca_per100k) if pop else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Population", f"{pop:,}" if pop else "—")
    c2.metric("Age 65+", f"{age65:.1f}%" if pd.notna(age65) else "—")
    c3.metric(
        "Social Vulnerability",
        f"{svi_pct}th pctile" if svi_pct is not None else "—",
        help="CDC/ATSDR SVI overall percentile (RPL_THEMES). Higher = "
             "more socially vulnerable.",
    )
    c4.metric(
        "Patient-care MDs / 100K",
        f"{per100k:,.0f}" if pop and cty_docs else "—",
        delta=(f"{delta:+,.0f} vs CA avg" if delta is not None
               and cty_docs else None),
        delta_color="normal",
        help="HCAI patient-care physician headcount ÷ SVI county "
             "population × 100,000. 'Patient Care' activity only — "
             "ca_hcai_physicians lists a physician once per activity "
             "category, so summing all activities would ~7x over-count.",
    )
    cap = _ca_context_caption(aamc)
    if cap:
        st.caption(cap)


def _panel_supply_gap(county: str, pp: pd.DataFrame) -> None:
    st.markdown("##### The supply gap")
    st.caption("Patient-care physicians per 100K by specialty in this "
               "county (bars) vs the California average for that "
               "specialty (diamond). Red = below the state average — "
               "locally under-supplied.")
    d = pp[pp["county"] == county].copy()
    if d.empty:
        st.info(f"No HCAI physician records for {county} County "
                "(HCAI does not report Alpine or Sierra).")
        return
    d = d.sort_values("per_100k")
    colors = np.where(d["per_100k"] < d["ca_per_100k"], _RED, _TEAL)
    fig = go.Figure()
    fig.add_bar(y=d["specialty"], x=d["per_100k"], orientation="h",
                marker_color=colors, name=f"{county} County",
                hovertemplate="%{y}<br>%{x:.0f} / 100K<extra></extra>")
    fig.add_scatter(y=d["specialty"], x=d["ca_per_100k"], mode="markers",
                    marker=dict(symbol="diamond", size=10, color=_AMBER),
                    name="CA average",
                    hovertemplate="CA avg %{x:.0f} / 100K<extra></extra>")
    fig.update_xaxes(title="Physicians per 100,000")
    st.plotly_chart(_layout(fig, height=max(300, 42 * len(d))),
                    use_container_width=True)


def _panel_outcomes_gap(county: str, sp: pd.DataFrame) -> None:
    st.markdown("##### The outcomes gap")
    st.caption("Preventable-hospitalization (AHRQ PQI) rate per 100K by "
               "condition: this county vs the California mean. The widest "
               "gap is highlighted — that is where local care is failing "
               "hardest.")
    d = sp[sp["county"] == county][
        ["pqi_description", "cty_pqi_rate", "st_pqi_rate"]].copy()
    if d.empty:
        st.info(f"No PQI data for {county} County.")
        return
    d["gap"] = d["cty_pqi_rate"] - d["st_pqi_rate"]
    d = d.sort_values("gap")
    worst = d["gap"].idxmax()
    cty_colors = [_AMBER if i == worst else _RED for i in d.index]
    fig = go.Figure()
    fig.add_bar(y=d["pqi_description"], x=d["st_pqi_rate"], orientation="h",
                marker_color=_MUTED, name="CA mean",
                hovertemplate="CA mean %{x:.0f}<extra></extra>")
    fig.add_bar(y=d["pqi_description"], x=d["cty_pqi_rate"], orientation="h",
                marker_color=cty_colors, name=f"{county} County",
                hovertemplate="%{y}<br>%{x:.0f} / 100K<extra></extra>")
    fig.update_layout(barmode="group")
    fig.update_xaxes(title="Preventable hospitalizations per 100,000")
    st.plotly_chart(_layout(fig, height=max(320, 50 * len(d))),
                    use_container_width=True)


@st.cache_data(show_spinner=False)
def _scatter_frame(sp: pd.DataFrame, condition: str) -> pd.DataFrame:
    """Per-county supply vs PQI for one condition (cached cross-county calc)."""
    return sp[sp["pqi_description"] == condition][
        ["county", "cty_phy_rate", "cty_pqi_rate",
         "st_phy_rate", "st_pqi_rate"]].dropna()


def _panel_cross_reference(county: str, sp: pd.DataFrame) -> None:
    st.markdown("##### The cross-reference")
    st.caption("Every CA county positioned by physician supply (x) vs "
               "preventable-hospitalization rate (y) for one condition. "
               "The lower-right quadrant — low supply, high PQI — is the "
               "structural-failure zone. The selected county is red.")
    conditions = sorted(sp["pqi_description"].unique())
    default = (conditions.index("Heart Failure")
               if "Heart Failure" in conditions else 0)
    condition = st.selectbox("Condition", conditions, index=default,
                             key="atlas_xref_condition")
    d = _scatter_frame(sp, condition)
    if d.empty:
        st.info("No data for this condition.")
        return
    sx, sy = d["st_phy_rate"].iloc[0], d["st_pqi_rate"].iloc[0]
    is_sel = d["county"] == county
    fig = go.Figure()
    fig.add_scatter(
        x=d.loc[~is_sel, "cty_phy_rate"], y=d.loc[~is_sel, "cty_pqi_rate"],
        mode="markers", name="CA counties",
        marker=dict(size=8, color=_BLUE, opacity=0.55),
        text=d.loc[~is_sel, "county"],
        hovertemplate="%{text}<br>supply %{x:.0f}<br>PQI %{y:.0f}<extra></extra>")
    if is_sel.any():
        fig.add_scatter(
            x=d.loc[is_sel, "cty_phy_rate"], y=d.loc[is_sel, "cty_pqi_rate"],
            mode="markers+text", name=f"{county} County",
            marker=dict(size=16, color=_RED, line=dict(color=_TXT, width=1)),
            text=d.loc[is_sel, "county"], textposition="top center",
            textfont=dict(color=_TXT),
            hovertemplate="%{text}<br>supply %{x:.0f}<br>PQI %{y:.0f}<extra></extra>")
    fig.add_vline(x=sx, line=dict(color=_MUTED, dash="dash"))
    fig.add_hline(y=sy, line=dict(color=_MUTED, dash="dash"))
    xmax, ymax = d["cty_phy_rate"].max(), d["cty_pqi_rate"].max()
    for xx, yy, txt, anchor in [
        (sx * 0.5, ymax * 0.95, "LOW SUPPLY · HIGH PQI", "left"),
        (xmax * 0.98, ymax * 0.95, "high supply · high PQI", "right"),
        (sx * 0.5, sy * 0.1, "low supply · low PQI", "left"),
        (xmax * 0.98, sy * 0.1, "HIGH SUPPLY · LOW PQI", "right"),
    ]:
        fig.add_annotation(x=xx, y=yy, text=txt, showarrow=False,
                           font=dict(color=_MUTED, size=11), xanchor=anchor)
    fig.update_xaxes(title="Relevant-specialty physicians per 100,000")
    fig.update_yaxes(title=f"{condition} hospitalizations per 100,000")
    st.plotly_chart(_layout(fig, height=460,
                            title=f"{condition}: supply vs outcomes, all CA counties"),
                    use_container_width=True)


def _panel_priority(county: str, sp: pd.DataFrame) -> None:
    st.markdown("##### Specialty priority ranking")
    st.caption("Care domains ordered by the preventable-hospitalization "
               "gap this county carries where physician supply is also "
               "below the state norm. The top row is the operational "
               "answer to \"which clinician is most needed here\".")
    d = sp[sp["county"] == county].copy()
    if d.empty:
        st.info(f"No PQI data for {county} County.")
        return
    d["PQI vs state"] = (d["cty_pqi_rate"] / d["st_pqi_rate"]).round(2)
    d["pqi_gap"] = (d["cty_pqi_rate"] - d["st_pqi_rate"]).round(1)
    d["supply_deficit"] = (d["st_phy_rate"] - d["cty_phy_rate"]).round(1)
    # Actionable = supply is Low; rank those by the PQI gap, then append
    # the rest so the table is complete.
    low = d["phy_supply_vs_state"].eq("Low")
    d = pd.concat([d[low].sort_values("pqi_gap", ascending=False),
                   d[~low].sort_values("pqi_gap", ascending=False)])
    show = d[["pqi_description", "phy_supply_vs_state", "cty_phy_rate",
              "st_phy_rate", "supply_deficit", "cty_pqi_rate",
              "st_pqi_rate", "PQI vs state"]].rename(columns={
        "pqi_description": "Care domain (PQI condition)",
        "phy_supply_vs_state": "Supply vs state",
        "cty_phy_rate": "County supply /100K",
        "st_phy_rate": "State supply /100K",
        "supply_deficit": "Supply deficit /100K",
        "cty_pqi_rate": "County PQI /100K",
        "st_pqi_rate": "State PQI /100K",
    })
    st.dataframe(show, use_container_width=True, hide_index=True)
    with st.expander("Methodology"):
        st.markdown(
            "AHRQ Prevention Quality Indicators (PQIs) are conditions for "
            "which timely ambulatory care should prevent hospitalization. "
            "HCAI ties each PQI condition to the relevant ambulatory-care "
            "physician supply rate (`cty_phy_rate`). Rows where supply is "
            "**Low** vs the state are the actionable ones — a high PQI gap "
            "co-occurring with a supply deficit is the signal that adding "
            "that domain's clinicians could reduce preventable "
            "hospitalizations. This is an association surfaced from HCAI's "
            "own supply/outcome pairing, not a causal estimate. Population "
            "is CDC/ATSDR SVI (2022 ACS-based); physician counts are CA "
            "HCAI licensee data restricted to 'Patient Care' activity "
            "(the dataset rows physicians once per activity category, so "
            "an all-activity sum over-counts ~7x); vintages differ — "
            "directional, not actuarial."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render() -> None:
    """Render the CA Workforce Atlas tab."""
    st.subheader("🩺 CA Workforce Atlas")
    try:
        sp, ph, svi, aamc = _load()
    except Exception as exc:  # noqa: BLE001
        st.error(f"CA Workforce Atlas data unavailable: {exc}")
        return

    counties = sorted(sp["county"].unique())
    default_idx = counties.index(_FEATURED) if _FEATURED in counties else 0
    county = st.selectbox(
        "County", counties, index=default_idx, key="atlas_county",
        help="All CA counties in the HCAI Supply×PQI dataset.",
    )
    if county == _FEATURED:
        st.markdown(
            "> **Featured: Glenn County** — a rural Northern California "
            "county (pop ~28,700) that is a structural outlier: physician "
            "supply below the state norm on *every* preventable-"
            "hospitalization domain, and elevated hospitalization rates on "
            "all but one. The clearest single answer to \"where does the "
            "next clinician matter most?\""
        )
    else:
        st.markdown(f"> Showing **{county} County**. Switch counties above; "
                    "Glenn County is the featured demonstration case.")

    st.divider()
    _panel_header(county, sp, ph, svi, aamc)
    st.divider()
    left, right = st.columns(2)
    with left:
        _panel_supply_gap(county, _physicians_per_100k(ph, svi))
    with right:
        _panel_outcomes_gap(county, sp)
    st.divider()
    _panel_cross_reference(county, sp)
    st.divider()
    _panel_priority(county, sp)
