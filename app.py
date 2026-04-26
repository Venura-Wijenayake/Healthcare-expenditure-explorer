import time
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from data_loader import fetch_part_d_data, fetch_part_b_data, load_geo_variation, load_ahrf, load_hpsa
from ai_analyst import (
    query_analyst,
    get_active_provider,
    PROVIDER_LABELS,
)

st.set_page_config(
    page_title="U.S. Healthcare Expenditure Explorer",
    page_icon="🏥",
    layout="wide"
)

st.title("🏥 U.S. Healthcare Expenditure Explorer")
st.markdown("Exploring Medicare drug and equipment spending across the United States.")

# Load data
with st.spinner("Loading Medicare Part D data..."):
    df = fetch_part_d_data()

# Clean columns
df["Tot_Spndng"] = pd.to_numeric(df["Tot_Spndng"], errors="coerce")
df["Tot_Benes"] = pd.to_numeric(df["Tot_Benes"], errors="coerce")
df = df.dropna(subset=["Tot_Spndng"])

# Sidebar filters
st.sidebar.header("Filters")

years = sorted(df["Year"].unique().tolist())
selected_year = st.sidebar.selectbox("Select Year", years, index=len(years)-1)

search_term = st.sidebar.text_input("Search Drug Name", "")

# Filter data
filtered = df[df["Year"] == selected_year]
if search_term:
    filtered = filtered[
        filtered["Brnd_Name"].str.contains(search_term, case=False, na=False) |
        filtered["Gnrc_Name"].str.contains(search_term, case=False, na=False)
    ]

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📊 Overview",
    "💊 Drug Analysis",
    "💰 Spending Deep Dive",
    "💉 Part B",
    "🗺️ Geography",
    "🔍 Compare States",
    "🤖 AI Analyst",
    "📚 Data Sources",
])

with tab1:
    # Metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Drugs", f"{filtered['Brnd_Name'].nunique():,}")
    col2.metric("Total Spending", f"${filtered['Tot_Spndng'].sum()/1e9:.1f}B")
    col3.metric("Total Beneficiaries", f"{filtered['Tot_Benes'].sum()/1e6:.1f}M")

    st.divider()

    # Auto insights
    st.subheader("📊 Key Insights")
    col_a, col_b = st.columns(2)

    # Insight 1: Top spending drug
    top_drug = filtered.groupby("Brnd_Name")["Tot_Spndng"].sum().idxmax()
    top_spend = filtered.groupby("Brnd_Name")["Tot_Spndng"].sum().max()
    col_a.info(f"💊 **{top_drug}** is the highest spending drug at **${top_spend/1e9:.1f}B** in {selected_year}")

    # Insight 2: Most expensive per patient
    df["Avg_Spnd_Per_Bene"] = pd.to_numeric(df["Avg_Spnd_Per_Bene"], errors="coerce")
    expensive_drug = filtered[filtered["Tot_Benes"] >= 100].groupby("Brnd_Name")["Avg_Spnd_Per_Bene"].mean().idxmax()
    expensive_cost = filtered[filtered["Tot_Benes"] >= 100].groupby("Brnd_Name")["Avg_Spnd_Per_Bene"].mean().max()
    col_b.warning(f"💰 **{expensive_drug}** costs an average of **${expensive_cost:,.0f}** per patient in {selected_year}")

    # Top 10 drugs by spending
    st.subheader(f"Top 10 Drugs by Total Spending ({selected_year})")
    top10 = filtered.groupby("Brnd_Name")["Tot_Spndng"].sum().nlargest(10).reset_index()
    top10["Spending_B"] = (top10["Tot_Spndng"] / 1e9).round(1)
    fig = px.bar(top10, x="Spending_B", y="Brnd_Name", orientation="h",
                 labels={"Spending_B": "Total Spending ($B)", "Brnd_Name": "Drug"},
                 color="Spending_B", color_continuous_scale="Blues",
                 text="Spending_B")
    fig.update_traces(texttemplate="%{text}B", textposition="outside")
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True, height=400)

    # Raw data table
    if search_term:
        st.divider()
        st.subheader(f"Search Results for '{search_term}'")
        display_df = (
            filtered[["Brnd_Name", "Gnrc_Name", "Tot_Spndng", "Tot_Benes", "Avg_Spnd_Per_Bene", "Year"]]
            .drop_duplicates()
            .sort_values("Tot_Spndng", ascending=False)
            .head(50)
            .copy()
        )
        display_df["Tot_Spndng"] = display_df["Tot_Spndng"].apply(lambda x: f"${x/1e9:.2f}B")
        display_df["Avg_Spnd_Per_Bene"] = display_df["Avg_Spnd_Per_Bene"].apply(lambda x: f"${x:,.0f}")
        display_df.columns = ["Brand", "Generic", "Total Spending", "Beneficiaries", "Avg/Beneficiary", "Year"]
        st.dataframe(display_df, use_container_width=True)

        # Download button
        csv = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Results as CSV",
            data=csv,
            file_name=f"{search_term}_results.csv",
            mime="text/csv"
        )

