"""Provider Accountability — single-facility nursing-home lookup.

A consumer-protection lens: "How does a patient or family member check
if a specific nursing home has serious problems?" The federal
accountability record for a facility is real but fragmented across
several CMS consumer sites (Care Compare, the deficiencies file, the
penalties file, the SNF QRP file). This view converges the four
CCN-keyed datasets at render time into one place, anchored on a
featured high-severity case (the analog of Glenn County for this lens).

Datasets (all R2-backed, fetched via data_loader.load_dataset):
  - cms_nursing_home                    : master active-provider table —
                                          name, address, ownership, beds,
                                          5-star rating (~14,700 facilities).
  - cms_care_compare_nh_deficiencies    : one row per cited deficiency
                                          (F-tag + Scope/Severity letter).
  - cms_care_compare_nh_penalties       : one row per CMP fine / payment
                                          denial.
  - cms_citation_codes                  : F-tag -> plain-English decode.
  - cms_snf                             : SNF QRP quality measures (long;
                                          one row per facility x measure).

Cross-dataset realities verified during discovery (see handoff):
  * Deficiency prefix is 100% "F"; F-tags decode against
    cms_citation_codes with a 0.00% global join gap.
  * The rolling window is anchored on the data's own max survey date
    (~2026-03), not the wall clock — "last 3 years" of the snapshot.
  * cms_snf is the SNF QRP coded-measure file, NOT the MDS clinical
    quality-measure file. Falls-with-injury / pressure-ulcer /
    antipsychotic measures are not in it; the five QRP measures that
    DO decode unambiguously (readmission, discharge-to-community,
    Medicare spend, infections-requiring-hospitalization, drug-regimen
    review) are surfaced instead.
  * The penalties file carries no deficiency foreign key — penalties
    are not linked to a specific F-tag in the source, so this view does
    not fabricate that association.

Pure view layer — no ingestion, no new data; the facility selector is a
real tool over the whole provider universe, not a hardcoded slide.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import load_dataset

# Plotly can't read the app's CSS variables; mirror the palette
# (app.py :root) as literals so charts match the shell. Same set the
# CA Workforce Atlas uses.
_BG = "rgba(0,0,0,0)"
_GRID = "#1E3A5F"
_TXT = "#F0F4FF"
_TXT2 = "#8BA3C7"
_RED = "#EF4444"      # immediate jeopardy / worse than benchmark
_TEAL = "#00BFA6"     # healthy / better than benchmark
_AMBER = "#F59E0B"    # actual harm / emphasis
_BLUE = "#3D8EFF"     # neutral context
_MUTED = "#4A6080"

CCN_COL = "CMS Certification Number (CCN)"

# Discovery-selected showcase: a 1-star, government-district nursing
# home in Austin, TX with 18 immediate-jeopardy citations and six-figure
# federal fines in the rolling 3-year window — the clearest single
# answer to "why does unified accountability data matter?".
_FEATURED_CCN = "455862"

# Scope/Severity letter -> band. CMS A–L matrix collapsed to the three
# bands the spec asks for. (A is absent in this snapshot; B is the floor.)
_SEV_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
_BANDS = [
    ("No harm (A–F)", set("ABCDEF"), _BLUE),
    ("Actual harm (G–I)", set("GHI"), _AMBER),
    ("Immediate jeopardy (J–L)", set("JKL"), _RED),
]
_BAND_OF = {c: name for name, letters, _ in _BANDS for c in letters}
_BAND_COLOR = {name: color for name, _, color in _BANDS}

# Five SNF QRP measures whose CMS code stems decode unambiguously.
# (code, label, unit, lower_is_better)
_SNF_MEASURES = [
    ("S_004_01_PPR_PD_RSRR", "Potentially preventable 30-day readmission",
     "%", True),
    ("S_005_02_DTC_RS_RATE", "Successful discharge to community",
     "%", False),
    ("S_006_01_MSPB_SCORE", "Medicare spending per beneficiary "
     "(1.00 = national avg)", "ratio", True),
    ("S_039_01_HAI_RS_RATE", "Infections requiring hospitalization",
     "per 100", True),
    ("S_007_02_OBS_RATE", "Drug-regimen review completed w/ follow-up",
     "%", False),
]


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


def _clean(text: object) -> str:
    """Normalize CMS deficiency prose for tooltip display.

    The source is clean UTF-8 (verified: zero U+FFFD across all
    418k deficiency + 643 citation-code rows). It does use the
    typographic right single-quote U+2019 (e.g. "resident’s"); fold
    it to a plain apostrophe so hover text renders consistently
    regardless of font.
    """
    return str(text).replace("’", "'").strip()


# ---------------------------------------------------------------------------
# Data loading — full frames fetched once via load_dataset, cached for the
# process. Per-CCN slices are cheap pandas filters on the cached frames;
# benchmark aggregates are cached separately.
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_facilities() -> pd.DataFrame:
    df = load_dataset("cms_nursing_home")
    df[CCN_COL] = df[CCN_COL].astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def _load_deficiencies() -> pd.DataFrame:
    df = load_dataset("cms_care_compare_nh_deficiencies").copy()
    df[CCN_COL] = df[CCN_COL].astype(str).str.strip()
    df["_survey"] = pd.to_datetime(df["Survey Date"], errors="coerce")
    df["_sev"] = df["Scope Severity Code"].astype(str).str.strip()
    df["_band"] = df["_sev"].map(_BAND_OF)
    return df.dropna(subset=["_survey", "_band"])


@st.cache_data(show_spinner=False)
def _load_penalties() -> pd.DataFrame:
    df = load_dataset("cms_care_compare_nh_penalties").copy()
    df[CCN_COL] = df[CCN_COL].astype(str).str.strip()
    df["_date"] = pd.to_datetime(df["Penalty Date"], errors="coerce")
    return df.dropna(subset=["_date"])


@st.cache_data(show_spinner=False)
def _load_citation_codes() -> dict[tuple[str, int], tuple[str, str]]:
    """(prefix, tag) -> ("F0689", plain-English description)."""
    df = load_dataset("cms_citation_codes")
    out: dict[tuple[str, int], tuple[str, str]] = {}
    for _, r in df.iterrows():
        pfx = str(r["Deficiency Prefix"]).strip()
        try:
            tag = int(r["Deficiency Tag Number"])
        except (TypeError, ValueError):
            continue
        out[(pfx, tag)] = (f"{pfx}{tag:04d}",
                           _clean(r["Deficiency Description"]))
    return out


@st.cache_data(show_spinner=False)
def _load_snf() -> pd.DataFrame:
    """SNF QRP long file, pre-filtered to the five surfaced measures."""
    codes = {m[0] for m in _SNF_MEASURES}
    df = load_dataset("cms_snf")
    df = df[df["Measure Code"].isin(codes)].copy()
    df[CCN_COL] = df[CCN_COL].astype(str).str.strip()
    df["_val"] = pd.to_numeric(df["Score"], errors="coerce")
    return df.dropna(subset=["_val"])


@st.cache_data(show_spinner=False)
def _window_start() -> pd.Timestamp:
    """Rolling 3-year window anchored on the data's own latest survey."""
    d = _load_deficiencies()
    max_d = d["_survey"].max()
    return max_d - pd.DateOffset(years=3)


