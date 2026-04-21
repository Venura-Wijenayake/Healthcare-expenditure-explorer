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
st.plotly_chart(fig, use_container_width=True)

# Raw data table
if search_term:
    st.divider()
    st.subheader(f"Search Results for '{search_term}'")
    st.dataframe(
        filtered[["Brnd_Name", "Gnrc_Name", "Tot_Spndng", "Tot_Benes", "Avg_Spnd_Per_Bene", "Year"]]
        .sort_values("Tot_Spndng", ascending=False)
        .head(50),
        use_container_width=True
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
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No GLP-1 data found.")