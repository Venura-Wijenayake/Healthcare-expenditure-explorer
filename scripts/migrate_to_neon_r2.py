"""Migrate the CSV datasets in data/ to Postgres (Neon) + Cloudflare R2.

Routing decisions are delegated to routing.route_dataset(); this script
just discovers files, builds metadata, and dispatches.

Modes:
    (default)    TRUNCATE observations/metric_registry/dataset_registry,
                 then load fresh. First-run baseline path.
    --no-reset   Keep existing rows; use INSERT ... ON CONFLICT for the
                 registries. Idempotent for repeated runs.
    --dry-run    Print routing decisions and schema actions; write nothing.

Usage:
    python scripts/migrate_to_neon_r2.py
    python scripts/migrate_to_neon_r2.py --no-reset
    python scripts/migrate_to_neon_r2.py --dry-run
"""

from __future__ import annotations

import argparse
import io
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import psycopg2
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from infra import get_postgres_conn, load_secrets, make_r2  # noqa: E402
from routing import route_dataset  # noqa: E402


DATA_DIR = ROOT / "data"
INSERT_BATCH = 1000
PARQUET_COMPRESSION = "snappy"

# Disk-budget pre-flight constants (see MIGRATION_PLAYBOOK.md).
NEON_DISK_LIMIT_MB = 500       # free-tier ceiling
SAFE_BUDGET_MB = 400           # 80% of ceiling — abort threshold
# ~80 bytes heap + ~120 bytes across 6 btree indexes on observations.
# Conservative; under-estimating here is what caused the original
# Supabase blow-out.
BYTES_PER_OBS_ROW = 200
BASELINE_OVERHEAD_MB = 85      # 50 WAL + 30 system + 5 registries

SKIP_FILES = {
    "aoa_aging_services_DICTIONARY.csv",
    "usda_food_access_dictionary.csv",
    "uscs_data_dictionary.xlsx",
    "hrsa_uds_h80_2024.xlsx",
    "MANIFEST.md",
}

READ_OVERRIDES: dict[str, dict] = {"nci_cancer": {"sep": "|"}}

# Manual classifications fed to routing.route_dataset(). These mirror the
# lists in scripts/test_data_integrity.py — keep them in sync. (We didn't
# DRY them into a shared module yet because Venura wants to review the
# classifications by hand before that lock-in happens.)
CATEGORICAL_USED_BY_APP = {
    "part_d", "part_b", "geo_variation_2014_2023",
    "hpsa_primary_care", "hpsa_dental", "hpsa_mental_health",
    "hospital_compare_general_info", "hospital_compare_complications_state",
    "hospital_compare_hcahps_state", "hospital_compare_readmissions_state",
    "cms_nursing_home", "cms_hospital_prices", "cms_timely_care",
    "cms_enrollment_additive", "samhsa_facilities", "samhsa_nmhss", "cdc_nndss",
}
FILTER_HEAVY = {
    "ahrf_state_national_2025", "bls_unemployment", "bls_healthcare_wages",
    "census_saipe", "census_sahie", "state_risk_index",
    "cdc_hai", "cdc_hiv", "cdc_sti", "hrsa_nurse_corps",
}

