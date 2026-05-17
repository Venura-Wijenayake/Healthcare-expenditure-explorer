"""Outbreak Watch — rolling current-threats situation report.

Unlike the CA Workforce Atlas (a geographic case) or Provider
Accountability (a facility lookup), this lens is *time-aware*: the
demo question is "what disease threats is CDC warning about RIGHT NOW,
and what does the surveillance data show?" There is no single anchor
case — the HAN advisories ARE the anchor, and the active-surveillance
datasets supply quantitative context for whatever CDC is currently
warning about. The featured content rotates as new HAN alerts publish.

Datasets (all R2-backed; aggregates are pushed down to DuckDB
server-side rather than materialized into pandas — see _q()):
  - cdc_han              : HAN advisory archive (small; the live anchor).
  - cdc_nndss            : notifiable diseases, weekly, ~431k rows.
  - cdc_fluview_ilinet   : ILINet respiratory surveillance (key is
                           cdc_fluview_ilinet, NOT cdc_fluview).
  - cdc_arbonet          : vector-borne (WNV etc.), weekly.
  - cdc_foodnet          : foodborne incidence (Campylobacter has a
                           2024 methodology break — flagged, not hidden).
  - cdc_nors             : historical outbreaks by transmission mode.
  - cdc_wastewater       : forward-looking respiratory signal.

Honesty constraints enforced here (surveillance lag is real):
  * Every surveillance panel carries an explicit data-vintage caption.
  * "Right now" never means mid-season estimates: NNDSS runs to 2024,
    NORS to 2023, ArboNET 2026 is pre-season so the most-recent
    *complete* season (2025) is shown, FluView season is Oct–May.
  * HAN message_type is only populated for the most recent 9 records;
    the older 34 are surfaced as "Unspecified", not back-filled.
  * Nothing about "this week's status" is synthesized beyond what the
    data states.

Pure view layer — no ingestion, no new data.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from _pg_loader import lookup_storage
from _r2_loader import get_duckdb, r2_bucket

# Mirror app.py :root palette (Plotly can't read CSS vars). Color encodes
# alert SEVERITY here (Alert > Advisory > Update > Info), not benchmark.
_BG = "rgba(0,0,0,0)"
_GRID = "#1E3A5F"
_TXT = "#F0F4FF"
_TXT2 = "#8BA3C7"
_RED = "#EF4444"      # Health Alert (most severe)
_AMBER = "#F59E0B"    # Health Advisory
_TEAL = "#00BFA6"     # Health Update
_BLUE = "#3D8EFF"     # neutral / sparklines
_MUTED = "#4A6080"    # Unspecified / Info

# HAN message_type -> (display, color, severity rank for sorting)
_HAN_TYPE = {
    "Health Alert":    ("Health Alert", _RED, 4),
    "Health Advisory": ("Health Advisory", _AMBER, 3),
    "Health Update":   ("Health Update", _TEAL, 2),
    "Info Service":    ("Info Service", _MUTED, 1),
}
_HAN_DEFAULT = ("Unspecified", _MUTED, 0)

# Today, per the app's clock. Used for "days since" + the 90-day window.
_TODAY = pd.Timestamp(_dt.date.today())

_US_ABBR = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL",
    "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY",
    "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NEW YORK CITY": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND",
    "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY",
}
_VALID_ABBR = set(_US_ABBR.values())


def _layout(fig: go.Figure, height: int = 320, title: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=_TXT,
                                         family="Space Grotesk")),
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_TXT2, family="DM Sans", size=11),
        margin=dict(l=10, r=16, t=40 if title else 12, b=10),
        height=height, legend=dict(bgcolor=_BG, font=dict(color=_TXT2)),
        hoverlabel=dict(bgcolor="#162540", font=dict(color=_TXT)),
    )
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    return fig


# ---------------------------------------------------------------------------
# DuckDB pushdown. Aggregates run server-side on R2 Parquet; only small
# result frames reach pandas. Every query result is @st.cache_data'd.
# ---------------------------------------------------------------------------
_URI_CACHE: dict[str, str] = {}


def _uri(dataset_key: str) -> str:
    """r2://bucket/<parquet> for a dataset_key (registry-resolved)."""
    if dataset_key not in _URI_CACHE:
        reg = lookup_storage(dataset_key) or {}
        path = reg.get("parquet_path") or f"{dataset_key}.parquet"
        _URI_CACHE[dataset_key] = f"r2://{r2_bucket()}/{path}"
    return _URI_CACHE[dataset_key]