def _ftag(prefix: object, tag: object,
          codes: dict[tuple[str, int], tuple[str, str]],
          fallback_desc: object = "") -> tuple[str, str]:
    """Decode one deficiency row to ("F0689", "Free of accident hazards…").

    Falls back to the row's own Deficiency Description if the (prefix,
    tag) pair is somehow absent from cms_citation_codes (0% in this
    snapshot, but the view must not crash on a future gap)."""
    pfx = str(prefix).strip()
    try:
        t = int(tag)
    except (TypeError, ValueError):
        return (pfx or "?", _clean(fallback_desc))
    code, desc = codes.get((pfx, t), (f"{pfx}{t:04d}", _clean(fallback_desc)))
    return code, desc


@st.cache_data(show_spinner=False)
def _severity_band_shares() -> tuple[pd.DataFrame, pd.Series]:
    """Per-facility %-of-citations in each band, within the window.

    Returns (per-facility share frame indexed by CCN with State, the
    three band columns) and the national median share Series. Cached:
    this is the most expensive cross-facility aggregation in the view.
    """
    d = _load_deficiencies()
    d = d[d["_survey"] >= _window_start()]
    counts = (d.groupby([CCN_COL, "_band"]).size()
              .unstack(fill_value=0))
    for name, _, _c in _BANDS:
        if name not in counts:
            counts[name] = 0
    counts = counts[[n for n, _, _ in _BANDS]]
    shares = counts.div(counts.sum(axis=1), axis=0) * 100
    fac = _load_facilities().set_index(CCN_COL)["State"]
    shares["State"] = shares.index.map(fac)
    nat_median = shares[[n for n, _, _ in _BANDS]].median()
    return shares, nat_median