# Curated names/agencies/categories for the registry. Datasets not in this
# table get auto-generated metadata from the dataset_key. Names are pulled
# from the original migrate_to_supabase_r2.py (Venura-curated) so the app's
# sources inventory stays consistent with what users have already seen.
DATASET_METADATA: dict[str, dict] = {
    "state_risk_index":              {"name": "State Healthcare Risk Index",                 "agency": "Composite", "category": "Risk"},
    "census_sahie":                  {"name": "Small Area Health Insurance Estimates",       "agency": "Census",    "category": "Coverage"},
    "census_saipe":                  {"name": "Small Area Income & Poverty Estimates",       "agency": "Census",    "category": "Social Determinants"},
    "bls_unemployment":              {"name": "BLS Unemployment by State",                   "agency": "BLS",       "category": "Workforce"},
    "cdc_hai":                       {"name": "CDC Healthcare-Associated Infections",        "agency": "CDC",       "category": "Quality"},
    "cms_timely_care":               {"name": "CMS Timely & Effective Care",                 "agency": "CMS",       "category": "Quality"},
    "hrsa_nurse_corps":              {"name": "HRSA Nurse Corps Awards",                     "agency": "HRSA",      "category": "Workforce"},
    "samhsa_nmhss":                  {"name": "SAMHSA National Mental Health Services Survey","agency": "SAMHSA",   "category": "Behavioral Health"},
    "cdc_hiv":                       {"name": "CDC HIV Surveillance",                        "agency": "CDC",       "category": "Disease"},
    "cdc_sti":                       {"name": "CDC STI Surveillance",                        "agency": "CDC",       "category": "Disease"},
    "hpsa_primary_care":             {"name": "HRSA HPSA — Primary Care",                    "agency": "HRSA",      "category": "Workforce"},
    "hospital_compare_general_info": {"name": "Hospital Compare — General Info",             "agency": "CMS",       "category": "Quality"},
    "cms_snf":                       {"name": "CMS Skilled Nursing Facility",                "agency": "CMS",       "category": "Post-Acute"},
    "cdc_nndss":                     {"name": "CDC NNDSS Notifiable Diseases",               "agency": "CDC",       "category": "Disease"},
    "hrsa_mch":                      {"name": "HRSA Maternal & Child Health",                "agency": "HRSA",      "category": "Maternal/Child"},
    "nci_cancer":                    {"name": "NCI Cancer Incidence & Mortality",            "agency": "NCI",       "category": "Disease"},
    "cdc_places_county":             {"name": "CDC PLACES County-Level",                     "agency": "CDC",       "category": "Population Health"},
    "cdc_alzheimers":                {"name": "CDC Alzheimer's Surveillance",                "agency": "CDC",       "category": "Chronic Disease"},
    "brfss_state_prevalence":        {"name": "BRFSS State Prevalence",                      "agency": "CDC",       "category": "Population Health"},
    "rwj_county_health_rankings":    {"name": "RWJ County Health Rankings",                  "agency": "RWJF",      "category": "Population Health"},
    "cms_physician_payments":        {"name": "CMS Physician Open Payments",                 "agency": "CMS",       "category": "Spending"},
    "cdc_vaccination":               {"name": "CDC Vaccination Coverage",                    "agency": "CDC",       "category": "Prevention"},
    "geo_variation_2014_2023":       {"name": "CMS Geographic Variation 2014-2023",          "agency": "CMS",       "category": "Spending"},

    # --- Tier-2 backfill (May 2026): the 58 keys that were defaulting to
    # agency='Unknown' in dataset_registry, which collapsed the header
    # banner's distinct-agency count to 16. Agency inferred from the
    # dataset_key prefix; category from dataset context. Names mirror the
    # consumer-facing source titles. See handoff for the two judgement
    # calls (gme_residency -> ACGME, ca_hcai -> CA HCAI facility data).
    "acs_demographics":              {"name": "Census ACS Demographics",                     "agency": "Census",  "category": "Social Determinants"},
    "ahrf_state_national_2025":      {"name": "HRSA Area Health Resources File",              "agency": "HRSA",    "category": "Workforce"},
    "ahrq_meps":                     {"name": "AHRQ Medical Expenditure Panel Survey",        "agency": "AHRQ",    "category": "Spending"},
    "aoa_aging_services":            {"name": "ACL Older Americans Act Services",             "agency": "ACL",     "category": "Social Determinants"},
    "bls_healthcare_wages":          {"name": "BLS Healthcare Occupational Wages",            "agency": "BLS",     "category": "Workforce"},
    "ca_hcai":                       {"name": "CA HCAI Facility Financial & Utilization",     "agency": "CA HCAI", "category": "Spending"},
    "cdc_births":                    {"name": "CDC Natality (Births)",                        "agency": "CDC",     "category": "Maternal/Child"},
    "cdc_drug_overdose":             {"name": "CDC Drug Overdose Mortality",                  "agency": "CDC",     "category": "Behavioral Health"},
    "cdc_lead_exposure":             {"name": "CDC Childhood Lead Exposure",                  "agency": "CDC",     "category": "Population Health"},
    "cdc_maternal_mortality":        {"name": "CDC Maternal Mortality",                       "agency": "CDC",     "category": "Maternal/Child"},
    "cdc_mortality":                 {"name": "CDC Mortality",                                "agency": "CDC",     "category": "Population Health"},
    "cdc_nhanes":                    {"name": "CDC NHANES",                                   "agency": "CDC",     "category": "Population Health"},
    "cdc_oral_health":               {"name": "CDC Oral Health Indicators",                   "agency": "CDC",     "category": "Population Health"},
    "cdc_svi":                       {"name": "CDC/ATSDR Social Vulnerability Index",         "agency": "CDC/ATSDR","category": "Social Determinants"},
    "cdc_wastewater":                {"name": "CDC Wastewater Surveillance",                  "agency": "CDC",     "category": "Disease"},
    "cdc_wisqars":                   {"name": "CDC WISQARS Injury Statistics",                "agency": "CDC",     "category": "Population Health"},
    "cdc_wonder_mortality":          {"name": "CDC WONDER Mortality",                         "agency": "CDC",     "category": "Population Health"},
    "cms_aco":                       {"name": "CMS Accountable Care Organizations",           "agency": "CMS",     "category": "Spending"},
    "cms_chronic_conditions":        {"name": "CMS Medicare Chronic Conditions",              "agency": "CMS",     "category": "Chronic Disease"},
    "cms_dialysis":                  {"name": "CMS Dialysis Facility Compare",                "agency": "CMS",     "category": "Quality"},
    "cms_enrollment_additive":       {"name": "CMS Medicare Enrollment",                      "agency": "CMS",     "category": "Coverage"},
    "cms_home_health":               {"name": "CMS Home Health Compare",                      "agency": "CMS",     "category": "Post-Acute"},
    "cms_hospice":                   {"name": "CMS Hospice Provider Data",                    "agency": "CMS",     "category": "Post-Acute"},
    "cms_hospital_prices":           {"name": "CMS Hospital Price Transparency",              "agency": "CMS",     "category": "Spending"},
    "cms_innovation":                {"name": "CMS Innovation Center Models",                 "agency": "CMS",     "category": "Spending"},
    "cms_inpatient_geo":             {"name": "CMS Inpatient Geographic Variation",           "agency": "CMS",     "category": "Spending"},
    "cms_ma_star_ratings":           {"name": "CMS Medicare Advantage Star Ratings",          "agency": "CMS",     "category": "Quality"},
    "cms_medicaid_drug":             {"name": "CMS Medicaid Drug Spending",                   "agency": "CMS",     "category": "Spending"},
    "cms_nppes":                     {"name": "CMS NPPES Provider Registry",                  "agency": "CMS",     "category": "Workforce"},
    "cms_nursing_home":              {"name": "CMS Nursing Home Compare",                     "agency": "CMS",     "category": "Post-Acute"},
    "cms_open_payments":             {"name": "CMS Open Payments",                            "agency": "CMS",     "category": "Spending"},
    "cms_partd_prescribers":         {"name": "CMS Part D Prescribers",                       "agency": "CMS",     "category": "Spending"},
    "dot_transportation":            {"name": "DOT Transportation Access",                    "agency": "DOT",     "category": "Social Determinants"},
    "epa_ejscreen":                  {"name": "EPA EJScreen Environmental Justice",           "agency": "EPA",     "category": "Social Determinants"},
    "fcc_broadband":                 {"name": "FCC Broadband Availability",                   "agency": "FCC",     "category": "Social Determinants"},
    "fda_adverse_events":            {"name": "FDA Adverse Event Reporting (FAERS)",          "agency": "FDA",     "category": "Quality"},
    "gme_residency":                 {"name": "ACGME Graduate Medical Education",             "agency": "ACGME",   "category": "Workforce"},
    "hospital_compare_complications_state": {"name": "Hospital Compare — Complications (State)", "agency": "CMS",  "category": "Quality"},
    "hospital_compare_hcahps_state":        {"name": "Hospital Compare — HCAHPS (State)",        "agency": "CMS",  "category": "Quality"},
    "hospital_compare_readmissions_state":  {"name": "Hospital Compare — Readmissions (State)",  "agency": "CMS",  "category": "Quality"},
    "hpsa_dental":                   {"name": "HRSA HPSA — Dental",                           "agency": "HRSA",    "category": "Workforce"},
    "hpsa_mental_health":            {"name": "HRSA HPSA — Mental Health",                    "agency": "HRSA",    "category": "Workforce"},
    "hrsa_fqhc":                     {"name": "HRSA Federally Qualified Health Centers",      "agency": "HRSA",    "category": "Access"},
    "hrsa_grants":                   {"name": "HRSA Grant Awards",                            "agency": "HRSA",    "category": "Spending"},
    "hrsa_ryan_white":               {"name": "HRSA Ryan White HIV/AIDS Program",            "agency": "HRSA",    "category": "Disease"},
    "hrsa_telehealth":               {"name": "HRSA Telehealth Programs",                     "agency": "HRSA",    "category": "Access"},
    "hrsa_workforce_projections":    {"name": "HRSA Health Workforce Projections",            "agency": "HRSA",    "category": "Workforce"},
    "hud_fair_market_rents":         {"name": "HUD Fair Market Rents",                        "agency": "HUD",     "category": "Social Determinants"},
    "nih_research_funding":          {"name": "NIH Research Funding (RePORTER)",              "agency": "NIH",     "category": "Spending"},
    "nimh_mental_health":            {"name": "NIMH Mental Health Statistics",                "agency": "NIH",     "category": "Behavioral Health"},
    "onc_ehr_adoption":              {"name": "ONC EHR Adoption",                             "agency": "ONC",     "category": "Health IT"},
    "osha_healthcare_injuries":      {"name": "OSHA Healthcare Worker Injuries",              "agency": "OSHA",    "category": "Workforce"},
    "part_b":                        {"name": "Medicare Part B Spending",                     "agency": "CMS",     "category": "Spending"},
    "part_d":                        {"name": "Medicare Part D Spending",                     "agency": "CMS",     "category": "Spending"},
    "samhsa_facilities":             {"name": "SAMHSA Treatment Facility Locator",            "agency": "SAMHSA",  "category": "Behavioral Health"},
    "samhsa_nsduh":                  {"name": "SAMHSA NSDUH",                                 "agency": "SAMHSA",  "category": "Behavioral Health"},
    "usda_food_access":              {"name": "USDA Food Access Research Atlas",              "agency": "USDA",    "category": "Social Determinants"},
    "usda_wic":                      {"name": "USDA WIC Participation",                       "agency": "USDA",    "category": "Social Determinants"},
}