@st.cache_data(show_spinner=False)
def _q(sql: str) -> pd.DataFrame:
    """Run a DuckDB query (URIs already embedded) -> DataFrame. Cached."""
    con = get_duckdb()
    if con is None:
        raise RuntimeError("DuckDB/R2 not configured")
    return con.execute(sql).fetch_df()


def _short_disease(name: object) -> str:
    """'Arboviral diseases, West Nile virus disease' -> 'West Nile virus disease'."""
    s = str(name)
    return s.split(", ", 1)[1] if ", " in s else s


# ---------------------------------------------------------------------------
# HAN (small — pulled whole, then handled in pandas)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _han() -> pd.DataFrame:
    df = _q(f"SELECT * FROM read_parquet('{_uri('cdc_han')}')").copy()
    df["_date"] = pd.to_datetime(df["issue_date"], errors="coerce", utc=True
                                 ).dt.tz_localize(None)
    df = df.dropna(subset=["_date"]).sort_values("_date", ascending=False)
    meta = df["message_type"].map(
        lambda t: _HAN_TYPE.get(str(t).strip(), _HAN_DEFAULT)
        if t is not None and str(t).strip() not in ("", "None")
        else _HAN_DEFAULT)
    df["_type"] = meta.map(lambda m: m[0])
    df["_color"] = meta.map(lambda m: m[1])
    df["_rank"] = meta.map(lambda m: m[2])
    return df


def _tags(value: object) -> list[str]:
    if value is None or str(value).strip() in ("", "None"):
        return []
    return [t.strip() for t in str(value).replace("|", ",").split(",")
            if t.strip()]


# ---------------------------------------------------------------------------
# Panel 1 — header: latest Alert/Advisory
# ---------------------------------------------------------------------------
def _panel_header(han: pd.DataFrame) -> str | None:
    featured = han[han["message_type"].isin(["Health Alert",
                                             "Health Advisory"])]
    if featured.empty:
        st.warning("No Health Alert or Advisory in the HAN archive.")
        return None
    row = featured.sort_values(["_date"], ascending=False).iloc[0]
    color = row["_color"]
    days = int((_TODAY - row["_date"].normalize()).days)
    st.markdown(
        f"<div style='border-left:5px solid {color};padding:.4rem 0 .4rem "
        f".9rem'>"
        f"<span style='color:{color};font-weight:700;font-size:1.05rem'>"
        f"● {row['_type']}</span>"
        f"<span style='color:{_TXT2}'> &nbsp;·&nbsp; {row['han_number']} "
        f"&nbsp;·&nbsp; issued {row['_date']:%b %d, %Y} "
        f"({days} days ago)</span><br>"
        f"<span style='color:{_TXT};font-size:1.35rem;font-weight:700'>"
        f"{row['title']}</span></div>",
        unsafe_allow_html=True,
    )
    summary = str(row.get("summary") or "").strip()
    if summary and summary != "None":
        st.markdown(f"<span style='color:{_TXT2}'>{summary[:600]}"
                    f"{'…' if len(summary) > 600 else ''}</span>",
                    unsafe_allow_html=True)
    paths = _tags(row.get("pathogen_mentions"))
    geos = _tags(row.get("geographic_mentions"))
    chips = "".join(
        f"<span style='background:#162540;color:{_AMBER};border-radius:"
        f"10px;padding:2px 9px;margin-right:6px;font-size:.8rem'>🦠 {p}"
        f"</span>" for p in paths)
    chips += "".join(
        f"<span style='background:#162540;color:{_BLUE};border-radius:"
        f"10px;padding:2px 9px;margin-right:6px;font-size:.8rem'>📍 {g}"
        f"</span>" for g in geos)
    if chips:
        st.markdown(chips, unsafe_allow_html=True)
    url = str(row.get("source_url") or "").strip()
    if url and url != "None":
        st.markdown(f"[Read the full CDC HAN advisory →]({url})")
    return paths[0] if paths else None


