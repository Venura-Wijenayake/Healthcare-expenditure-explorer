import streamlit as st
import pandas as pd
import plotly.express as px
from data_loader import fetch_part_d_data, fetch_part_b_data

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
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Overview",
    "💊 Drug Analysis",
    "💰 Spending Deep Dive",
    "💉 Part B",
    "🗺️ Geography"
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

        st.dataframe(
            comparison_df[["Brand", "Generic", "Total Spending ($B)", "Beneficiaries (M)", "Avg/Patient ($)"]],
            use_container_width=True,
            hide_index=True
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
    # US State Map (placeholder - state data coming in Phase 2)
    st.subheader("🗺️ Medicare Spending by State")
    st.info("🚧 State-level geographic data pipeline in progress — coming in next update.")