# ============================================================
# SCHEMA
# ============================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dataset_registry (
    dataset_key TEXT PRIMARY KEY, name TEXT NOT NULL, agency TEXT NOT NULL,
    category TEXT NOT NULL, granularity TEXT NOT NULL,
    storage_location TEXT NOT NULL, parquet_path TEXT,
    year_start INTEGER, year_end INTEGER, refresh_schedule TEXT,
    last_refreshed TIMESTAMPTZ, row_count INTEGER,
    contributor TEXT DEFAULT 'core-team', status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS metric_registry (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT REFERENCES dataset_registry(dataset_key),
    metric_name TEXT NOT NULL, metric_label TEXT NOT NULL,
    metric_unit TEXT, lower_is_better BOOLEAN, description TEXT,
    UNIQUE(dataset_key, metric_name)
);
CREATE TABLE IF NOT EXISTS observations (
    id BIGSERIAL PRIMARY KEY,
    dataset_key TEXT REFERENCES dataset_registry(dataset_key),
    state TEXT, county TEXT, granularity TEXT NOT NULL,
    year INTEGER, month INTEGER,
    metric_name TEXT NOT NULL, metric_value NUMERIC, metric_unit TEXT,
    sex TEXT, race TEXT, age_group TEXT, notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_state             ON observations(state);
CREATE INDEX IF NOT EXISTS idx_obs_metric            ON observations(metric_name);
CREATE INDEX IF NOT EXISTS idx_obs_dataset           ON observations(dataset_key);
CREATE INDEX IF NOT EXISTS idx_obs_year              ON observations(year);
CREATE INDEX IF NOT EXISTS idx_obs_state_metric_year ON observations(state, metric_name, year);
CREATE INDEX IF NOT EXISTS idx_obs_granularity       ON observations(granularity);
CREATE TABLE IF NOT EXISTS contributor_submissions (
    id BIGSERIAL PRIMARY KEY,
    github_username TEXT NOT NULL, dataset_name TEXT NOT NULL,
    source_url TEXT NOT NULL, agency TEXT NOT NULL, description TEXT NOT NULL,
    fetch_script_url TEXT, estimated_rows INTEGER,
    status TEXT DEFAULT 'pending', reviewer TEXT, reviewer_notes TEXT,
    submitted_at TIMESTAMPTZ DEFAULT NOW(), reviewed_at TIMESTAMPTZ
);
"""

def apply_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
    print("[schema] applied")

def truncate_tables(conn) -> None:
    """TRUNCATE the three data tables. CASCADE clears observations/metric_registry FKs."""
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE observations, metric_registry, dataset_registry "
            "RESTART IDENTITY CASCADE"
        )
    conn.commit()
    print("[truncate] observations, metric_registry, dataset_registry — done")


# ============================================================
# COLUMN CLEANING
# ============================================================

STATE_COL_CANDIDATES = [
    "state", "State", "state_name", "state_abbr", "BENE_GEO_DESC", "AREA",
    "locationabbr", "locationdesc", "reporting_area", "State Abbreviation",
    "State Name", "state_territory", "st_abbrev", "NAME", "ACO_State",
]
COUNTY_COL_CANDIDATES = ["county", "County", "county_name", "BENE_GEO_DESC2", "fips_county"]
YEAR_COL_CANDIDATES   = ["year", "Year", "YEAR", "fiscal_year", "yearstart", "period"]
MONTH_COL_CANDIDATES  = ["month", "Month", "MONTH", "month_num"]
SEX_COL_CANDIDATES    = ["sex", "Sex", "SEX", "gender", "Gender"]
RACE_COL_CANDIDATES   = ["race", "Race", "RACE", "race_ethnicity", "Race/Ethnicity"]
AGE_COL_CANDIDATES    = ["age", "Age", "AGE", "age_group", "AgeGroup", "age_range"]

def _first_present(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def drop_low_value_columns(df: pd.DataFrame, dataset_key: str) -> pd.DataFrame:
    """Drop columns: >90% null/empty, and exact duplicates of another column."""
    df = df.copy()
    before = list(df.columns)
    null_share = (df.isna() | (df.astype(object) == "")).mean()
    df = df.drop(columns=null_share[null_share > 0.9].index.tolist())
    df = df.drop(columns=df.columns[df.T.duplicated(keep="first")].tolist())
    dropped = set(before) - set(df.columns)
    if dropped:
        print(f"  [columns] {dataset_key}: dropped {len(dropped)} -> kept {len(df.columns)}")
    return df

def detect_granularity(df: pd.DataFrame) -> tuple[str, str | None, str | None]:
    state_col = _first_present(df, STATE_COL_CANDIDATES)
    county_col = _first_present(df, COUNTY_COL_CANDIDATES)
    if county_col and state_col:
        return "county", state_col, county_col
    if state_col:
        return "state", state_col, None
    return "national", None, None

def read_csv(path: Path, dataset_key: str, **extra) -> pd.DataFrame:
    opts = {"low_memory": False}
    opts.update(READ_OVERRIDES.get(dataset_key, {}))
    opts.update(extra)
    return pd.read_csv(path, **opts)

def count_csv_rows(path: Path, dataset_key: str) -> int:
    sep = READ_OVERRIDES.get(dataset_key, {}).get("sep", ",")
    try:
        return sum(c.shape[0] for c in pd.read_csv(path, sep=sep, usecols=[0],
                                                    low_memory=False, chunksize=200_000))
    except Exception:
        return read_csv(path, dataset_key).shape[0]

def count_numeric_columns(path: Path, dataset_key: str) -> int:
    sep = READ_OVERRIDES.get(dataset_key, {}).get("sep", ",")
    try:
        sample = pd.read_csv(path, sep=sep, nrows=1000, low_memory=False)
    except Exception:
        return 0
    return sum(1 for c in sample.columns if pd.api.types.is_numeric_dtype(sample[c]))

def detect_year_span(path: Path, dataset_key: str) -> tuple[int | None, int | None]:
    sep = READ_OVERRIDES.get(dataset_key, {}).get("sep", ",")
    y_min: int | None = None
    y_max: int | None = None
    try:
        head = pd.read_csv(path, sep=sep, nrows=5, low_memory=False)
        ycol = _first_present(head, YEAR_COL_CANDIDATES)
        if not ycol:
            return None, None
        for chunk in pd.read_csv(path, sep=sep, usecols=[ycol], low_memory=False,
                                 chunksize=200_000):
            years = pd.to_numeric(chunk[ycol], errors="coerce").dropna()
            if years.empty:
                continue
            y_min = int(years.min()) if y_min is None else min(y_min, int(years.min()))
            y_max = int(years.max()) if y_max is None else max(y_max, int(years.max()))
    except Exception:
        return None, None
    return y_min, y_max

def detect_granularity_from_csv(path: Path, dataset_key: str) -> str:
    sep = READ_OVERRIDES.get(dataset_key, {}).get("sep", ",")
    head = pd.read_csv(path, sep=sep, nrows=5, low_memory=False)
    g, _, _ = detect_granularity(head)
    return g


# ============================================================
# ROUTING DISPATCH
# ============================================================

@dataclass
class Plan:
    dataset_key: str
    path: Path
    tier: str
    reason: str
    rows: int
    numeric_columns: int

def list_datasets() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for p in sorted(DATA_DIR.iterdir()):
        if not p.is_file() or p.name in SKIP_FILES or p.suffix.lower() != ".csv":
            continue
        out.append((p.stem, p))
    return out

def build_plan(all_datasets: list[tuple[str, Path]]) -> list[Plan]:
    plans: list[Plan] = []
    for key, path in all_datasets:
        try:
            rows = count_csv_rows(path, key)
            ncols = count_numeric_columns(path, key)
        except Exception as exc:  # noqa: BLE001
            print(f"  [route] {key}: SKIPPED ({exc})")
            continue
        meta = {
            "rows": rows,
            "numeric_columns": ncols,
            "has_categorical_columns_used_by_app": key in CATEGORICAL_USED_BY_APP,
            "is_filter_heavy": key in FILTER_HEAVY,
        }
        tier, reason = route_dataset(meta)
        plans.append(Plan(key, path, tier, reason, rows, ncols))
    return plans

def print_routing_decisions(plans: list[Plan]) -> None:
    pg = sum(1 for p in plans if p.tier == "postgres")
    r2 = sum(1 for p in plans if p.tier == "r2")
    print(f"\n[routing] {len(plans)} datasets — {pg} postgres, {r2} r2\n")
    for p in plans:
        print(f"  {p.tier:8} {p.dataset_key:40} rows={p.rows:>8,} num_cols={p.numeric_columns:>3}  ({p.reason})")


def predict_disk_usage(plans: list[Plan]) -> dict:
    """Estimate Neon disk footprint for the postgres-routed datasets.

    Predicted observation rows = rows * numeric_columns (one row per
    melted metric value). Storage = rows * 80 bytes (heap-only) plus
    baseline overhead. See MIGRATION_PLAYBOOK.md for the budget table.
    """
    pg_plans = [p for p in plans if p.tier == "postgres"]
    predicted_obs = sum(p.rows * p.numeric_columns for p in pg_plans)
    obs_mb = predicted_obs * BYTES_PER_OBS_ROW / 1_000_000
    total_mb = obs_mb + BASELINE_OVERHEAD_MB
    headroom_mb = NEON_DISK_LIMIT_MB - total_mb
    pct_used = (total_mb / NEON_DISK_LIMIT_MB) * 100
    largest = sorted(pg_plans, key=lambda p: p.rows * p.numeric_columns, reverse=True)[:5]
    return {
        "pg_count": len(pg_plans),
        "predicted_obs": predicted_obs,
        "obs_mb": obs_mb,
        "baseline_mb": BASELINE_OVERHEAD_MB,
        "total_mb": total_mb,
        "limit_mb": NEON_DISK_LIMIT_MB,
        "headroom_mb": headroom_mb,
        "pct_used": pct_used,
        "exceeded": total_mb > SAFE_BUDGET_MB,
        "largest": largest,
    }


def print_budget_preflight(b: dict, dry_run: bool, force_budget: bool) -> bool:
    """Print the pre-flight table; return True to proceed, False to abort."""
    print()
    print("=== DISK BUDGET PRE-FLIGHT ===")
    print(f"postgres-routed datasets:     {b['pg_count']}")
    print(f"predicted observations:       {b['predicted_obs']:,} rows")
    print(f"predicted observations storage: {b['obs_mb']:.0f} MB")
    print(f"baseline overhead (WAL + system + registries): {b['baseline_mb']} MB")
    print(f"predicted total:              {b['total_mb']:.0f} MB")
    print(f"Neon free tier limit:         {b['limit_mb']} MB")
    print(f"headroom:                     {b['headroom_mb']:.0f} MB ({b['pct_used']:.0f}% used)")
    print()
    print("Top 5 contributors (predicted observation rows):")
    for p in b["largest"]:
        n = p.rows * p.numeric_columns
        print(f"  {p.dataset_key:40} {n:>10,}  ({p.rows:,} rows × {p.numeric_columns} numeric cols)")
    print()
    if b["exceeded"]:
        if dry_run:
            print(f"[BUDGET EXCEEDED] {b['total_mb']:.0f} MB > {SAFE_BUDGET_MB} MB safe threshold "
                  f"({SAFE_BUDGET_MB / NEON_DISK_LIMIT_MB:.0%} of {NEON_DISK_LIMIT_MB} MB) — "
                  f"informational only in dry-run")
            return True
        if force_budget:
            print(f"[BUDGET EXCEEDED — proceeding anyway] --force-budget given; "
                  f"{b['total_mb']:.0f} MB > {SAFE_BUDGET_MB} MB safe threshold")
            return True
        print(f"[BUDGET EXCEEDED — ABORT] {b['total_mb']:.0f} MB > {SAFE_BUDGET_MB} MB safe threshold")
        print(f"   Override at your own risk with --force-budget.")
        return False
    print("[budget OK]")
    return True


# ============================================================
# MELT / UNPIVOT
# ============================================================

def melt_to_observations(df: pd.DataFrame, dataset_key: str) -> tuple[pd.DataFrame, dict]:
    granularity, state_col, county_col = detect_granularity(df)
    year_col  = _first_present(df, YEAR_COL_CANDIDATES)
    month_col = _first_present(df, MONTH_COL_CANDIDATES)
    sex_col   = _first_present(df, SEX_COL_CANDIDATES)
    race_col  = _first_present(df, RACE_COL_CANDIDATES)
    age_col   = _first_present(df, AGE_COL_CANDIDATES)

    id_vars = [c for c in (state_col, county_col, year_col, month_col,
                           sex_col, race_col, age_col) if c]
    numeric_cols = [c for c in df.columns
                    if c not in id_vars and pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        raise ValueError(f"{dataset_key}: no numeric columns to unpivot")

    long_df = df.melt(id_vars=id_vars, value_vars=numeric_cols,
                      var_name="metric_name", value_name="metric_value")
    long_df = long_df.dropna(subset=["metric_value"])

    out = pd.DataFrame({
        "dataset_key": dataset_key,
        "state":  long_df[state_col]  if state_col  else None,
        "county": long_df[county_col] if county_col else None,
        "granularity": granularity,
        "year":  pd.to_numeric(long_df[year_col],  errors="coerce").astype("Int64") if year_col  else pd.NA,
        "month": pd.to_numeric(long_df[month_col], errors="coerce").astype("Int64") if month_col else pd.NA,
        "metric_name":  long_df["metric_name"].astype(str),
        "metric_value": pd.to_numeric(long_df["metric_value"], errors="coerce"),
        "metric_unit":  None,
        "sex":       long_df[sex_col].astype(str)  if sex_col  else None,
        "race":      long_df[race_col].astype(str) if race_col else None,
        "age_group": long_df[age_col].astype(str)  if age_col  else None,
        "notes":     None,
    })
    out = out.dropna(subset=["metric_value"])
    years = pd.to_numeric(out["year"], errors="coerce").dropna()
    return out, {
        "granularity": granularity,
        "year_start": int(years.min()) if not years.empty else None,
        "year_end":   int(years.max()) if not years.empty else None,
        "metric_names": numeric_cols,
    }


# ============================================================
# POSTGRES INSERT PATH
# ============================================================

OBS_COLS = ("dataset_key", "state", "county", "granularity", "year", "month",
            "metric_name", "metric_value", "metric_unit", "sex", "race",
            "age_group", "notes")

def upsert_dataset_registry(conn, *, dataset_key: str, storage_location: str,
                            granularity: str, parquet_path: str | None,
                            year_start: int | None, year_end: int | None,
                            row_count: int) -> None:
    """Always writes storage_location ∈ {'postgres', 'r2'} — never 'supabase'.
    `row_count` is the original CSV row count (not the long-format observations count)."""
    meta = DATASET_METADATA.get(dataset_key, {})
    sql = """
        INSERT INTO dataset_registry
            (dataset_key, name, agency, category, granularity,
             storage_location, parquet_path, year_start, year_end, row_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (dataset_key) DO UPDATE SET
            name = EXCLUDED.name, agency = EXCLUDED.agency,
            category = EXCLUDED.category, granularity = EXCLUDED.granularity,
            storage_location = EXCLUDED.storage_location,
            parquet_path = EXCLUDED.parquet_path,
            year_start = EXCLUDED.year_start, year_end = EXCLUDED.year_end,
            row_count = EXCLUDED.row_count
    """
    params = (
        dataset_key,
        meta.get("name", dataset_key.replace("_", " ").title()),
        meta.get("agency", "Unknown"),
        meta.get("category", "General"),
        granularity, storage_location, parquet_path,
        year_start, year_end, row_count,
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()

def insert_metric_registry(conn, dataset_key: str, metric_names: Iterable[str]) -> None:
    rows = []
    for m in metric_names:
        lc = m.lower()
        unit = ("%" if any(k in lc for k in ("pct", "rate", "percent"))
                else "USD" if any(k in lc for k in ("spending", "amount", "dollars", "_usd"))
                else "per 100k" if "per_100k" in lc or "per 100k" in lc
                else None)
        rows.append((dataset_key, m, m.replace("_", " ").replace(".", " ").title(),
                     unit, None))
    if not rows:
        return
    sql = """
        INSERT INTO metric_registry
            (dataset_key, metric_name, metric_label, metric_unit, lower_is_better)
        VALUES %s
        ON CONFLICT (dataset_key, metric_name) DO UPDATE SET
            metric_label = EXCLUDED.metric_label,
            metric_unit  = EXCLUDED.metric_unit
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=INSERT_BATCH)
    conn.commit()

def insert_observations(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    df = df.reindex(columns=list(OBS_COLS))
    df = df.where(pd.notna(df), None)
    records = [tuple(r) for r in df.itertuples(index=False, name=None)]
    sql = f"INSERT INTO observations ({','.join(OBS_COLS)}) VALUES %s"
    with conn.cursor() as cur:
        execute_values(cur, sql, records, page_size=INSERT_BATCH)
    conn.commit()
    return len(records)

# NOTE: migrate_to_postgres and its helpers (melt_to_observations,
# insert_observations, insert_metric_registry) are currently unreachable —
# routing.route_dataset() always returns 'r2' under the lakehouse-only
# architecture. Preserved intact for future re-enable; see
# docs/MIGRATION_PLAYBOOK.md "Decision record (May 2026): lakehouse-only".
def migrate_to_postgres(conn, dataset_key: str, path: Path, csv_row_count: int) -> dict:
    print(f"[postgres] {dataset_key}: reading {path.name}")
    df = read_csv(path, dataset_key)
    df.replace([np.inf, -np.inf], None, inplace=True)
    df = drop_low_value_columns(df, dataset_key)
    long_df, meta = melt_to_observations(df, dataset_key)
    upsert_dataset_registry(
        conn, dataset_key=dataset_key, storage_location="postgres",
        granularity=meta["granularity"], parquet_path=None,
        year_start=meta["year_start"], year_end=meta["year_end"],
        row_count=int(csv_row_count),
    )
    n = insert_observations(conn, long_df)
    insert_metric_registry(conn, dataset_key, meta["metric_names"])
    print(f"  inserted {n} observation rows ({len(meta['metric_names'])} metrics)")
    return {"observation_rows": n, "metrics": len(meta["metric_names"])}


# ============================================================
# R2 PARQUET PATH
# ============================================================

def csv_to_parquet_bytes(path: Path, dataset_key: str) -> bytes:
    """Whole-file read so pyarrow gets a single consistent dtype per column."""
    sep = READ_OVERRIDES.get(dataset_key, {}).get("sep", ",")
    df = pd.read_csv(path, sep=sep, low_memory=False)
    df = drop_low_value_columns(df, dataset_key)
    table = pa.Table.from_pandas(df, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression=PARQUET_COMPRESSION)
    return buf.getvalue()

def migrate_to_r2(secrets, r2_client, bucket: str, dataset_key: str,
                  csv_path: Path, csv_row_count: int) -> dict:
    # Phase 1: read CSV, convert to Parquet, upload to R2 — no DB connection
    # held during the slow upload. Holding a Neon connection idle through a
    # 30-60s upload causes the server to drop SSL, killing the registry write.
    print(f"[r2] {dataset_key}: converting {csv_path.name} to Parquet")
    csv_bytes = csv_path.stat().st_size
    parquet_bytes = csv_to_parquet_bytes(csv_path, dataset_key)
    parquet_key = f"{dataset_key}.parquet"
    r2_client.put_object(Bucket=bucket, Key=parquet_key, Body=parquet_bytes,
                         ContentType="application/vnd.apache.parquet")
    csv_mb = csv_bytes / 1_000_000
    pq_mb = len(parquet_bytes) / 1_000_000
    reduction = 1 - (len(parquet_bytes) / csv_bytes) if csv_bytes else 0.0
    print(f"  uploaded {parquet_key} — {csv_mb:.1f}MB CSV → {pq_mb:.1f}MB Parquet "
          f"({reduction:.0%} reduction)")

    # Phase 2: open a fresh connection just for the registry write.
    conn = get_postgres_conn(secrets)
    try:
        upsert_dataset_registry(
            conn, dataset_key=dataset_key, storage_location="r2",
            granularity=detect_granularity_from_csv(csv_path, dataset_key),
            parquet_path=parquet_key,
            year_start=detect_year_span(csv_path, dataset_key)[0],
            year_end=detect_year_span(csv_path, dataset_key)[1],
            row_count=int(csv_row_count),
        )
    finally:
        try:
            conn.close()
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            pass
    return {"csv_mb": csv_mb, "parquet_mb": pq_mb, "reduction": reduction,
            "rows": int(csv_row_count)}


# ============================================================
# MAIN + ARGPARSE
# ============================================================

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-reset", action="store_true",
                    help="Skip TRUNCATE; INSERT ... ON CONFLICT for idempotent re-runs.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print routing decisions and schema actions; write nothing.")
    ap.add_argument("--force-budget", action="store_true",
                    help="Proceed even when the disk-budget pre-flight predicts >400 MB.")
    return ap.parse_args()

def print_banner(args: argparse.Namespace) -> None:
    msg = ("DRY RUN — no writes will occur" if args.dry_run
           else "INCREMENTAL UPDATE — ON CONFLICT upserts" if args.no_reset
           else "TRUNCATING TABLES — fresh baseline load")
    bar = "=" * 64
    print(f"{bar}\n{msg}\n{bar}")

def main() -> int:
    args = parse_args()
    print_banner(args)

    secrets = load_secrets()
    all_datasets = list_datasets()
    print(f"[discover] found {len(all_datasets)} CSV datasets in {DATA_DIR}")
    plans = build_plan(all_datasets)
    print_routing_decisions(plans)

    budget = predict_disk_usage(plans)
    if not print_budget_preflight(budget, args.dry_run, args.force_budget):
        return 2

    if args.dry_run:
        print("\n[dry-run] would apply schema, "
              + ("skip truncate" if args.no_reset else "TRUNCATE 3 tables")
              + f", migrate {len(plans)} datasets — exiting")
        return 0

    # Phase 1 — schema + TRUNCATE on a dedicated connection that closes
    # before the per-dataset loop starts. Long R2 uploads can sit idle
    # past Neon's connection timeout, so we open a fresh connection per
    # dataset below rather than holding one across the whole loop.
    setup_conn = get_postgres_conn(secrets)
    try:
        apply_schema(setup_conn)
        if not args.no_reset:
            truncate_tables(setup_conn)
    finally:
        setup_conn.close()

    # Phase 2 — per-dataset migration, fresh connection each time.
    r2 = make_r2(secrets)
    failed: list[tuple[str, str]] = []
    pg_results: dict[str, dict] = {}
    r2_results: dict[str, dict] = {}

    for plan in plans:
        try:
            if plan.tier == "postgres":
                # Currently unreachable — routing.route_dataset always returns
                # 'r2'. Branch retained for if/when the postgres tier is
                # repaired and re-enabled per dataset.
                conn = get_postgres_conn(secrets)
                try:
                    pg_results[plan.dataset_key] = migrate_to_postgres(
                        conn, plan.dataset_key, plan.path, plan.rows)
                except Exception:
                    try:
                        conn.rollback()
                    except (psycopg2.InterfaceError, psycopg2.OperationalError):
                        pass
                    raise
                finally:
                    try:
                        conn.close()
                    except (psycopg2.InterfaceError, psycopg2.OperationalError):
                        pass
            else:
                # migrate_to_r2 manages its own short-lived connection now,
                # opened only for the post-upload registry write — see its
                # docstring for the SSL-drop background.
                r2_results[plan.dataset_key] = migrate_to_r2(
                    secrets, r2, secrets.r2_bucket_name,
                    plan.dataset_key, plan.path, plan.rows)
        except Exception as exc:  # noqa: BLE001
            failed.append((plan.dataset_key, f"{plan.tier}: {exc}"))
            traceback.print_exc()

    succeeded = len(pg_results) + len(r2_results)
    print(f"\n=== MIGRATION SUMMARY ===")
    print(f"  postgres datasets:   {len(pg_results)}")
    print(f"  r2 datasets:         {len(r2_results)}")
    print(f"  succeeded total:     {succeeded}")
    print(f"  failed:              {len(failed)}")
    if failed:
        print(f"  failed dataset_keys:")
        for k, why in failed:
            print(f"    ❌ {k} — {why}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