with tab2:
    # GLP-1 Spotlight
    st.subheader("🔬 GLP-1 Spotlight — Ozempic & Mounjaro")
    st.markdown("GLP-1 drugs are the fastest growing drug category in Medicare spending.")

    glp1_drugs = ["Ozempic", "Mounjaro", "Trulicity", "Victoza", "Rybelsus", "Wegovy"]
    glp1_df = df[df["Brnd_Name"].isin(glp1_drugs)].copy()
    glp1_df["Spending_B"] = (glp1_df["Tot_Spndng"] / 1e9).round(2)

    if not glp1_df.empty:
        fig2 = px.bar(
            glp1_df,
            x="Year",
            y="Spending_B",
            color="Brnd_Name",
            barmode="group",
            labels={"Spending_B": "Total Spending ($B)", "Brnd_Name": "Drug", "Year": "Period"},
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        st.plotly_chart(fig2, use_container_width=True, height=400)
    else:
        st.info("No GLP-1 data found.")

    st.divider()

    # Drug Comparison Tool
    st.subheader("🔍 Drug Comparison Tool")
    st.markdown("Select up to 5 drugs to compare side by side.")

    all_drugs = sorted(filtered["Brnd_Name"].dropna().unique().tolist())
    selected_drugs = st.multiselect(
        "Select drugs to compare",
        options=all_drugs,
        default=["Ozempic", "Mounjaro", "Eliquis"] if all(d in all_drugs for d in ["Ozempic", "Mounjaro", "Eliquis"]) else all_drugs[:3],
        max_selections=5
    )

    if selected_drugs:
        comparison_df = (
            filtered[filtered["Brnd_Name"].isin(selected_drugs)]
            .drop_duplicates(subset=["Brnd_Name"])
            [["Brnd_Name", "Gnrc_Name", "Tot_Spndng", "Tot_Benes", "Avg_Spnd_Per_Bene"]]
            .copy()
        )
        comparison_df["Total Spending ($B)"] = (comparison_df["Tot_Spndng"] / 1e9).round(2)
        comparison_df["Beneficiaries (M)"] = (comparison_df["Tot_Benes"] / 1e6).round(2)
        comparison_df["Avg/Patient ($)"] = comparison_df["Avg_Spnd_Per_Bene"].round(0).apply(lambda x: f"${x:,.0f}")
        comparison_df = comparison_df.rename(columns={"Brnd_Name": "Brand", "Gnrc_Name": "Generic"})

        comparison_display = comparison_df[["Brand", "Generic", "Total Spending ($B)", "Beneficiaries (M)", "Avg/Patient ($)"]]
        st.dataframe(
            comparison_display,
            use_container_width=True,
            hide_index=True
        )
        st.download_button(
            "📥 Download Comparison as CSV",
            data=comparison_display.to_csv(index=False).encode("utf-8"),
            file_name=f"drug_comparison_{selected_year}.csv",
            mime="text/csv",
            key="dl_drug_comparison",
        )

        fig5 = px.bar(
            comparison_df,
            x="Brand",
            y="Total Spending ($B)",
            color="Brand",
            text="Total Spending ($B)",
            color_discrete_sequence=px.colors.qualitative.Set1
        )
        fig5.update_traces(texttemplate="%{text}B", textposition="outside")
        fig5.update_layout(showlegend=False)
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("Select at least one drug above to compare.")

    st.divider()

    # Year-over-year % change
    st.subheader("📈 Fastest Growing Drugs (Year-over-Year)")
    st.markdown("Drugs with the biggest spending increase from 2024 to 2025.")
    st.caption("⚠️ Note: 2025 data covers Q1-Q2 only. Growth rates may be understated compared to full-year 2024.")

    yoy_df = df.groupby(["Brnd_Name", "Year"])["Tot_Spndng"].sum().reset_index()
    pivot = yoy_df.pivot(index="Brnd_Name", columns="Year", values="Tot_Spndng").reset_index()
    pivot.columns.name = None

    years = sorted(df["Year"].unique().tolist())
    if len(years) >= 2:
        col_2024 = years[0]
        col_2025 = years[1]
        pivot = pivot.dropna(subset=[col_2024, col_2025])
        pivot = pivot[pivot[col_2024] >= 1e8]  # minimum $100M in 2024 to qualify
        pivot["YoY_%"] = ((pivot[col_2025] - pivot[col_2024]) / pivot[col_2024] * 100).round(1)

        top_growers = pivot.nlargest(10, "YoY_%")[["Brnd_Name", col_2024, col_2025, "YoY_%"]].copy()
        top_growers[col_2024] = (top_growers[col_2024] / 1e9).round(2)
        top_growers[col_2025] = (top_growers[col_2025] / 1e9).round(2)
        top_growers.columns = ["Drug", "2024 ($B)", "2025 ($B)", "Growth %"]

        fig6 = px.bar(
            top_growers,
            x="Growth %",
            y="Drug",
            orientation="h",
            text="Growth %",
            color="Growth %",
            color_continuous_scale="Greens"
        )
        fig6.update_traces(texttemplate="%{text}%", textposition="outside")
        fig6.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig6, use_container_width=True)
        st.dataframe(top_growers, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download Top Growers as CSV",
            data=top_growers.to_csv(index=False).encode("utf-8"),
            file_name=f"top_growers_{col_2024}_to_{col_2025}.csv",
            mime="text/csv",
            key="dl_top_growers",
        )
    else:
        st.info("Need at least 2 years of data for year-over-year comparison.")

    st.divider()

    # Generic vs Brand
    st.subheader("💊 Brand vs Generic Spending")
    st.markdown("Generic drugs are chemically identical to brands but cost significantly less.")

    filtered = filtered.copy()
    filtered["Drug_Type"] = filtered.apply(
        lambda row: "Generic" if str(row["Brnd_Name"]).strip().lower() == str(row["Gnrc_Name"]).strip().lower() else "Brand",
        axis=1
    )

    type_summary = filtered.groupby("Drug_Type")["Tot_Spndng"].sum().reset_index()
    type_summary["Spending_B"] = (type_summary["Tot_Spndng"] / 1e9).round(1)

    fig4 = px.pie(
        type_summary,
        values="Spending_B",
        names="Drug_Type",
        color_discrete_sequence=["#2196F3", "#4CAF50"]
    )
    st.plotly_chart(fig4, use_container_width=True, height=400)