@st.cache_data(show_spinner=False)
def _snf_benchmarks() -> pd.DataFrame:
    """Per-measure national + per-state median of the SNF QRP score."""
    snf = _load_snf()
    fac = _load_facilities().set_index(CCN_COL)["State"]
    snf = snf.assign(State=snf[CCN_COL].map(fac))
    nat = (snf.groupby("Measure Code")["_val"].median()
           .rename("national_median"))
    st_med = (snf.groupby(["Measure Code", "State"])["_val"].median()
              .rename("state_median").reset_index())
    out = st_med.merge(nat, on="Measure Code")
    return out


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------
def _rating_badge(rating: float | None) -> str:
    if rating is None or pd.isna(rating):
        return f"<span style='color:{_TXT2}'>Not rated</span>"
    r = int(rating)
    color = _RED if r <= 2 else _AMBER if r == 3 else _TEAL
    stars = "★" * r + "☆" * (5 - r)
    return (f"<span style='color:{color};font-size:1.5rem;"
            f"font-weight:700'>{stars}</span> "
            f"<span style='color:{color}'>{r}-star overall</span>")


def _panel_header(fac: pd.Series, defs: pd.DataFrame,
                  pens: pd.DataFrame) -> None:
    name = fac.get("Provider Name", "—")
    addr = ", ".join(str(fac.get(c, "")).strip() for c in
                     ("Provider Address", "City/Town", "State")
                     if str(fac.get(c, "")).strip())
    zipc = fac.get("ZIP Code")
    if pd.notna(zipc):
        addr += f" {int(zipc)}"
    own = str(fac.get("Ownership Type", "—"))
    beds = fac.get("Number of Certified Beds")
    avg_res = fac.get("Average Number of Residents per Day")
    occ = (avg_res / beds * 100) if pd.notna(beds) and beds and pd.notna(avg_res) else None

    st.markdown(f"### {name}")
    st.markdown(
        f"{addr}  ·  **{own}**  ·  "
        f"{int(beds) if pd.notna(beds) else '—'} certified beds  ·  "
        f"{occ:.0f}% occupancy" if occ is not None
        else f"{addr}  ·  **{own}**  ·  "
             f"{int(beds) if pd.notna(beds) else '—'} certified beds",
        unsafe_allow_html=False,
    )
    st.markdown(_rating_badge(fac.get("Overall Rating")),
                unsafe_allow_html=True)

    cmp_total = pens.loc[pens["Penalty Type"] == "Fine", "Fine Amount"].sum()
    n_ij = int((defs["_band"] == "Immediate jeopardy (J–L)").sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Citations · last 3 yrs", f"{len(defs):,}",
              help="Deficiencies cited at any Scope/Severity level in the "
                   "rolling 3-year window.")
    c2.metric("Immediate-jeopardy citations", f"{n_ij:,}",
              delta=None if n_ij == 0 else "serious",
              delta_color="inverse",
              help="Scope/Severity J, K or L — the most serious band, "
                   "meaning a situation that caused or was likely to "
                   "cause serious injury, harm or death.")
    c3.metric("Cumulative fines · last 3 yrs", f"${cmp_total:,.0f}",
              help="Sum of Civil Money Penalty fine amounts in the "
                   "window. Payment denials are counted separately in "
                   "the penalty record below.")


