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


if __name__ == "__main__":
    df = fetch_part_d_data()
    print(df.head())
    print(df.columns.tolist())