with tab3:
    # Affordability Section
    st.subheader("💰 Most Expensive Drugs Per Beneficiary")
    st.markdown("Total spending can be misleading — this shows the average cost per patient.")

    df["Avg_Spnd_Per_Bene"] = pd.to_numeric(df["Avg_Spnd_Per_Bene"], errors="coerce")

    afford = (
        filtered[filtered["Tot_Benes"] >= 100]  # filter out tiny sample sizes
        .groupby("Brnd_Name")["Avg_Spnd_Per_Bene"]
        .mean()
        .nlargest(10)
        .reset_index()
    )
    afford["Avg_Spnd_Per_Bene"] = afford["Avg_Spnd_Per_Bene"].round(0)

    fig3 = px.bar(
        afford,
        x="Avg_Spnd_Per_Bene",
        y="Brnd_Name",
        orientation="h",
        labels={"Avg_Spnd_Per_Bene": "Avg Spend Per Beneficiary ($)", "Brnd_Name": "Drug"},
        color="Avg_Spnd_Per_Bene",
        color_continuous_scale="Reds",
        text="Avg_Spnd_Per_Bene"
    )
    fig3.update_traces(texttemplate="$%{text:,.0f}", textposition="outside")
    fig3.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig3, use_container_width=True, height=400)

    st.divider()

    # Anomaly Detection
    st.subheader("🚨 Spending Anomalies")
    st.markdown("Drugs with unusually high spending relative to the number of beneficiaries they serve.")

    df["Avg_Spnd_Per_Bene"] = pd.to_numeric(df["Avg_Spnd_Per_Bene"], errors="coerce")
    df["Tot_Spndng"] = pd.to_numeric(df["Tot_Spndng"], errors="coerce")

    anomaly_df = filtered[
        (filtered["Tot_Benes"] >= 100) &
        (filtered["Tot_Spndng"] >= 1e7)
    ].copy()

    anomaly_df = anomaly_df.drop_duplicates(subset=["Brnd_Name"])

    mean_spend = anomaly_df["Avg_Spnd_Per_Bene"].mean()
    std_spend = anomaly_df["Avg_Spnd_Per_Bene"].std()
    threshold = mean_spend + (2 * std_spend)

    anomalies = anomaly_df[anomaly_df["Avg_Spnd_Per_Bene"] > threshold].copy()
    anomalies = anomalies.sort_values("Avg_Spnd_Per_Bene", ascending=False).head(10)

    if not anomalies.empty:
        st.warning(f"⚠️ Found **{len(anomalies)}** drugs with spending more than 2 standard deviations above average (threshold: **${threshold:,.0f}**/patient)")

        anomalies["Avg_Spnd_Per_Bene"] = anomalies["Avg_Spnd_Per_Bene"].round(0)
        anomalies["Tot_Spndng_B"] = (anomalies["Tot_Spndng"] / 1e9).round(2)

        fig8 = px.scatter(
            anomalies,
            x="Tot_Benes",
            y="Avg_Spnd_Per_Bene",
            size="Tot_Spndng_B",
            color="Brnd_Name",
            hover_name="Brnd_Name",
            labels={
                "Tot_Benes": "Number of Beneficiaries",
                "Avg_Spnd_Per_Bene": "Avg Spend Per Patient ($)",
                "Tot_Spndng_B": "Total Spending ($B)"
            },
            color_discrete_sequence=px.colors.qualitative.Set1
        )
        fig8.add_hline(
            y=threshold,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Anomaly threshold: ${threshold:,.0f}",
            annotation_position="top right"
        )
        st.plotly_chart(fig8, use_container_width=True)

        display_anomalies = anomalies[["Brnd_Name", "Gnrc_Name", "Tot_Spndng_B", "Tot_Benes", "Avg_Spnd_Per_Bene"]].copy()
        display_anomalies.columns = ["Brand", "Generic", "Total Spending ($B)", "Beneficiaries", "Avg/Patient ($)"]
        display_anomalies["Avg/Patient ($)"] = display_anomalies["Avg/Patient ($)"].apply(lambda x: f"${x:,.0f}")
        st.dataframe(display_anomalies, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download Anomalies as CSV",
            data=display_anomalies.to_csv(index=False).encode("utf-8"),
            file_name=f"spending_anomalies_{selected_year}.csv",
            mime="text/csv",
            key="dl_anomalies",
        )
    else:
        st.success("No significant spending anomalies detected in the current selection.")

    st.divider()

    # Top Manufacturers
    st.subheader("🏭 Top Drug Manufacturers by Medicare Spending")
    st.markdown("Which pharmaceutical companies collect the most Medicare Part D dollars.")

    df["Tot_Mftr"] = pd.to_numeric(df["Tot_Mftr"], errors="coerce")

    mftr_col = "Mftr_Name" if "Mftr_Name" in filtered.columns else None

    total_mftr_spend = filtered[~filtered[mftr_col].str.contains("Overall", case=False, na=False)]["Tot_Spndng"].sum()
    st.info(f"💊 Total Medicare Part D spending across all manufacturers in {selected_year}: **${total_mftr_spend/1e9:.1f}B**")

    if mftr_col:
        top_mftr = (
        filtered[~filtered[mftr_col].str.contains("Overall", case=False, na=False)]
        .groupby(mftr_col)["Tot_Spndng"]
        .sum()
        .nlargest(10)
        .reset_index()
        )
        top_mftr["Spending_B"] = (top_mftr["Tot_Spndng"] / 1e9).round(2)
        top_mftr.columns = ["Manufacturer", "Tot_Spndng", "Spending ($B)"]

        fig7 = px.bar(
            top_mftr,
            x="Spending ($B)",
            y="Manufacturer",
            orientation="h",
            text="Spending ($B)",
            color="Spending ($B)",
            color_continuous_scale="Purples"
        )
        fig7.update_traces(texttemplate="%{text}B", textposition="outside")
        fig7.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig7, use_container_width=True)
    else:
        st.info("Manufacturer data not available in current dataset.")