# ---------------------------------------------------------------------------
# Panel 2 — HAN activity timeline
# ---------------------------------------------------------------------------
def _panel_timeline(han: pd.DataFrame) -> None:
    st.markdown("##### HAN activity")
    cutoff = _TODAY - pd.Timedelta(days=90)
    win = han[han["_date"] >= cutoff]
    widened = False
    if len(win) < 3:  # genuinely quiet — widen for context, labelled
        cutoff = _TODAY - pd.Timedelta(days=365)
        win = han[han["_date"] >= cutoff]
        widened = True
    st.caption(
        ("Last 90 days had fewer than 3 HAN messages — showing the last "
         "12 months for context. " if widened else
         "Every HAN message in the last 90 days. ")
        + "Color = message severity; gaps are quiet periods.")
    if win.empty:
        st.info("No HAN messages in the window.")
        return
    fig = go.Figure()
    for typ in win["_type"].unique():
        sub = win[win["_type"] == typ]
        fig.add_scatter(
            x=sub["_date"], y=[typ] * len(sub), mode="markers",
            name=typ,
            marker=dict(size=13, color=sub["_color"].iloc[0], opacity=0.8,
                        line=dict(color=_TXT, width=0.5)),
            customdata=sub[["han_number", "title", "pathogen_mentions"]],
            hovertemplate="%{customdata[0]} · %{x|%b %d, %Y}<br>"
                          "<b>%{customdata[1]}</b><br>"
                          "🦠 %{customdata[2]}<extra></extra>")
    fig.update_xaxes(range=[cutoff, _TODAY], title=None)
    fig.update_yaxes(categoryorder="array",
                     categoryarray=["Info Service", "Unspecified",
                                    "Health Update", "Health Advisory",
                                    "Health Alert"])
    st.plotly_chart(_layout(fig, height=230), width="stretch")
    st.caption(f"{len(win)} messages shown · archive vintage "
               f"{han['_date'].max():%Y-%m-%d}.")


# ---------------------------------------------------------------------------
# Panel 3 — 2x2 disease activity grid
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _fluview_natl() -> pd.DataFrame:
    return _q(f"""
        SELECT epiweek, wili, release_date
        FROM read_parquet('{_uri('cdc_fluview_ilinet')}')
        WHERE region='nat' ORDER BY epiweek DESC LIMIT 30
    """)


@st.cache_data(show_spinner=False)
def _arbonet_recent() -> tuple[int, pd.DataFrame]:
    """Most-recent COMPLETE year (2026 is pre-season) top state×disease."""
    yr = _q(f"""
        SELECT MAX(year) y FROM read_parquet('{_uri('cdc_arbonet')}')
        WHERE geo_type='state'
          AND year < (SELECT MAX(year) FROM
                      read_parquet('{_uri('cdc_arbonet')}'))
    """)["y"].iloc[0]
    df = _q(f"""
        WITH mw AS (SELECT MAX(week) w FROM
                    read_parquet('{_uri('cdc_arbonet')}')
                    WHERE year={yr} AND geo_type='state')
        SELECT state_normalized AS state, disease,
               SUM(cum_ytd_current) AS cases
        FROM read_parquet('{_uri('cdc_arbonet')}'), mw
        WHERE year={yr} AND geo_type='state' AND week=mw.w
        GROUP BY 1,2 HAVING SUM(cum_ytd_current) > 0
        ORDER BY cases DESC LIMIT 8
    """)
    df["disease"] = df["disease"].map(_short_disease)
    return int(yr), df


@st.cache_data(show_spinner=False)
def _foodnet_yoy() -> tuple[int, int, pd.DataFrame]:
    yrs = _q(f"""
        SELECT DISTINCT CAST(year AS INTEGER) AS year
        FROM read_parquet('{_uri('cdc_foodnet')}')
        WHERE metric_type='annual_incidence' AND year IS NOT NULL
        ORDER BY year DESC LIMIT 2
    """)["year"].tolist()
    cur, prev = int(yrs[0]), int(yrs[1])
    df = _q(f"""
        SELECT pathogen, CAST(year AS INTEGER) AS year, incidence_per_100k,
               campy_methodology_break
        FROM read_parquet('{_uri('cdc_foodnet')}')
        WHERE metric_type='annual_incidence'
          AND CAST(year AS INTEGER) IN ({cur},{prev})
    """)
    piv = df.pivot_table(index="pathogen", columns="year",
                         values="incidence_per_100k", aggfunc="first")
    brk = (df[df["year"] == cur].set_index("pathogen")
           ["campy_methodology_break"].astype(bool))
    piv["break"] = piv.index.map(lambda p: bool(brk.get(p, False)))
    piv["yoy"] = (piv[cur] - piv[prev]) / piv[prev] * 100
    return cur, prev, piv.reset_index()


