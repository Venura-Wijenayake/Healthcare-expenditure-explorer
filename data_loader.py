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


# CMS Medicare Geographic Variation by National, State & County
GEO_VARIATION_CSV_URL = "https://data.cms.gov/sites/default/files/2025-03/a40ac71d-9f80-4d99-92d2-fd149433d7d8/2014-2023%20Medicare%20Fee-for-Service%20Geographic%20Variation%20Public%20Use%20File.csv"

def load_geo_variation():
    """Load Medicare FFS geographic variation data (national/state/county, 2014-2023)."""
    filepath = os.path.join(DATA_DIR, "geo_variation_2014_2023.csv")

    if not os.path.exists(filepath):
        print("Downloading Geographic Variation data from CMS...")
        response = requests.get(GEO_VARIATION_CSV_URL, timeout=120)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch Geographic Variation data: {response.status_code}")
        with open(filepath, "wb") as f:
            f.write(response.content)
    else:
        print("Loading cached Geographic Variation data...")

    df = pd.read_csv(filepath, low_memory=False)
    print(f"Loaded {len(df)} Geographic Variation records ({df['YEAR'].min()}-{df['YEAR'].max()})")
    return df


# HRSA Area Health Resources File (state + national, 2024-2025) - workforce supply by profession
AHRF_ZIP_URL = "https://data.hrsa.gov/DataDownload/AHRF/AHRF_SN_2024-2025_CSV.zip"
AHRF_ZIP_MEMBER = "NCHWA-2024-2025+AHRF+SN+CSV/ahrfsn2025.csv"

def load_ahrf():
    """Load HRSA AHRF state+national workforce file (52 rows = 50 states + DC + US, 1448 vars)."""
    filepath = os.path.join(DATA_DIR, "ahrf_state_national_2025.csv")

    if not os.path.exists(filepath):
        print("Downloading AHRF data from HRSA...")
        response = requests.get(AHRF_ZIP_URL, timeout=120)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch AHRF data: {response.status_code}")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            with z.open(AHRF_ZIP_MEMBER) as src, open(filepath, "wb") as dst:
                dst.write(src.read())
    else:
        print("Loading cached AHRF data...")

    df = pd.read_csv(filepath, low_memory=False)
    print(f"Loaded {len(df)} AHRF state rows, {len(df.columns)} columns")
    return df


# HRSA HPSA (Health Professional Shortage Areas) - 3 disciplines, designation-level
HPSA_FILES = {
    "Primary Care":  ("hpsa_primary_care.csv",  "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv"),
    "Dental":        ("hpsa_dental.csv",        "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_DH.csv"),
    "Mental Health": ("hpsa_mental_health.csv", "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_MH.csv"),
}

def load_hpsa():
    """Load HRSA HPSA designations across all 3 disciplines, filtered to currently Designated."""
    frames = []
    for discipline, (fname, url) in HPSA_FILES.items():
        filepath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(filepath):
            print(f"Downloading HPSA {discipline} from HRSA...")
            response = requests.get(url, timeout=300)
            if response.status_code != 200:
                raise Exception(f"Failed to fetch HPSA {discipline}: {response.status_code}")
            with open(filepath, "wb") as f:
                f.write(response.content)
        df = pd.read_csv(filepath, low_memory=False)
        df = df[df["HPSA Status"] == "Designated"].copy()
        df["Discipline"] = discipline
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(combined)} designated HPSAs across {len(HPSA_FILES)} disciplines")
    return combined


if __name__ == "__main__":
    df_d = fetch_part_d_data()
    print("Part D columns:", df_d.columns.tolist())
    df_b = fetch_part_b_data()
    print("Part B columns:", df_b.columns.tolist())
    df_g = load_geo_variation()
    print("Geo Variation shape:", df_g.shape)
    df_a = load_ahrf()
    print("AHRF shape:", df_a.shape)
    df_h = load_hpsa()
    print("HPSA shape:", df_h.shape)