with tab4:
    # Part B Section
    st.subheader("💉 Medicare Part B — Doctor-Administered Drugs")
    st.markdown("Part B covers drugs administered in doctors offices and outpatient settings — different from Part D pharmacy drugs.")

    with st.spinner("Loading Part B data..."):
        df_b = fetch_part_b_data()

    # Clean and reshape Part B - it has yearly columns not rows
    spend_cols = [c for c in df_b.columns if c.startswith("Tot_Spndng_")]
    bene_cols = [c for c in df_b.columns if c.startswith("Tot_Benes_")]

    # Get most recent year available (2023)
    df_b["Tot_Spndng"] = pd.to_numeric(df_b["Tot_Spndng_2023"], errors="coerce")
    df_b["Tot_Benes"] = pd.to_numeric(df_b["Tot_Benes_2023"], errors="coerce")
    df_b = df_b.dropna(subset=["Tot_Spndng"])

    # Metrics
    col_b1, col_b2, col_b3 = st.columns(3)
    col_b1.metric("Part B Drugs", f"{df_b['Brnd_Name'].nunique():,}")
    col_b2.metric("Total Part B Spending (2023)", f"${df_b['Tot_Spndng'].sum()/1e9:.1f}B")
    col_b3.metric("Total Beneficiaries", f"{df_b['Tot_Benes'].sum()/1e6:.1f}M")

    # Top 10 Part B drugs
    top_b = df_b.groupby("Brnd_Name")["Tot_Spndng"].sum().nlargest(10).reset_index()
    top_b["Spending_B"] = (top_b["Tot_Spndng"] / 1e9).round(2)

    fig_b = px.bar(
        top_b,
        x="Spending_B",
        y="Brnd_Name",
        orientation="h",
        text="Spending_B",
        color="Spending_B",
        color_continuous_scale="Oranges",
        labels={"Spending_B": "Total Spending ($B)", "Brnd_Name": "Drug"}
    )
    fig_b.update_traces(texttemplate="%{text}B", textposition="outside")
    fig_b.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig_b, use_container_width=True)

    # Part B vs Part D comparison - drugs in both
    st.subheader("🔗 Drugs Appearing in Both Part B and Part D")
    st.markdown("These drugs are prescribed at pharmacies AND administered in clinical settings.")

    part_d_drugs = set(df["Brnd_Name"].dropna().unique())
    part_b_drugs = set(df_b["Brnd_Name"].dropna().unique())
    overlap = part_d_drugs.intersection(part_b_drugs)

    if overlap:
        overlap_d = df[df["Brnd_Name"].isin(overlap)].groupby("Brnd_Name")["Tot_Spndng"].sum().reset_index()
        overlap_b = df_b[df_b["Brnd_Name"].isin(overlap)].groupby("Brnd_Name")["Tot_Spndng"].sum().reset_index()
        overlap_merged = overlap_d.merge(overlap_b, on="Brnd_Name", suffixes=("_PartD", "_PartB"))
        overlap_merged["Total_Combined"] = overlap_merged["Tot_Spndng_PartD"] + overlap_merged["Tot_Spndng_PartB"]
        overlap_merged = overlap_merged.nlargest(10, "Total_Combined")
        overlap_merged["Part D ($B)"] = (overlap_merged["Tot_Spndng_PartD"] / 1e9).round(2)
        overlap_merged["Part B ($B)"] = (overlap_merged["Tot_Spndng_PartB"] / 1e9).round(2)

        fig_overlap = px.bar(
            overlap_merged,
            x="Brnd_Name",
            y=["Part D ($B)", "Part B ($B)"],
            barmode="group",
            labels={"Brnd_Name": "Drug", "value": "Spending ($B)"},
            color_discrete_map={"Part D ($B)": "#2196F3", "Part B ($B)": "#FF9800"}
        )
        st.plotly_chart(fig_overlap, use_container_width=True)
        st.caption(f"Found {len(overlap):,} drugs appearing in both Part B and Part D datasets.")
    else:
        st.info("No overlapping drugs found between Part B and Part D.")