def _panel_severity(defs: pd.DataFrame, ccn: str) -> None:
    st.markdown("##### Citation severity vs other facilities")
    st.caption("Share of this facility's citations in each Scope/Severity "
               "band (bars) against the state and national median facility "
               "(diamonds). Immediate jeopardy is the band that should be "
               "near-zero everywhere.")
    if defs.empty:
        st.info("No citations in the last 3 years for this facility.")
        return
    band_names = [n for n, _, _ in _BANDS]
    this = (defs["_band"].value_counts(normalize=True)
            .reindex(band_names, fill_value=0) * 100)
    shares, nat_median = _severity_band_shares()
    state = _load_facilities().set_index(CCN_COL).loc[ccn, "State"] \
        if ccn in _load_facilities().set_index(CCN_COL).index else None
    st_rows = shares[shares["State"] == state] if state else shares.iloc[0:0]
    st_median = (st_rows[band_names].median() if not st_rows.empty
                 else pd.Series(np.nan, index=band_names))

    fig = go.Figure()
    fig.add_bar(
        y=band_names, x=[this[b] for b in band_names], orientation="h",
        marker_color=[_BAND_COLOR[b] for b in band_names],
        name="This facility",
        hovertemplate="%{y}<br>%{x:.0f}% of citations<extra></extra>")
    fig.add_scatter(
        y=band_names, x=[nat_median[b] for b in band_names], mode="markers",
        marker=dict(symbol="diamond", size=11, color=_TXT),
        name="National median facility",
        hovertemplate="National median %{x:.0f}%<extra></extra>")
    if not st_rows.empty:
        fig.add_scatter(
            y=band_names, x=[st_median[b] for b in band_names],
            mode="markers",
            marker=dict(symbol="diamond-open", size=13, color=_TXT2),
            name=f"{state} median facility",
            hovertemplate=f"{state} median %{{x:.0f}}%<extra></extra>")
    fig.update_xaxes(title="% of this facility's citations", ticksuffix="%")
    st.plotly_chart(_layout(fig, height=300), width="stretch")


def _panel_timeline(defs: pd.DataFrame,
                     codes: dict[tuple[str, int], tuple[str, str]]) -> None:
    st.markdown("##### Citation timeline")
    st.caption("Every cited deficiency in the rolling 3-year window, "
               "placed by survey date (x) and Scope/Severity letter (y). "
               "Hover for the decoded F-tag and what it means. Red = "
               "immediate jeopardy.")
    if defs.empty:
        st.info("No citations in the last 3 years for this facility.")
        return
    d = defs.copy()
    decoded = d.apply(
        lambda r: _ftag(r["Deficiency Prefix"], r["Deficiency Tag Number"],
                        codes, r.get("Deficiency Description", "")),
        axis=1, result_type="expand")
    d["_code"] = decoded[0]
    d["_desc"] = decoded[1]
    d["_band"] = d["_sev"].map(_BAND_OF)
    fig = go.Figure()
    for name, _letters, color in _BANDS:
        sub = d[d["_band"] == name]
        if sub.empty:
            continue
        fig.add_scatter(
            x=sub["_survey"], y=sub["_sev"], mode="markers", name=name,
            marker=dict(size=11, color=color, opacity=0.75,
                        line=dict(color=_TXT, width=0.5)),
            customdata=np.stack([sub["_code"], sub["_desc"]], axis=-1),
            hovertemplate=("%{x|%b %d, %Y} · severity %{y}<br>"
                           "<b>%{customdata[0]}</b> — %{customdata[1]}"
                           "<extra></extra>"))
    fig.update_yaxes(categoryorder="array", categoryarray=_SEV_ORDER,
                     title="Scope / Severity")
    fig.update_xaxes(title="Survey date")
    st.plotly_chart(_layout(fig, height=380), width="stretch")