@st.cache_data(show_spinner=False)
def _nndss_top(year: int) -> tuple[int, pd.DataFrame]:
    wk = _q(f"""SELECT MAX(week) w FROM read_parquet('{_uri('cdc_nndss')}')
               WHERE year={year}""")["w"].iloc[0]
    df = _q(f"""
        SELECT disease, SUM(cum_ytd_current) AS ytd
        FROM read_parquet('{_uri('cdc_nndss')}')
        WHERE year={year} AND week={int(wk)}
        GROUP BY 1 ORDER BY ytd DESC NULLS LAST LIMIT 8
    """)
    return int(wk), df


@st.cache_data(show_spinner=False)
def _nndss_latest_year() -> int:
    return int(_q(f"SELECT MAX(year) y FROM "
                  f"read_parquet('{_uri('cdc_nndss')}')")["y"].iloc[0])


def _mini(fig: go.Figure, h: int = 200) -> None:
    st.plotly_chart(_layout(fig, height=h), width="stretch")


def _panel_grid() -> None:
    st.markdown("##### Disease activity — current state across families")
    r1c1, r1c2 = st.columns(2)
    r2c1, r2c2 = st.columns(2)

    with r1c1:
        st.markdown("**🫁 Respiratory — ILINet**")
        fv = _fluview_natl().sort_values("epiweek")
        if fv.empty:
            st.info("No FluView data.")
        else:
            latest = fv.iloc[-1]
            ew = int(latest["epiweek"])
            fig = go.Figure()
            fig.add_scatter(x=fv["epiweek"].astype(str), y=fv["wili"],
                            mode="lines", line=dict(color=_BLUE, width=2),
                            hovertemplate="epiweek %{x}<br>wILI "
                                          "%{y:.2f}%<extra></extra>")
            fig.update_yaxes(title="wILI %")
            fig.update_xaxes(showticklabels=False)
            _mini(fig, 170)
            st.metric("National weighted ILI",
                      f"{latest['wili']:.2f}%",
                      help="Weighted % of outpatient visits for "
                           "influenza-like illness, most recent week.")
            st.caption(f"Vintage: epiweek {ew} · released "
                       f"{latest['release_date']} · season runs Oct–May.")

    with r1c2:
        st.markdown("**🦟 Vector-borne — ArboNET**")
        yr, ab = _arbonet_recent()
        if ab.empty:
            st.info("No ArboNET data.")
        else:
            ab = ab.sort_values("cases")
            colors = [_RED if "West Nile" in d else _BLUE
                      for d in ab["disease"]]
            fig = go.Figure(go.Bar(
                x=ab["cases"], y=ab["state"] + " · " + ab["disease"],
                orientation="h", marker_color=colors,
                hovertemplate="%{y}<br>%{x:.0f} cases (cum)<extra></extra>"))
            _mini(fig, 220)
            st.caption(f"Vintage: {yr} (most recent *complete* season — "
                       f"2026 is pre-season). West Nile in red.")

    with r2c1:
        st.markdown("**🍔 Foodborne — FoodNet**")
        cur, prev, fn = _foodnet_yoy()
        fn = fn.dropna(subset=["yoy"]).sort_values("yoy")
        fig = go.Figure(go.Bar(
            x=fn["yoy"],
            y=[p + (" *" if b else "") for p, b in
               zip(fn["pathogen"], fn["break"])],
            orientation="h",
            marker_color=[_MUTED if b else
                          (_RED if v > 0 else _TEAL)
                          for v, b in zip(fn["yoy"], fn["break"])],
            hovertemplate="%{y}<br>%{x:+.1f}% YoY<extra></extra>"))
        fig.update_xaxes(title=f"% change {prev}→{cur}")
        _mini(fig, 220)
        st.caption(f"Vintage: {cur} incidence /100k vs {prev}. "
                   f"\\* Campylobacter has a {cur} methodology break — "
                   f"its change is an artifact, not a real trend (grey).")

    with r2c2:
        st.markdown("**📋 Notifiable — NNDSS**")
        yr = _nndss_latest_year()
        wk, nd = _nndss_top(yr)
        nd = nd.dropna(subset=["ytd"]).sort_values("ytd")
        nd["lbl"] = nd["disease"].str.slice(0, 34)
        fig = go.Figure(go.Bar(
            x=nd["ytd"], y=nd["lbl"], orientation="h",
            marker_color=_BLUE,
            hovertemplate="%{y}<br>%{x:,.0f} cumulative cases"
                          "<extra></extra>"))
        fig.update_xaxes(title="YTD cases")
        _mini(fig, 220)
        st.caption(f"Vintage: {yr} week {wk} (NNDSS runs ~1–4 weeks "
                   f"behind real time). Data surfaces what's actually "
                   f"most-reported — STIs dominate.")