with tab5:
    st.subheader("🗺️ Medicare Spending by State")
    st.markdown("Medicare Fee-for-Service spending by state, from the CMS Geographic Variation Public Use File.")

    with st.spinner("Loading Geographic Variation data..."):
        df_geo = load_geo_variation()

    col_yr, col_view = st.columns([1, 2])
    geo_years = sorted(df_geo["YEAR"].unique().tolist())
    default_idx = geo_years.index(2022) if 2022 in geo_years else len(geo_years) - 1
    geo_year = col_yr.selectbox("Year", geo_years, index=default_idx, key="geo_year")
    view_mode = col_view.radio(
        "View",
        ["Total Spending", "Per Beneficiary"],
        horizontal=True,
        key="geo_view",
    )

    # 50 states + DC (drop PR, VI, Territory, ZZ aggregates that don't render in USA-states)
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
        metric_col = "Spending_B"
        metric_label = "Spending ($B)"
        color_scale = "Blues"
        hover_fmt = ":.2f"
        bar_text_template = "$%{text}B"
    else:
        metric_col = "TOT_MDCR_PYMT_PC"
        metric_label = "Spending per Beneficiary ($)"
        color_scale = "Reds"
        hover_fmt = ":$,.0f"
        bar_text_template = "$%{text:,.0f}"

    fig_map = px.choropleth(
        state_df,
        locations="BENE_GEO_DESC",
        locationmode="USA-states",
        color=metric_col,
        scope="usa",
        color_continuous_scale=color_scale,
        labels={metric_col: metric_label, "BENE_GEO_DESC": "State"},
        hover_name="BENE_GEO_DESC",
        hover_data={metric_col: hover_fmt, "BENE_GEO_DESC": False},
    )
    fig_map.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    st.plotly_chart(fig_map, use_container_width=True)

    col_g1, col_g2, col_g3 = st.columns(3)
    if view_mode == "Total Spending":
        col_g1.metric("Total FFS Spending", f"${state_df['TOT_MDCR_PYMT_AMT'].sum()/1e9:.1f}B")
        top_state = state_df.loc[state_df["TOT_MDCR_PYMT_AMT"].idxmax()]
        bottom_state = state_df.loc[state_df["TOT_MDCR_PYMT_AMT"].idxmin()]
        col_g2.metric("Highest Spend State", top_state["BENE_GEO_DESC"], f"${top_state['Spending_B']:.1f}B")
        col_g3.metric("Lowest Spend State", bottom_state["BENE_GEO_DESC"], f"${bottom_state['Spending_B']:.2f}B")
    else:
        col_g1.metric("National Avg / Beneficiary", f"${state_df['TOT_MDCR_PYMT_PC'].mean():,.0f}")
        top_state = state_df.loc[state_df["TOT_MDCR_PYMT_PC"].idxmax()]
        bottom_state = state_df.loc[state_df["TOT_MDCR_PYMT_PC"].idxmin()]
        col_g2.metric("Highest per Beneficiary", top_state["BENE_GEO_DESC"], f"${top_state['TOT_MDCR_PYMT_PC']:,.0f}")
        col_g3.metric("Lowest per Beneficiary", bottom_state["BENE_GEO_DESC"], f"${bottom_state['TOT_MDCR_PYMT_PC']:,.0f}")

    st.divider()

    st.subheader(f"Top 10 States — {view_mode} ({geo_year})")
    top10_states = state_df.nlargest(10, metric_col)[["BENE_GEO_DESC", metric_col]].copy()
    top10_states[metric_col] = top10_states[metric_col].round(2)
    fig_bar_states = px.bar(
        top10_states,
        x=metric_col,
        y="BENE_GEO_DESC",
        orientation="h",
        labels={metric_col: metric_label, "BENE_GEO_DESC": "State"},
        color=metric_col,
        color_continuous_scale=color_scale,
        text=metric_col,
    )
    fig_bar_states.update_traces(texttemplate=bar_text_template, textposition="outside")
    fig_bar_states.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
    st.plotly_chart(fig_bar_states, use_container_width=True)

    st.caption("Source: CMS Medicare Geographic Variation PUF. Total = TOT_MDCR_PYMT_AMT; Per Beneficiary = TOT_MDCR_PYMT_PC (FFS beneficiaries, all ages).")

    st.divider()

    # === Workforce Supply (HRSA AHRF) ===
    st.subheader("👩‍⚕️ Healthcare Workforce Supply per 100k Population")
    st.markdown("Active physicians, registered nurses, and dentists per 100k residents. Top 15 states by population.")

    with st.spinner("Loading HRSA AHRF data..."):
        df_ahrf = load_ahrf()

    states_only = df_ahrf[df_ahrf["st_abbrev"] != "US"].copy()
    for c in ["phys_wkforc_23", "rn_23", "dent_23", "popn_pums_23"]:
        states_only[c] = pd.to_numeric(states_only[c], errors="coerce")
    states_only["Physicians"] = states_only["phys_wkforc_23"] / states_only["popn_pums_23"] * 1e5
    states_only["Registered Nurses"] = states_only["rn_23"] / states_only["popn_pums_23"] * 1e5
    states_only["Dentists"] = states_only["dent_23"] / states_only["popn_pums_23"] * 1e5

    top15_pop = states_only.nlargest(15, "popn_pums_23")[
        ["st_abbrev", "Physicians", "Registered Nurses", "Dentists"]
    ].copy()
    workforce_long = top15_pop.melt(
        id_vars="st_abbrev",
        value_vars=["Physicians", "Registered Nurses", "Dentists"],
        var_name="Profession",
        value_name="Per 100k",
    )
    workforce_long["Per 100k"] = workforce_long["Per 100k"].round(1)

    fig_workforce = px.bar(
        workforce_long,
        x="st_abbrev",
        y="Per 100k",
        color="Profession",
        barmode="group",
        labels={"st_abbrev": "State", "Per 100k": "Workforce per 100k"},
        color_discrete_sequence=["#1f77b4", "#2ca02c", "#ff7f0e"],
    )
    fig_workforce.update_layout(xaxis={"categoryorder": "array", "categoryarray": top15_pop["st_abbrev"].tolist()})
    st.plotly_chart(fig_workforce, use_container_width=True)
    st.caption("Source: HRSA Area Health Resources File (AHRF) state+national 2024-2025. Workforce: phys_wkforc_23 (active physicians), rn_23, dent_23. Population: popn_pums_23 (ACS PUMS). States ranked by population.")

    st.divider()

    # === Provider Shortage (HRSA HPSA) ===
    st.subheader("🚨 Provider Shortage — Practitioners Needed by State")
    st.markdown("FTE practitioners needed across designated Health Professional Shortage Areas (HPSAs), by discipline. Top 15 states by total need.")

    with st.spinner("Loading HRSA HPSA data..."):
        df_hpsa = load_hpsa()

    df_hpsa["HPSA Shortage"] = pd.to_numeric(df_hpsa["HPSA Shortage"], errors="coerce")
    rollup = (
        df_hpsa.groupby(["State Abbreviation", "Discipline"])["HPSA Shortage"]
        .sum()
        .unstack(fill_value=0)
    )
    rollup["Total"] = rollup.sum(axis=1)
    top15_shortage = rollup.nlargest(15, "Total").drop(columns="Total").reset_index()

    shortage_long = top15_shortage.melt(
        id_vars="State Abbreviation",
        var_name="Discipline",
        value_name="Practitioners Needed",
    )
    shortage_long["Practitioners Needed"] = shortage_long["Practitioners Needed"].round(0)

    fig_shortage = px.bar(
        shortage_long,
        x="State Abbreviation",
        y="Practitioners Needed",
        color="Discipline",
        barmode="group",
        labels={"State Abbreviation": "State"},
        color_discrete_map={
            "Primary Care": "#d62728",
            "Dental": "#9467bd",
            "Mental Health": "#8c564b",
        },
    )
    fig_shortage.update_layout(xaxis={"categoryorder": "array", "categoryarray": top15_shortage["State Abbreviation"].tolist()})
    st.plotly_chart(fig_shortage, use_container_width=True)
    st.caption("Source: HRSA HPSA designations (BCD_HPSA_FCT_DET), filtered to HPSA Status = 'Designated'. 'Practitioners Needed' = sum of HPSA Shortage (FTEs to reach target ratio). NY is an outlier (~96k total) due to many population-type designations in NYC.")

    st.divider()

    # === State Risk Index (composite of 7 dimensions) ===
    st.subheader("🎯 State Risk Index")
    st.markdown(
        "Composite healthcare risk score across 7 dimensions, percentile-ranked 0–100. "
        "Higher score = greater risk."
    )

    df_risk = pd.read_csv("data/state_risk_index.csv")

    col_r1, col_r2, col_r3 = st.columns(3)
    highest = df_risk.iloc[df_risk["risk_score"].idxmax()]
    lowest = df_risk.iloc[df_risk["risk_score"].idxmin()]
    col_r1.metric("Highest Risk State", highest["state"], f"{highest['risk_score']:.1f}")
    col_r2.metric("Lowest Risk State", lowest["state"], f"{lowest['risk_score']:.1f}")
    col_r3.metric("National Average", f"{df_risk['risk_score'].mean():.1f}")

    # Choropleth — State Healthcare Risk Map
    st.markdown("**State Healthcare Risk Map**")
    fig_risk_map = px.choropleth(
        df_risk,
        locations="state_abbr",
        locationmode="USA-states",
        color="risk_score",
        scope="usa",
        color_continuous_scale="RdYlGn_r",
        range_color=(0, 100),
        labels={"risk_score": "Risk Score"},
        hover_name="state",
        hover_data={
            "risk_score": ":.1f",
            "risk_tier": True,
            "dim_spending": ":.1f",
            "dim_supply": ":.1f",
            "dim_shortage": ":.1f",
            "dim_disease": ":.1f",
            "dim_insurance": ":.1f",
            "dim_hospital_quality": ":.1f",
            "dim_poverty": ":.1f",
            "state_abbr": False,
        },
    )
    fig_risk_map.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    st.plotly_chart(fig_risk_map, use_container_width=True)

    tier_colors = {"High": "#d62728", "Medium": "#ff9800", "Low": "#2ca02c"}
    df_risk_sorted = df_risk.sort_values("risk_score", ascending=True).copy()
    df_risk_sorted["risk_score_display"] = df_risk_sorted["risk_score"].round(1)

    fig_risk = px.bar(
        df_risk_sorted,
        x="risk_score",
        y="state_abbr",
        orientation="h",
        color="risk_tier",
        color_discrete_map=tier_colors,
        category_orders={
            "state_abbr": df_risk_sorted["state_abbr"].tolist(),
            "risk_tier": ["High", "Medium", "Low"],
        },
        labels={"risk_score": "Risk Score (0–100)", "state_abbr": "State", "risk_tier": "Tier"},
        hover_name="state",
        hover_data={
            "risk_score_display": ":.1f",
            "risk_rank": True,
            "risk_tier": True,
            "state_abbr": False,
            "risk_score": False,
        },
        text="risk_score_display",
    )
    fig_risk.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    fig_risk.update_layout(height=950, margin={"l": 0, "r": 40, "t": 10, "b": 10})
    st.plotly_chart(fig_risk, use_container_width=True)

    st.markdown("**All states — dimension scores and tier:**")
    table_df = df_risk[
        [
            "state", "state_abbr",
            "dim_spending", "dim_supply", "dim_shortage", "dim_disease",
            "dim_insurance", "dim_hospital_quality", "dim_poverty",
            "risk_score", "risk_rank", "risk_tier",
        ]
    ].copy()
    table_df.columns = [
        "State", "Abbr",
        "Spending", "Supply", "Shortage", "Disease",
        "Insurance", "Hosp. Quality", "Poverty",
        "Risk Score", "Rank", "Tier",
    ]
    for c in ["Spending", "Supply", "Shortage", "Disease", "Insurance", "Hosp. Quality", "Poverty", "Risk Score"]:
        table_df[c] = table_df[c].round(1)
    table_df_sorted = table_df.sort_values("Rank")
    st.dataframe(
        table_df_sorted,
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "📥 Download State Risk Index as CSV",
        data=table_df_sorted.to_csv(index=False).encode("utf-8"),
        file_name="state_risk_index.csv",
        mime="text/csv",
        key="dl_state_risk",
    )

    st.caption(
        "Methodology: 7 dimensions percentile-ranked 0–100 across the 51 jurisdictions, then averaged with "
        "equal weights. Higher = worse outcome. Dimensions: **Spending** (Medicare standardized payment per "
        "beneficiary, 2023) · **Supply** (active physicians per 100k, AHRF 2023, inverted) · **Shortage** (HPSA "
        "primary-care score weighted by FTEs needed) · **Disease** (mean of diabetes + obesity + CHD prevalence "
        "from BRFSS, most-recent year per state) · **Insurance** (% uninsured all-income, SAHIE) · "
        "**Hospital Quality** (mean overall star rating, inverted) · **Poverty** (poverty rate all ages, SAIPE)."
    )

