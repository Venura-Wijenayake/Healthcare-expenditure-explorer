import pandas as pd
import requests
import os
import zipfile
import io

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# CMS Medicare Part D Spending by Drug - direct CSV download
PART_D_CSV_URL = "https://data.cms.gov/sites/default/files/2026-01/2d43e067-c2f2-4dfd-a991-95655df72052/QDD_PTD_RQ2601_P01_V10_DQT2502_20260106.csv"

def fetch_part_d_data():
    """Load Medicare Part D drug spending data."""
    filepath = os.path.join(DATA_DIR, "part_d.csv")

    if os.path.exists(filepath):
        print("Loading cached Part D data...")
        return pd.read_csv(filepath)

    print("Downloading Part D data from CMS...")
    response = requests.get(PART_D_CSV_URL, timeout=30)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch data: {response.status_code}")

    with open(filepath, "wb") as f:
        f.write(response.content)

    df = pd.read_csv(filepath)
    print(f"Loaded {len(df)} records")
    return df

# CMS Medicare Part B Spending by Drug - drugs administered in doctors offices/outpatient settings
PART_B_CSV_URL = "https://data.cms.gov/sites/default/files/2025-05/f52d5fcd-8d93-481d-9173-6219813e4efb/DSD_PTB_RY25_P06_V10_DYT23_HCPCS-%20250430.csv"

def fetch_part_b_data():
    """Load Medicare Part B drug spending data (administered in doctors offices)."""
    filepath = os.path.join(DATA_DIR, "part_b.csv")

    if os.path.exists(filepath):
        print("Loading cached Part B data...")
        return pd.read_csv(filepath)

    print("Downloading Part B data from CMS...")
    response = requests.get(PART_B_CSV_URL, timeout=30)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch Part B data: {response.status_code}")

    with open(filepath, "wb") as f:
        f.write(response.content)

    df = pd.read_csv(filepath)
    print(f"Loaded {len(df)} Part B records")
    return df


if __name__ == "__main__":
    df_d = fetch_part_d_data()
    print("Part D columns:", df_d.columns.tolist())
    df_b = fetch_part_b_data()
    print("Part B columns:", df_b.columns.tolist())