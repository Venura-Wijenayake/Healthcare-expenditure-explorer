"""
Fetch CMS Medicare Part D Prescribers - by Provider (DY 2023) and aggregate
to STATE x SPECIALTY. Output: data/cms_partd_prescribers.csv
"""
import os
import sys
import time
import requests
import pandas as pd
import numpy as np

URL = "https://data.cms.gov/sites/default/files/2025-04/750769a3-bb0f-4f05-81dc-7dcb6e105cb0/MUP_DPR_RY25_P04_V10_DY23_NPI.csv"
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "cms_partd_prescribers.csv")
TMP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tmp", "MUP_DPR_RY23_NPI.csv")

os.makedirs(os.path.dirname(TMP_PATH), exist_ok=True)
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)


def download():
    if os.path.exists(TMP_PATH) and os.path.getsize(TMP_PATH) > 100_000_000:
        print(f"Already downloaded: {TMP_PATH} ({os.path.getsize(TMP_PATH)/1e6:.1f} MB)")
        return
    print(f"Streaming download from {URL}")
    t0 = time.time()
    with requests.get(URL, stream=True, timeout=120) as r:
        r.raise_for_status()
        total_mb = int(r.headers.get("Content-Length", 0)) / (1024*1024)
        print(f"Reported size: {total_mb:.1f} MB")
        bytes_done = 0
        with open(TMP_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
                    bytes_done += len(chunk)
                    if bytes_done % (64 * 1024 * 1024) < 8 * 1024 * 1024:
                        print(f"  {bytes_done/1e6:.0f} MB ({(time.time()-t0):.0f}s)")
    print(f"Done. {os.path.getsize(TMP_PATH)/1e6:.1f} MB in {(time.time()-t0):.0f}s")


# Numeric sum cols at provider level -> sum across providers in (state, specialty)
SUM_COLS = [
    "Tot_Clms", "Tot_30day_Fills", "Tot_Drug_Cst", "Tot_Day_Suply", "Tot_Benes",
    "GE65_Tot_Clms", "GE65_Tot_Drug_Cst", "GE65_Tot_Benes",
    "Brnd_Tot_Clms", "Brnd_Tot_Drug_Cst",
    "Gnrc_Tot_Clms", "Gnrc_Tot_Drug_Cst",
    "Othr_Tot_Clms", "Othr_Tot_Drug_Cst",
    "MAPD_Tot_Clms", "MAPD_Tot_Drug_Cst",
    "PDP_Tot_Clms", "PDP_Tot_Drug_Cst",
    "LIS_Tot_Clms", "LIS_Drug_Cst",
    "NonLIS_Tot_Clms", "NonLIS_Drug_Cst",
    "Opioid_Tot_Clms", "Opioid_Tot_Drug_Cst", "Opioid_Tot_Suply", "Opioid_Tot_Benes",
    "Opioid_LA_Tot_Clms", "Opioid_LA_Tot_Drug_Cst", "Opioid_LA_Tot_Benes",
    "Antbtc_Tot_Clms", "Antbtc_Tot_Drug_Cst", "Antbtc_Tot_Benes",
    "Antpsyct_GE65_Tot_Clms", "Antpsyct_GE65_Tot_Drug_Cst", "Antpsyct_GE65_Tot_Benes",
    "Bene_Age_LT_65_Cnt", "Bene_Age_65_74_Cnt", "Bene_Age_75_84_Cnt", "Bene_Age_GT_84_Cnt",
    "Bene_Feml_Cnt", "Bene_Male_Cnt",
    "Bene_Race_Wht_Cnt", "Bene_Race_Black_Cnt", "Bene_Race_Api_Cnt",
    "Bene_Race_Hspnc_Cnt", "Bene_Race_Natind_Cnt", "Bene_Race_Othr_Cnt",
    "Bene_Dual_Cnt", "Bene_Ndual_Cnt",
]

# Weighted-mean cols (weight = Tot_Clms)
WMEAN_COLS = ["Bene_Avg_Age", "Bene_Avg_Risk_Scre", "Opioid_Prscrbr_Rate"]

GROUP_COLS = ["Prscrbr_State_Abrvtn", "Prscrbr_Type"]

USE_COLS = GROUP_COLS + ["PRSCRBR_NPI"] + SUM_COLS + WMEAN_COLS


def aggregate():
    print(f"Streaming-aggregate {TMP_PATH} in chunks...")
    t0 = time.time()
    chunksize = 200_000

    # Per group: dict[(state,spec)] -> dict
    aggs = {}
    chunks_seen = 0
    rows_seen = 0

    reader = pd.read_csv(
        TMP_PATH,
        usecols=lambda c: c in USE_COLS,
        chunksize=chunksize,
        dtype=str,
        low_memory=False,
    )
    for chunk in reader:
        chunks_seen += 1
        rows_seen += len(chunk)
        # Coerce numeric
        for c in SUM_COLS + WMEAN_COLS:
            if c in chunk.columns:
                chunk[c] = pd.to_numeric(chunk[c], errors="coerce")
        # Drop rows with no state or specialty
        chunk = chunk.dropna(subset=GROUP_COLS)
        chunk = chunk[(chunk["Prscrbr_State_Abrvtn"].str.strip() != "") &
                       (chunk["Prscrbr_Type"].str.strip() != "")]

        # Provider count
        chunk["_prov_cnt"] = 1

        # Weighted-mean numerators (val * Tot_Clms)
        weight = chunk["Tot_Clms"].fillna(0)
        for c in WMEAN_COLS:
            chunk[f"_w_{c}"] = chunk[c].fillna(0) * weight
            chunk[f"_wt_{c}"] = weight.where(chunk[c].notna(), 0)

        agg_dict = {c: "sum" for c in SUM_COLS if c in chunk.columns}
        agg_dict["_prov_cnt"] = "sum"
        for c in WMEAN_COLS:
            agg_dict[f"_w_{c}"] = "sum"
            agg_dict[f"_wt_{c}"] = "sum"

        g = chunk.groupby(GROUP_COLS, dropna=False).agg(agg_dict)

        for key, row in g.iterrows():
            if key not in aggs:
                aggs[key] = row.copy()
            else:
                aggs[key] = aggs[key].add(row, fill_value=0)

        if chunks_seen % 5 == 0:
            print(f"  chunk {chunks_seen}, {rows_seen:,} rows, {len(aggs):,} groups, "
                  f"{(time.time()-t0):.0f}s")

    print(f"Total rows: {rows_seen:,}; groups: {len(aggs):,}; {(time.time()-t0):.0f}s")

    # Build output frame
    out = pd.DataFrame.from_dict(aggs, orient="index").reset_index()
    out = out.rename(columns={"level_0": "state", "level_1": "specialty"})
    out = out.rename(columns={"_prov_cnt": "provider_count"})

    # Compute weighted means
    for c in WMEAN_COLS:
        wsum = out[f"_w_{c}"]
        wt = out[f"_wt_{c}"]
        out[c] = np.where(wt > 0, wsum / wt, np.nan)
        out = out.drop(columns=[f"_w_{c}", f"_wt_{c}"])

    # Derived ratios
    out["brand_share_clms"] = np.where(
        out["Tot_Clms"] > 0, out["Brnd_Tot_Clms"] / out["Tot_Clms"], np.nan)
    out["generic_share_clms"] = np.where(
        out["Tot_Clms"] > 0, out["Gnrc_Tot_Clms"] / out["Tot_Clms"], np.nan)
    out["opioid_share_clms"] = np.where(
        out["Tot_Clms"] > 0, out["Opioid_Tot_Clms"] / out["Tot_Clms"], np.nan)
    out["mapd_share_clms"] = np.where(
        out["Tot_Clms"] > 0, out["MAPD_Tot_Clms"] / out["Tot_Clms"], np.nan)
    out["pdp_share_clms"] = np.where(
        out["Tot_Clms"] > 0, out["PDP_Tot_Clms"] / out["Tot_Clms"], np.nan)
    out["lis_share_clms"] = np.where(
        out["Tot_Clms"] > 0, out["LIS_Tot_Clms"] / out["Tot_Clms"], np.nan)
    out["clms_per_provider"] = np.where(
        out["provider_count"] > 0, out["Tot_Clms"] / out["provider_count"], np.nan)
    out["benes_per_provider"] = np.where(
        out["provider_count"] > 0, out["Tot_Benes"] / out["provider_count"], np.nan)
    out["cost_per_clm"] = np.where(
        out["Tot_Clms"] > 0, out["Tot_Drug_Cst"] / out["Tot_Clms"], np.nan)

    # Year tag
    out["data_year"] = 2023

    # Lowercase, neat column names
    rename = {
        "Tot_Clms": "tot_clms",
        "Tot_30day_Fills": "tot_30day_fills",
        "Tot_Drug_Cst": "tot_drug_cst",
        "Tot_Day_Suply": "tot_day_suply",
        "Tot_Benes": "tot_benes",
        "GE65_Tot_Clms": "ge65_tot_clms",
        "GE65_Tot_Drug_Cst": "ge65_tot_drug_cst",
        "GE65_Tot_Benes": "ge65_tot_benes",
        "Brnd_Tot_Clms": "brnd_tot_clms",
        "Brnd_Tot_Drug_Cst": "brnd_tot_drug_cst",
        "Gnrc_Tot_Clms": "gnrc_tot_clms",
        "Gnrc_Tot_Drug_Cst": "gnrc_tot_drug_cst",
        "Othr_Tot_Clms": "othr_tot_clms",
        "Othr_Tot_Drug_Cst": "othr_tot_drug_cst",
        "MAPD_Tot_Clms": "mapd_tot_clms",
        "MAPD_Tot_Drug_Cst": "mapd_tot_drug_cst",
        "PDP_Tot_Clms": "pdp_tot_clms",
        "PDP_Tot_Drug_Cst": "pdp_tot_drug_cst",
        "LIS_Tot_Clms": "lis_tot_clms",
        "LIS_Drug_Cst": "lis_drug_cst",
        "NonLIS_Tot_Clms": "nonlis_tot_clms",
        "NonLIS_Drug_Cst": "nonlis_drug_cst",
        "Opioid_Tot_Clms": "opioid_tot_clms",
        "Opioid_Tot_Drug_Cst": "opioid_tot_drug_cst",
        "Opioid_Tot_Suply": "opioid_tot_suply",
        "Opioid_Tot_Benes": "opioid_tot_benes",
        "Opioid_LA_Tot_Clms": "opioid_la_tot_clms",
        "Opioid_LA_Tot_Drug_Cst": "opioid_la_tot_drug_cst",
        "Opioid_LA_Tot_Benes": "opioid_la_tot_benes",
        "Antbtc_Tot_Clms": "antbtc_tot_clms",
        "Antbtc_Tot_Drug_Cst": "antbtc_tot_drug_cst",
        "Antbtc_Tot_Benes": "antbtc_tot_benes",
        "Antpsyct_GE65_Tot_Clms": "antpsyct_ge65_tot_clms",
        "Antpsyct_GE65_Tot_Drug_Cst": "antpsyct_ge65_tot_drug_cst",
        "Antpsyct_GE65_Tot_Benes": "antpsyct_ge65_tot_benes",
        "Bene_Age_LT_65_Cnt": "bene_age_lt_65_cnt",
        "Bene_Age_65_74_Cnt": "bene_age_65_74_cnt",
        "Bene_Age_75_84_Cnt": "bene_age_75_84_cnt",
        "Bene_Age_GT_84_Cnt": "bene_age_gt_84_cnt",
        "Bene_Feml_Cnt": "bene_feml_cnt",
        "Bene_Male_Cnt": "bene_male_cnt",
        "Bene_Race_Wht_Cnt": "bene_race_wht_cnt",
        "Bene_Race_Black_Cnt": "bene_race_black_cnt",
        "Bene_Race_Api_Cnt": "bene_race_api_cnt",
        "Bene_Race_Hspnc_Cnt": "bene_race_hspnc_cnt",
        "Bene_Race_Natind_Cnt": "bene_race_natind_cnt",
        "Bene_Race_Othr_Cnt": "bene_race_othr_cnt",
        "Bene_Dual_Cnt": "bene_dual_cnt",
        "Bene_Ndual_Cnt": "bene_ndual_cnt",
        "Bene_Avg_Age": "bene_avg_age",
        "Bene_Avg_Risk_Scre": "bene_avg_risk_scre",
        "Opioid_Prscrbr_Rate": "opioid_prscrbr_rate",
    }
    out = out.rename(columns=rename)

    # Reorder columns
    front = ["state", "specialty", "data_year", "provider_count",
             "tot_clms", "tot_benes", "tot_drug_cst",
             "clms_per_provider", "benes_per_provider", "cost_per_clm",
             "brand_share_clms", "generic_share_clms",
             "opioid_share_clms", "mapd_share_clms", "pdp_share_clms", "lis_share_clms",
             "bene_avg_age", "bene_avg_risk_scre", "opioid_prscrbr_rate"]
    rest = [c for c in out.columns if c not in front]
    out = out[front + rest]

    # Sort
    out = out.sort_values(["state", "tot_clms"], ascending=[True, False])

    # Round numeric
    for c in out.select_dtypes(include="float64").columns:
        out[c] = out[c].round(4)

    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}: {len(out):,} rows, {len(out.columns)} cols")
    print("States:", out["state"].nunique())
    print("Specialties:", out["specialty"].nunique())
    print("Top specialties by total claims:")
    print(out.groupby("specialty")["tot_clms"].sum().sort_values(ascending=False).head(10))


if __name__ == "__main__":
    download()
    aggregate()