def _panel_penalties(pens: pd.DataFrame) -> None:
    st.markdown("##### Penalty record")
    if pens.empty:
        st.info("No federal penalties recorded in the last 3 years for "
                "this facility.")
        return
    fines = pens[pens["Penalty Type"] == "Fine"]
    denials = pens[pens["Penalty Type"] == "Payment Denial"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Total fines", f"${fines['Fine Amount'].sum():,.0f}")
    c2.metric("Number of fines", f"{len(fines):,}")
    c3.metric("Payment-denial actions", f"{len(denials):,}")

    show = pens.sort_values("_date", ascending=False).copy()
    show["Date"] = show["_date"].dt.strftime("%Y-%m-%d")
    show["Amount / duration"] = np.where(
        show["Penalty Type"] == "Fine",
        show["Fine Amount"].map(lambda v: f"${v:,.0f}"
                                if pd.notna(v) else "—"),
        show["Payment Denial Length in Days"].map(
            lambda v: f"{int(v)} days payment denial"
            if pd.notna(v) else "payment denial"))
    st.dataframe(
        show[["Date", "Penalty Type", "Amount / duration"]],
        width="stretch", hide_index=True)
    st.caption("Each row is a real federal enforcement action (CMS Civil "
               "Money Penalty or payment denial). The source penalties "
               "file does not link a penalty to a specific F-tag, so no "
               "deficiency association is shown — see the timeline above "
               "for the citations that drove enforcement.")


def _panel_quality(ccn: str) -> None:
    st.markdown("##### Quality measures vs benchmarks")
    st.caption("SNF Quality Reporting Program measures: this facility "
               "against the state and national median facility. Bar color "
               "= better (teal) or worse (red) than the national median.")
    snf = _load_snf()
    mine = snf[snf[CCN_COL] == ccn].set_index("Measure Code")["_val"]
    bench = _snf_benchmarks()
    state = (_load_facilities().set_index(CCN_COL).loc[ccn, "State"]
             if ccn in _load_facilities().set_index(CCN_COL).index else None)

    rows = []
    for code, label, unit, lower_better in _SNF_MEASURES:
        if code not in mine.index:
            continue
        val = float(mine[code])
        nat = bench.loc[bench["Measure Code"] == code, "national_median"]
        nat = float(nat.iloc[0]) if not nat.empty else np.nan
        srow = bench[(bench["Measure Code"] == code)
                     & (bench["State"] == state)]
        stm = float(srow["state_median"].iloc[0]) if not srow.empty else np.nan
        better = (val < nat) if lower_better else (val > nat)
        rows.append((label, unit, val, stm, nat, better))
    if not rows:
        st.info("No SNF quality-measure data reported for this facility.")
        return

    fig = go.Figure()
    labels = [r[0] for r in rows]
    fig.add_bar(
        y=labels, x=[r[2] for r in rows], orientation="h",
        marker_color=[_TEAL if r[5] else _RED for r in rows],
        name="This facility",
        customdata=[r[1] for r in rows],
        hovertemplate="%{y}<br>%{x:.2f} %{customdata}<extra></extra>")
    fig.add_scatter(
        y=labels, x=[r[4] for r in rows], mode="markers",
        marker=dict(symbol="diamond", size=11, color=_TXT),
        name="National median",
        hovertemplate="National median %{x:.2f}<extra></extra>")
    fig.add_scatter(
        y=labels, x=[r[3] for r in rows], mode="markers",
        marker=dict(symbol="diamond-open", size=13, color=_TXT2),
        name=f"{state} median" if state else "State median",
        hovertemplate="State median %{x:.2f}<extra></extra>")
    fig.update_xaxes(title="Measure value (units differ — see hover)")
    st.plotly_chart(_layout(fig, height=max(280, 70 * len(rows))),
                    width="stretch")
    with st.expander("What these measures mean"):
        st.markdown(
            "- **Potentially preventable 30-day readmission** — risk-"
            "standardized % of stays with an avoidable readmission "
            "(lower is better).\n"
            "- **Successful discharge to community** — risk-standardized "
            "% discharged home and still there 31 days later (higher is "
            "better).\n"
            "- **Medicare spending per beneficiary** — facility cost "
            "ratio; 1.00 = national average (lower is better).\n"
            "- **Infections requiring hospitalization** — risk-"
            "standardized rate of infections serious enough to need "
            "hospital care (lower is better).\n"
            "- **Drug-regimen review completed with follow-up** — "
            "process measure: % of stays where medications were reviewed "
            "and issues acted on (higher is better).\n\n"
            "Source: CMS SNF Quality Reporting Program (`cms_snf`). The "
            "MDS clinical measures (falls with injury, pressure ulcers, "
            "antipsychotic use) live in a different Care Compare file and "
            "are not in this dataset."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _facility_options(fac: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    """Build sorted 'Name — City, ST (CCN)' labels -> CCN map."""
    label = (fac["Provider Name"].astype(str).str.strip() + " — "
             + fac["City/Town"].astype(str).str.strip() + ", "
             + fac["State"].astype(str).str.strip() + " (" + fac[CCN_COL] + ")")
    pairs = sorted(zip(label, fac[CCN_COL]), key=lambda p: p[0].lower())
    labels = [p[0] for p in pairs]
    return labels, {lab: ccn for lab, ccn in pairs}


def render() -> None:
    """Render the Provider Accountability tab."""
    st.subheader("🏛️ Provider Accountability")
    try:
        with st.spinner("Loading federal nursing-home accountability "
                        "data (first load pulls four CMS datasets)…"):
            fac_df = _load_facilities()
            defs_all = _load_deficiencies()
            pens_all = _load_penalties()
            codes = _load_citation_codes()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Provider Accountability data unavailable: {exc}")
        return

    st.caption(
        "Federal accountability data for ~15,000 nursing homes — normally "
        "fragmented across multiple CMS consumer sites, unified here. The "
        "question this answers: *how does a patient or family member check "
        "if a specific nursing home has serious problems?*"
    )

    labels, lab_to_ccn = _facility_options(fac_df)
    by_ccn = fac_df.set_index(CCN_COL)
    featured_ccn = _FEATURED_CCN if _FEATURED_CCN in by_ccn.index else \
        fac_df[CCN_COL].iloc[0]
    default_label = next((l for l in labels
                          if l.endswith(f"({featured_ccn})")), labels[0])

    c_search, c_ccn = st.columns([3, 1])
    with c_search:
        chosen_label = st.selectbox(
            "Facility", labels, index=labels.index(default_label),
            key="acct_facility",
            help="Type to search ~15,000 Medicare/Medicaid nursing homes "
                 "by name, city or state.")
    with c_ccn:
        ccn_override = st.text_input(
            "…or enter a CCN", value="", max_chars=10,
            key="acct_ccn", placeholder="e.g. 455862").strip()

    ccn = lab_to_ccn[chosen_label]
    if ccn_override:
        if ccn_override in by_ccn.index:
            ccn = ccn_override
        else:
            st.warning(f"CCN {ccn_override} not found in cms_nursing_home — "
                       f"showing the selected facility instead.")

    if ccn == featured_ccn:
        st.markdown(
            "> **Featured case** — a 1-star, government-district nursing "
            "home in Austin, TX with **18 immediate-jeopardy citations** "
            "and six-figure federal fines in three years. The clearest "
            "single answer to *why does unified accountability data "
            "matter?* Switch facilities above — try a 5-star home like "
            "CCN `675281` for the contrast."
        )

    fac = by_ccn.loc[ccn]
    if isinstance(fac, pd.DataFrame):  # dup CCN guard
        fac = fac.iloc[0]
    win = _window_start()
    defs = defs_all[(defs_all[CCN_COL] == ccn)
                    & (defs_all["_survey"] >= win)].copy()
    pens = pens_all[(pens_all[CCN_COL] == ccn)
                    & (pens_all["_date"] >= win)].copy()

    st.divider()
    _panel_header(fac, defs, pens)
    st.divider()
    left, right = st.columns(2)
    with left:
        _panel_severity(defs, ccn)
    with right:
        _panel_timeline(defs, codes)
    st.divider()
    _panel_penalties(pens)
    st.divider()
    _panel_quality(ccn)
    st.caption(
        "Sources: CMS Nursing Home Care Compare (provider, deficiencies, "
        "penalties), CMS SNF Quality Reporting Program, CMS citation-code "
        "lookup. Rolling 3-year window anchored on the snapshot's latest "
        f"survey date ({win + pd.DateOffset(years=3):%b %Y}); F-tags "
        "decoded against the federal citation-code table."
    )
