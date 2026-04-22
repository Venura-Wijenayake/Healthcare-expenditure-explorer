import streamlit as st
import pandas as pd
import plotly.express as px
from data_loader import fetch_part_d_data

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

st.divider()

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

# US State Map (placeholder - state data coming in Phase 2)
st.subheader("🗺️ Medicare Spending by State")
st.info("🚧 State-level geographic data pipeline in progress — coming in next update.")