# ---------------------------------------------------------------------------
# Panel 4 — NNDSS state choropleth
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _nndss_conditions(year: int) -> list[str]:
    wk = _q(f"""SELECT MAX(week) w FROM read_parquet('{_uri('cdc_nndss')}')
               WHERE year={year}""")["w"].iloc[0]
    df = _q(f"""
        SELECT disease, SUM(cum_ytd_current) t
        FROM read_parquet('{_uri('cdc_nndss')}')
        WHERE year={year} AND week={int(wk)}
        GROUP BY 1 HAVING SUM(cum_ytd_current) > 50
        ORDER BY t DESC LIMIT 40
    """)
    return df["disease"].tolist()


@st.cache_data(show_spinner=False)
def _nndss_by_state(year: int,
                    condition: str | None) -> tuple[pd.DataFrame, int]:
    wk = _q(f"""SELECT MAX(week) w FROM read_parquet('{_uri('cdc_nndss')}')
               WHERE year={year}""")["w"].iloc[0]
    cond = ("" if not condition else
            " AND disease = '" + condition.replace("'", "''") + "'")
    df = _q(f"""
        SELECT reporting_area, SUM(cum_ytd_current) AS cases
        FROM read_parquet('{_uri('cdc_nndss')}')
        WHERE year={year} AND week={int(wk)}{cond}
        GROUP BY 1
    """)
    df["abbr"] = df["reporting_area"].astype(str).str.upper().map(
        lambda a: a if a in _VALID_ABBR else _US_ABBR.get(a))
    df = df.dropna(subset=["abbr"])
    out = (df.groupby("abbr", as_index=False)["cases"].sum())
    return out, int(wk)


def _panel_choropleth() -> None:
    st.markdown("##### Geographic distribution — reportable disease activity")
    yr = _nndss_latest_year()
    conds = _nndss_conditions(yr)
    options = ["All conditions"] + conds
    pick = st.selectbox("Condition", options, index=0,
                        key="ow_choropleth_cond",
                        help="Cumulative reported cases by state, "
                             f"NNDSS {yr}.")
    condition = None if pick == "All conditions" else pick
    state_df, wk = _nndss_by_state(yr, condition)
    n_states = state_df["abbr"].nunique()
    if state_df.empty:
        st.info("No state-level data for this condition.")
        return
    fig = px.choropleth(
        state_df, locations="abbr", locationmode="USA-states",
        color="cases", scope="usa",
        color_continuous_scale="Reds",
        labels={"cases": "Cum. cases"},
    )
    fig.update_layout(
        paper_bgcolor=_BG, geo_bgcolor=_BG,
        font=dict(color=_TXT2, family="DM Sans"),
        margin=dict(l=0, r=0, t=10, b=0), height=420,
        geo=dict(lakecolor=_BG, bgcolor=_BG))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        f"{pick} · NNDSS {yr} week {wk} · {n_states} states with data. "
        "Relative cumulative-case activity (states report under varied "
        "area encodings; this is a relative-intensity map, not an exact "
        "count). Surveillance lags real time by ~1–4 weeks.")


# ---------------------------------------------------------------------------
# Panel 5 — wastewater early warning
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _wastewater() -> pd.DataFrame:
    return _q(f"""
        SELECT week_end, pathogen_target,
               AVG(wval_pop_weighted_mean) AS level,
               SUM(n_sites_reporting) AS sites
        FROM read_parquet('{_uri('cdc_wastewater')}')
        GROUP BY 1,2 ORDER BY 1
    """)


