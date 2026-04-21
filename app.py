import streamlit as st
import pandas as pd
import plotly.express as px
from data_loader import fetch_part_d_data

# Page config
st.set_page_config(
    page_title="U.S. Healthcare Expenditure Explorer",
    page_icon="🏥",
    layout="wide"
)

# Header
st.title("🏥 U.S. Healthcare Expenditure Explorer")
st.markdown("Exploring Medicare drug and equipment spending across the United States.")

# Load data
with st.spinner("Loading Medicare Part D data..."):
    df = fetch_part_d_data()

# Clean spending column
df["Tot_Spndng"] = pd.to_numeric(df["Tot_Spndng"], errors="coerce")
df["Tot_Benes"] = pd.to_numeric(df["Tot_Benes"], errors="coerce")
df = df.dropna(subset=["Tot_Spndng"])

# Metrics row
col1, col2, col3 = st.columns(3)
col1.metric("Total Drugs", f"{df['Brnd_Name'].nunique():,}")
col2.metric("Total Spending", f"${df['Tot_Spndng'].sum()/1e9:.1f}B")
col3.metric("Total Beneficiaries", f"{df['Tot_Benes'].sum()/1e6:.1f}M")

st.divider()

# Top 10 drugs by spending
st.subheader("Top 10 Drugs by Total Spending")
top10 = df.groupby("Brnd_Name")["Tot_Spndng"].sum().nlargest(10).reset_index()
fig = px.bar(top10, x="Tot_Spndng", y="Brnd_Name", orientation="h",
             labels={"Tot_Spndng": "Total Spending ($)", "Brnd_Name": "Drug"},
             color="Tot_Spndng", color_continuous_scale="Blues")
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, use_container_width=True)