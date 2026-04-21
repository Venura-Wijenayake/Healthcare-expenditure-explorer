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