def _panel_wastewater() -> None:
    st.markdown("##### Wastewater early-warning signal")
    ww = _wastewater()
    if ww.empty:
        st.info("No wastewater data.")
        return
    ww["_d"] = pd.to_datetime(ww["week_end"], errors="coerce")
    ww = ww.dropna(subset=["_d"])
    recent = ww[ww["_d"] >= ww["_d"].max() - pd.Timedelta(weeks=26)]
    paths = sorted(recent["pathogen_target"].unique())
    cols = st.columns(len(paths))
    pal = {"SARS-CoV-2": _RED, "Influenza A virus": _AMBER, "RSV": _TEAL}
    for col, pth in zip(cols, paths):
        s = recent[recent["pathogen_target"] == pth].sort_values("_d")
        with col:
            cur = s["level"].iloc[-1]
            prev = s["level"].iloc[-2] if len(s) > 1 else cur
            trend = "▲" if cur > prev else "▼" if cur < prev else "▪"
            st.metric(pth, f"{cur:.2f}",
                      delta=f"{trend} vs prior week",
                      delta_color="inverse")
            fig = go.Figure(go.Scatter(
                x=s["_d"], y=s["level"], mode="lines",
                line=dict(color=pal.get(pth, _BLUE), width=2),
                hovertemplate="%{x|%b %d}<br>%{y:.2f}<extra></extra>"))
            fig.update_xaxes(showticklabels=False)
            _mini(fig, 130)
    st.caption(
        f"Population-weighted wastewater concentration, national mean, "
        f"last 26 weeks · vintage {ww['_d'].max():%Y-%m-%d}. Wastewater "
        "typically leads case-report data by 1–2 weeks for respiratory "
        "pathogens — an early-warning, not a case count.")


# ---------------------------------------------------------------------------
# Panel 6 — NORS historical context
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _nors_recent() -> tuple[int, int, pd.DataFrame]:
    mx = int(_q(f"SELECT MAX(year) y FROM "
                f"read_parquet('{_uri('cdc_nors')}')")["y"].iloc[0])
    lo = mx - 4
    df = _q(f"""
        SELECT year, primary_mode, COUNT(*) AS outbreaks
        FROM read_parquet('{_uri('cdc_nors')}')
        WHERE year BETWEEN {lo} AND {mx}
        GROUP BY 1,2 ORDER BY 1
    """)
    return lo, mx, df


def _panel_nors() -> None:
    st.markdown("##### Historical context — NORS outbreaks by transmission mode")
    lo, mx, df = _nors_recent()
    if df.empty:
        st.info("No NORS data.")
        return
    order = (df.groupby("primary_mode")["outbreaks"].sum()
             .sort_values(ascending=False).index.tolist())
    pal = [_RED, _AMBER, _TEAL, _BLUE, _MUTED, "#7C3AED"]
    fig = go.Figure()
    for i, mode in enumerate(order):
        s = df[df["primary_mode"] == mode].set_index("year")[
            "outbreaks"].reindex(range(lo, mx + 1), fill_value=0)
        fig.add_bar(x=list(s.index), y=s.values, name=mode,
                    marker_color=pal[i % len(pal)],
                    hovertemplate=f"{mode}<br>%{{x}}: %{{y}} outbreaks"
                                  f"<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title=None, dtick=1)
    fig.update_yaxes(title="Reported outbreaks")
    st.plotly_chart(_layout(fig, height=300), width="stretch")
    st.caption(f"NORS reported outbreaks {lo}–{mx} (most recent complete "
               f"NORS publication is {mx}). Anchors current alert activity "
               "against the multi-year baseline.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render() -> None:
    """Render the Outbreak Watch tab."""
    st.subheader("👁️ Outbreak Watch")
    try:
        with st.spinner("Loading CDC HAN advisories and surveillance "
                        "aggregates…"):
            han = _han()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Outbreak Watch data unavailable: {exc}")
        return

    st.caption(
        "A rolling situation report: what CDC is warning about now, with "
        "the active-surveillance data behind it. The featured advisory "
        "rotates as new HAN messages publish — there is no fixed anchor "
        "case. Every surveillance panel discloses its data vintage; "
        "nothing here is synthesized beyond what the feeds report."
    )
    st.divider()
    _panel_header(han)
    st.divider()
    _panel_timeline(han)
    st.divider()
    _panel_grid()
    st.divider()
    _panel_choropleth()
    st.divider()
    left, right = st.columns(2)
    with left:
        _panel_wastewater()
    with right:
        _panel_nors()
    st.divider()
    st.caption(
        "Sources: CDC Health Alert Network · NNDSS · FluView ILINet · "
        "ArboNET · FoodNet · NORS · CDC wastewater surveillance. "
        "Surveillance feeds lag reality; vintages are stated per panel "
        "and are not aligned to one another."
    )