with tab6:
    st.subheader("🔍 Compare States")
    st.markdown(
        "Side-by-side comparison of any two states across the 7 healthcare risk dimensions. "
        "Higher dimension scores indicate worse outcomes."
    )

    df_cmp = pd.read_csv("data/state_risk_index.csv")
    state_options = df_cmp.sort_values("state")["state"].tolist()

    DIM_COLS = [
        "dim_spending", "dim_supply", "dim_shortage", "dim_disease",
        "dim_insurance", "dim_hospital_quality", "dim_poverty",
    ]
    DIM_LABELS = {
        "dim_spending": "Spending",
        "dim_supply": "Supply",
        "dim_shortage": "Shortage",
        "dim_disease": "Disease",
        "dim_insurance": "Insurance",
        "dim_hospital_quality": "Hospital Quality",
        "dim_poverty": "Poverty",
    }

    col_a, col_b = st.columns(2)
    default_a = state_options.index("Mississippi") if "Mississippi" in state_options else 0
    default_b = state_options.index("Massachusetts") if "Massachusetts" in state_options else 1
    state_a = col_a.selectbox("State A", state_options, index=default_a, key="cmp_state_a")
    state_b = col_b.selectbox("State B", state_options, index=default_b, key="cmp_state_b")

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
            r=vals_a + [vals_a[0]],
            theta=labels + [labels[0]],
            fill="toself",
            name=state_a,
            line=dict(color="#d62728"),
        ))
        fig_radar.add_trace(go.Scatterpolar(
            r=vals_b + [vals_b[0]],
            theta=labels + [labels[0]],
            fill="toself",
            name=state_b,
            line=dict(color="#1f77b4"),
        ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True,
            height=500,
            margin={"l": 0, "r": 0, "t": 30, "b": 0},
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
            key="dl_state_compare",
        )

        # Plain-English summary
        THRESHOLD = 5  # percentile points to count as a meaningful gap
        worse, better = [], []
        for col, label in zip(DIM_COLS, labels):
            diff = row_a[col] - row_b[col]
            if diff >= THRESHOLD:
                worse.append(label)
            elif diff <= -THRESHOLD:
                better.append(label)

        composite_diff = row_a["risk_score"] - row_b["risk_score"]
        if composite_diff > 0:
            headline = f"Overall, **{state_a}** has higher healthcare risk than **{state_b}** (risk score {row_a['risk_score']:.1f} vs {row_b['risk_score']:.1f})."
        elif composite_diff < 0:
            headline = f"Overall, **{state_a}** has lower healthcare risk than **{state_b}** (risk score {row_a['risk_score']:.1f} vs {row_b['risk_score']:.1f})."
        else:
            headline = f"**{state_a}** and **{state_b}** have nearly identical composite risk scores."

        parts = [headline]
        if worse:
            parts.append(f"{state_a} scores **worse** than {state_b} on: " + ", ".join(worse) + ".")
        if better:
            parts.append(f"{state_a} scores **better** than {state_b} on: " + ", ".join(better) + ".")
        if not worse and not better:
            parts.append("No dimensions show a meaningful gap (≥5 percentile points) between the two states.")
        st.markdown(" ".join(parts))

        st.caption(
            "Reminder: each dimension is percentile-ranked 0–100 across all 51 jurisdictions, with higher = "
            "worse outcome. A 5-point gap is the threshold for calling out a difference."
        )

with tab7:
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
            "`GROQ_API_KEY`, `GEMINI_API_KEY`, or `TOGETHER_API_KEY` to "
            "`.streamlit/secrets.toml` (see `secrets.toml.example`)."
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
        st.session_state.ai_history = []  # list of dicts: {q, a, provider, seconds}

    def _set_question(q: str):
        st.session_state.ai_question_input = q

    st.markdown("**Example questions** (click to populate):")
    btn_cols = st.columns(2)
    for i, eq in enumerate(EXAMPLE_QUESTIONS):
        btn_cols[i % 2].button(
            eq,
            key=f"ai_example_{i}",
            on_click=_set_question,
            args=(eq,),
            use_container_width=True,
        )

    question = st.text_area(
        "Your question",
        key="ai_question_input",
        height=80,
        placeholder="Ask anything about the 81 datasets…",
    )

    submit = st.button("🔍 Ask the analyst", type="primary", disabled=(active is None))

    if submit and question.strip():
        with st.spinner("Thinking…"):
            t0 = time.time()
            try:
                response, provider_used, ctx_chars, route_label = query_analyst(question.strip())
                elapsed = time.time() - t0
                st.session_state.ai_history.insert(0, {
                    "q": question.strip(),
                    "a": response,
                    "provider": provider_used,
                    "seconds": elapsed,
                    "ctx_chars": ctx_chars,
                    "route": route_label,
                })
                st.session_state.ai_history = st.session_state.ai_history[:5]
            except RuntimeError as e:
                st.error(str(e))

    if st.session_state.ai_history:
        latest = st.session_state.ai_history[0]
        st.markdown("### Response")
        st.info(f"📊 **Routing:** {latest.get('route', 'n/a')}")
        with st.container(border=True):
            st.markdown(latest["a"])
        st.caption(
            f"Answered by **{PROVIDER_LABELS.get(latest['provider'], latest['provider'])}** "
            f"in {latest['seconds']:.1f}s · context {latest.get('ctx_chars', 0):,} chars."
        )

        if len(st.session_state.ai_history) > 1:
            st.divider()
            st.markdown("### Recent questions")
            for i, item in enumerate(st.session_state.ai_history[1:], start=1):
                with st.expander(f"{i}. {item['q']}", expanded=False):
                    st.markdown(item["a"])
                    st.caption(
                        f"{PROVIDER_LABELS.get(item['provider'], item['provider'])} · "
                        f"{item['seconds']:.1f}s · "
                        f"{item.get('ctx_chars', 0):,} chars · "
                        f"{item.get('route', '').split(' · ')[0] if item.get('route') else ''}"
                    )

with tab8:
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
    year_end_max = min(int(df_sources["year_end"].max()), 2026)  # cap at present
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    col_k1.metric("Total Datasets", f"{len(df_sources):,}")
    col_k2.metric("Total Rows", f"~{total_rows / 1e6:.1f}M")
    col_k3.metric("Agencies", f"{df_sources['agency'].nunique()}")
    col_k4.metric("Year Span", f"{year_start_min}–{year_end_max}")

    st.divider()

    # Filters: free-text search + single-select category dropdown
    col_f1, col_f2 = st.columns([2, 1])
    search_q = col_f1.text_input(
        "Search (matches name, agency, or category)",
        "",
        key="ds_search",
    )
    category_choice = col_f2.selectbox(
        "Category",
        options=["All"] + sorted(df_sources["category"].unique().tolist()),
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

    display = filtered_sources[
        ["name", "agency", "category", "year_range", "granularity", "rows", "description"]
    ].rename(columns={
        "name": "Dataset",
        "agency": "Agency",
        "category": "Category",
        "year_range": "Year Range",
        "granularity": "Granularity",
        "rows": "Rows",
        "description": "Description",
    })
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rows": st.column_config.NumberColumn("Rows", format="%d"),
            "Description": st.column_config.TextColumn("Description", width="large"),
        },
    )
    st.download_button(
        "📥 Download Data Sources as CSV",
        data=display.to_csv(index=False).encode("utf-8"),
        file_name="data_sources.csv",
        mime="text/csv",
        key="dl_data_sources",
    )

    st.caption(
        "Inventory is hand-curated from `data/MANIFEST.md`. Year ranges marked 'Current' or 'Multi-year' use a "
        "best estimate of the dataset's coverage window for the year-span KPI. Row counts reflect the cleaned "
        "files on disk at fetch time."
    )
