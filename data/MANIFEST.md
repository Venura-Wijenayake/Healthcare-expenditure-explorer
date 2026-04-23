# Healthcare Intelligence Platform — Data Manifest

The `data/` directory is gitignored. This manifest documents every dataset, its source, and how to re-fetch it. To rebuild the data layer from scratch, follow the URLs below or extend `data_loader.py` with the missing loaders.

**Inventory:** 25 distinct datasets across CMS, HRSA, CDC, Census, BLS, USDA, HUD, EPA, SAMHSA, and California HCAI. Two pre-existing files (`part_d.csv`, `part_b.csv`) are documented at the bottom.

**Total disk usage:** ~667 MB across 36 files.

---

## 1. CMS Medicare Geographic Variation
- **File:** `geo_variation_2014_2023.csv` — 33,639 rows × 247 cols (52.8 MB)
- **Years:** 2014–2023 (annual)
- **Source:** [CMS Medicare Geographic Variation by National, State & County](https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-geographic-comparisons/medicare-geographic-variation-by-national-state-county) — direct CSV via dataset UUID `6219697b-8f6c-4164-bed4-cd9317c58ebc`
- **Granularity:** national / state / county × age level (All / <65 / ≥65)
- **What it gives:** Medicare FFS spending (raw + standardized), beneficiary counts (FFS / MA / total), Part A+B coverage, demographics (sex / race / dual %), risk score, and 200+ service-line breakdowns (IP / SNF / HHA / HOS / OP) including utilization (admits / ED visits / readmits) and quality (ACSC, mortality)

## 2. HRSA Area Health Resources File (AHRF) — state + national
- **File:** `ahrf_state_national_2025.csv` — 52 rows × 1,448 cols (250 KB) + tech docs in `ahrf_tech_docs/`
- **Years:** 2024–2025 release (variable years per column, suffixes `_23` / `_24`)
- **Source:** [HRSA Data Downloads — AHRF](https://data.hrsa.gov/DataDownload/AHRF/AHRF_SN_2024-2025_CSV.zip)
- **Granularity:** 50 states + DC + US national
- **What it gives:** Workforce supply by profession (physicians, RNs, LPNs, dentists, PAs, psychologists, pharmacists, etc.) — counts, demographic breakdowns within profession, employment status (`*_emplymt_24`), median wage (`*_medn_wage_24`), plus population denominators (`popn_*`). Naming convention `<profession>_<metric>_<year>`.

## 3. HRSA HPSA — Health Professional Shortage Areas (3 disciplines)
- **Files:**
  - `hpsa_primary_care.csv` — 77,724 rows × 66 cols (47 MB)
  - `hpsa_dental.csv` — 45,176 rows × 65 cols (27 MB)
  - `hpsa_mental_health.csv` — 39,517 rows × 65 cols (24 MB)
- **Source:** HRSA Data Warehouse — `https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv` (and `_DH.csv` / `_MH.csv`)
- **Granularity:** designation-level (one row per HPSA designation); use `HPSA Status == 'Designated'` to filter currently active
- **What it gives:** Per discipline: HPSA score, designated population, underserved population, FTE practitioners needed, score, designation type (Geographic / Population / Facility), rural status, lat/lon, county FIPS

## 4. CDC BRFSS Prevalence Data — state-level chronic disease prevalence
- **File:** `brfss_state_prevalence.csv` — 64,290 rows × 27 cols (22 MB)
- **Years:** 2018–2024
- **Source:** [Behavioral Risk Factor Surveillance System Prevalence Data (2011–present)](https://data.cdc.gov/resource/dttw-5yxu.csv?$where=year>=2018%20AND%20break_out='Overall'%20AND%20data_value_type='Crude%20Prevalence')
- **Granularity:** state × year × topic × question × response (long format), filtered to `break_out='Overall'` + `Crude Prevalence`
- **What it gives:** State-level prevalence % (`data_value`) with CIs and sample sizes for 21 classes / 63 topics: Diabetes, Hypertension, Cholesterol, Obesity, Cancer Screening, Smoking, Mental Health, Asthma, COPD, Arthritis, Oral Health, etc. **(Substituted for CDC PLACES which has no state-level dataset.)**

## 5. CDC PLACES — county-level chronic disease prevalence
- **File:** `cdc_places_county.csv` — 229,298 rows × 22 cols (63 MB)
- **Years:** 2022, 2023
- **Source:** [PLACES: Local Data for Better Health, County Data, 2025 release](https://data.cdc.gov/resource/swc5-untb.csv?$limit=300000) — Socrata resource `swc5-untb`
- **Granularity:** county-level (229,218 rows) + 80 state-summary rows in same file (use `len(locationid)==2` to isolate state)
- **What it gives:** 40 measures across 6 categories (Health Outcomes, Health Status, Disability, Prevention, Health Risk Behaviors, Health-Related Social Needs). Model-based small-area estimates — **do not re-aggregate naively.**

## 6. Census SAHIE — Small Area Health Insurance Estimates
- **File:** `census_sahie.csv` — 4,998 rows × 13 cols (385 KB)
- **Years:** 2006–2023 (18 years)
- **Source:** [Census SAHIE timeseries API](https://api.census.gov/data/timeseries/healthins/sahie?get=NAME,PCTUI_PT,PCTIC_PT,NUI_PT,NIC_PT,NIPR_PT,IPRCAT,IPR_DESC&for=state:*&time=from+2006+to+2023&IPRCAT=*&AGECAT=0&SEXCAT=0&RACECAT=0)
- **Granularity:** 51 states (50 + DC) × year × IPR bracket (6 categories: All / ≤138% / ≤200% / ≤250% / ≤400% / 138–400% of FPL)
- **What it gives:** % uninsured (`PCTUI_PT`), % insured (`PCTIC_PT`), uninsured count (`NUI_PT`), insured count (`NIC_PT`), denominator population in IPR group (`NIPR_PT`) — supports computing poverty distribution + insurance rates by income bracket

## 7. CMS Medicare Monthly Enrollment (additive fields only)
- **File:** `cms_enrollment_additive.csv` — 9,802 rows × 26 cols (1.9 MB)
- **Years:** 2013–2025 (monthly + annual aggregates)
- **Source:** [Medicare Monthly Enrollment](https://data.cms.gov/sites/default/files/2026-03/c2e42f20-57f6-4bbf-95a7-5267cec3f77c/Medicare%20Monthly%20Enrollment%20Data_December%202025.csv) — filtered to state-level + scoped to **additive** columns only (Part D, dual eligibility, ESRD splits) to avoid duplicating geo_variation's enrollment fields
- **Granularity:** state × year × month (12 months + "Year" annual aggregate)
- **What it gives:** Part D enrollment (PDP / MA-PD / LIS tiers), dual eligibility counts (Full / Partial / QMB / SLMB / QDWI), ESRD breakdowns
- **Dropped (overlap with geo_variation):** `TOT_BENES`, `ORGNL_MDCR_BENES`, `MA_AND_OTH_BENES`, sex/race/age count breakdowns

## 8. CMS Hospital Compare — quality, satisfaction, readmissions (4 files)
- **Files:**
  - `hospital_compare_hcahps_state.csv` — 2,856 × 8 (570 KB) — patient satisfaction by state
  - `hospital_compare_readmissions_state.csv` — 784 × 14 (133 KB) — Unplanned Hospital Visits, hospital distribution counts per measure
  - `hospital_compare_complications_state.csv` — 1,120 × 10 (104 KB) — Complications & Deaths, hospital distribution counts
  - `hospital_compare_general_info.csv` — 5,426 × 38 (1.5 MB) — hospital-level master with 1–5 ★ overall rating and per-domain measure counts
- **Source:** CMS Provider Data Catalog — resource IDs `84jm-wiui` (HCAHPS state), `4gkm-5ypv` (Unplanned visits state), `bs2r-24vh` (Complications state), `xubh-q36u` (Hospital General Info)
- **Caveat:** State files give **distribution of hospitals** (worse / same / better counts), not state-aggregated rates. HCAHPS state file has actual % values.

## 9. NCI / CDC US Cancer Statistics — incidence + mortality by site
- **File:** `nci_cancer.csv` — 1,140,819 rows × 11 cols (107 MB), pipe-delimited (`sep="|"`) + dictionary in `uscs_data_dictionary.xlsx`
- **Years:** 1999–2023
- **Source:** [CDC USCS 1999–2022 ASCII bundle](https://www.cdc.gov/cancer/uscs/USCS-1999-2022-ASCII.zip), file `BYAREA.TXT`
- **Granularity:** state × year × cancer site (27 sites) × race (12 categories) × sex (3) × event type (Incidence / Mortality)
- **What it gives:** `AGE_ADJUSTED_RATE` (per 100k), `COUNT`, `POPULATION`, `AGE_ADJUSTED_CI_LOWER/UPPER`. Both incidence and mortality in one file.

## 10. Census ACS 5-year Demographics (state-level)
- **File:** `acs_demographics.csv` — 52 rows × 22 cols (8 KB)
- **Years:** 2019–2023 5-year estimates (from `/acs/acs5/2023` endpoint)
- **Source:** [Census ACS 5-year API](https://api.census.gov/data/2023/acs/acs5?get=NAME,B01001_001E,B19013_001E,B15003_001E,B15003_022E,B15003_023E,B15003_024E,B15003_025E,B18101_001E,B18101_004E,B18101_007E,B18101_010E,B18101_013E,B18101_016E,B18101_019E,B18101_023E,B18101_026E,B18101_029E,B18101_032E,B18101_035E,B18101_038E&for=state:*)
- **Granularity:** 50 states + DC + PR
- **What it gives:** Total population, median household income, educational attainment subcomponents (compute `BACHELORS_PLUS_PCT` from B15003_022/023/024/025 ÷ B15003_001), disability subcomponents (compute `WITH_DISABILITY_PCT` by summing 12 B18101 subcategories ÷ B18101_001)

## 11. HRSA FQHC Site Roster
- **File:** `hrsa_fqhc.csv` — 18,880 rows × 56 cols (13.5 MB)
- **Years:** Snapshot (no time dimension)
- **Source:** [HRSA Health Center Service Delivery and Look-Alike Sites](https://data.hrsa.gov/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv)
- **Granularity:** site-level (one row per service delivery site)
- **What it gives:** Site identity, address, lat/lon, FQHC vs Look-Alike, status, hours, operating schedule, county/HHS region/congressional district. **Does not include patients-served — that's in #18 UDS.**

## 12. CDC NCHS Leading Causes of Death — state mortality
- **File:** `cdc_mortality.csv` — 10,868 rows × 6 cols (965 KB)
- **Years:** 1999–2017 (CDC's last published CSV-downloadable state-level age-adjusted mortality file; newer requires CDC Wonder XML API)
- **Source:** [NCHS - Leading Causes of Death](https://data.cdc.gov/resource/bi63-dtpu.csv?$limit=20000) — Socrata `bi63-dtpu`
- **Granularity:** state × year × cause (11 leading causes + "All causes")
- **What it gives:** `aadr` (age-adjusted death rate per 100,000), `deaths` (raw count), `cause_name`, `_113_cause_name` (NCHS technical classification)

## 13. SAMHSA FindTreatment.gov Locator — facilities
- **File:** `samhsa_facilities.csv` — 87,549 rows × 19 cols (27 MB)
- **Years:** Snapshot (current)
- **Source:** [FindTreatment.gov locator API](https://findtreatment.gov/locator/exportsAsJson/v2) — paginated state-by-state pull, deduplicated on (name, city, state, phone). N-SUMHSS PUF was attempted first but SAMHSA's `/data/system/files/media-puf-file/` returns 403.
- **Granularity:** facility-level
- **What it gives:** Facility identity, lat/lon, type_of_care, service_setting, payment_accepted, treatment approaches, special programs, derived flags (`is_substance_use`, `is_mental_health`, `is_co_occurring`)
- **Caveat:** Counts are higher than N-SUMHSS would report — FindTreatment includes individual buprenorphine prescribers and OTPs

## 14. CMS Medicare Inpatient by Geography & Service (state × DRG)
- **File:** `cms_inpatient_geo.csv` — 26,479 rows × 9 cols (3.0 MB)
- **Years:** 2023 (RY25 release, single-year file)
- **Source:** [Medicare Inpatient Hospitals - by Geography and Service](https://data.cms.gov/sites/default/files/2025-04/3b718a11-a28d-4c38-a13b-2c6eeb649980/MUP_PHY_R25_P05_V20_D23_Geo.csv)
- **Granularity:** state × DRG (739 DRGs × 51 states + 773 national rows)
- **What it gives:** `Tot_Dschrgs`, `Avg_Submtd_Cvrd_Chrg`, `Avg_Tot_Pymt_Amt`, `Avg_Mdcr_Pymt_Amt` per DRG per state. **(Substituted for AHRQ HCUP — bulk HCUP data is gated.)**

## 15. CDC VSRR Provisional Drug Overdose Death Counts
- **File:** `cdc_drug_overdose.csv` — 82,530 rows × 12 cols (17 MB)
- **Years:** 2015 – Oct 2025 (provisional)
- **Source:** [VSRR Provisional Drug Overdose Death Counts](https://data.cdc.gov/resource/xkb8-kh2a.csv?$limit=200000) — Socrata `xkb8-kh2a`
- **Granularity:** state × year × month × indicator (rolling 12-month-ending counts)
- **What it gives:** 12 indicators including total overdose deaths, Cocaine (T40.5), Heroin (T40.1), Methadone (T40.3), Natural/semi-synthetic opioids (T40.2), Synthetic opioids excl. methadone (T40.4 = fentanyl), Psychostimulants (T43.6). Has lag-adjusted `predicted_value`.

## 16. HRSA UDS — FQHC patients served (Tables 3A/4/5 joined)
- **File:** `hrsa_uds.csv` — 1,359 rows × 17 cols (180 KB) + source `hrsa_uds_h80_2024.xlsx` (23 MB, 37 sheets, manually downloaded — see note)
- **Years:** 2024 (single reporting year)
- **Source:** HRSA H80 Awardee UDS — `https://www.hrsa.gov/sites/default/files/hrsa/foia/h80-2024.xlsx`. **Note:** `www.hrsa.gov` returns 403 to programmatic clients; this file was downloaded manually via browser, then processed.
- **Granularity:** health-center-level (one row per FQHC awardee)
- **What it gives:** State, name, address, urban/rural, total patients, male/female patients (Table 3A), Medicaid + Public Insurance patient counts (Table 4), medical clinic visits + virtual visits + dental visits (Table 5)
- **Sanity:** 32.4M total patients served by all FQHCs in 2024 ✓

## 17. CMS Nursing Home — Provider Information
- **File:** `cms_nursing_home.csv` — 14,703 rows × 99 cols (9.1 MB)
- **Snapshot:** March 2026
- **Source:** [CMS Provider Data Catalog — Nursing Home Provider Information](https://data.cms.gov/provider-data/sites/default/files/resources/3059e5643c76d35f1185eb1ee2f38d63_1773439550/NH_ProviderInfo_Mar2026.csv) — resource `4pq5-n9py`
- **Granularity:** facility-level (one row per CMS-certified nursing home)
- **What it gives:** Identity (CCN, name, address, ownership, chain), beds, residents/day, **5-star ratings** (Overall, Health Inspection, Staffing, QM Long-Stay, QM Short-Stay), staffing hours-per-resident-per-day (RN, LPN, Nurse Aide, PT — Reported / Case-Mix / Adjusted), deficiencies per Rating Cycle (1, 2/3) with Health Deficiency Score, penalties

## 18. CMS Medicare Physician & Other Practitioners — by Geography & Service
- **File:** `cms_physician_payments.csv` — 268,634 rows × 15 cols (42 MB)
- **Years:** 2023 (RY25 release)
- **Source:** [Medicare Physician & Other Practitioners by Geography & Service](https://data.cms.gov/sites/default/files/2025-04/3b718a11-a28d-4c38-a13b-2c6eeb649980/MUP_PHY_R25_P05_V20_D23_Geo.csv)
- **Granularity:** Geo × HCPCS code × Place of Service
- **What it gives:** `Tot_Rndrng_Prvdrs`, `Tot_Benes`, `Tot_Srvcs`, `Avg_Sbmtd_Chrg`, `Avg_Mdcr_Alowd_Amt`, `Avg_Mdcr_Pymt_Amt`, `Avg_Mdcr_Stdzd_Amt`. Note: this is HCPCS-by-state, not by-specialty (CMS doesn't publish state×specialty as a single CSV).

## 19. CMS Open Payments — General Payments (state-aggregated 2023)
- **File:** `cms_open_payments.csv` — 60 rows × 6 cols (2.2 KB)
- **Year:** 2023 program year
- **Source:** Streamed from [`OP_DTL_GNRL_PGYR2023`](https://download.cms.gov/openpayments/PGYR2023_P01232026_01102026/OP_DTL_GNRL_PGYR2023_P01232026_01102026.csv) (raw 14.7M rows / ~5+ GB) and aggregated server-side by `Recipient_State`. Only the state summary saved.
- **What it gives:** Per state: `n_payments`, `n_unique_recipients` (NPIs + teaching hospitals), `n_unique_manufacturers`, `total_usd`. National total: $3.31B in 2023 ✓

## 20. BLS OES — Healthcare Wages by State (May 2024)
- **File:** `bls_healthcare_wages.csv` — 4,136 rows × 32 cols (800 KB)
- **Year:** May 2024 OEWS estimates
- **Source:** [BLS OES state file `oesm24st.zip`](https://www.bls.gov/oes/special-requests/oesm24st.zip), filtered to SOC codes starting `29-` (practitioners) or `31-` (support). **Note:** BLS rejects generic User-Agents; use UA with email contact (e.g. `Healthcare-Intel-Platform contact@example.com`).
- **Granularity:** state × healthcare occupation (90 SOC codes × 54 areas)
- **What it gives:** Employment counts (`TOT_EMP`, `JOBS_1000`, `LOC_QUOTIENT`), wage percentiles hourly + annual (`H_MEAN`, `H_PCT10/25/MEDIAN/75/90`, `A_MEAN`, `A_PCT10/25/MEDIAN/75/90`)
- **Overlap note:** Conceptually overlaps AHRF (#2) which also has `*_emplymt_24` and `*_medn_wage_24` from BLS. BLS adds wage *percentiles* and finer SOC granularity.

## 21. USDA Food Access Research Atlas (food deserts by census tract)
- **Files:** `usda_food_access.csv` — 72,531 rows × 147 cols (47 MB) + dictionary `usda_food_access_dictionary.csv`
- **Year:** 2019 (USDA's most recent published version)
- **Source:** [USDA ERS Food Access Research Atlas](https://ers.usda.gov/media/5627/food-access-research-atlas-data-download-2019.zip?v=77599)
- **Granularity:** census tract level
- **What it gives:** Tract identity, population, urban flag, poverty rate, median family income, multiple food-desert flags (`LILATracts_*` for Low-Income+Low-Access at varying distance thresholds), distance-to-store flags, vehicle access flag

## 22. HUD Fair Market Rents — FY2026 (revised)
- **File:** `hud_fair_market_rents.csv` — 4,764 rows × 14 cols (550 KB)
- **Year:** FY2026 (uses 2023 ACS data)
- **Source:** [HUD FMR FY2026 (revised)](https://www.huduser.gov/portal/datasets/fmr/fmr2026/FY26_FMRs_revised.xlsx) — converted from XLSX (required patching malformed `docProps/core.xml` date format inside the zipped XLSX)
- **Granularity:** county / county-subdivision per HUD FMR area
- **What it gives:** State, HUD area code, county/town name, metro flag, population, **40th-percentile rent** for 0/1/2/3/4-bedroom units (`fmr_0` through `fmr_4`)

## 23. Census SAIPE — Small Area Income & Poverty Estimates
- **File:** `census_saipe.csv` — 67,059 rows × 9 cols (3.7 MB)
- **Years:** 2003–2023 (21 years)
- **Source:** [Census SAIPE timeseries API](https://api.census.gov/data/timeseries/poverty/saipe?get=NAME,SAEPOVRTALL_PT,SAEMHI_PT,SAEPOVRT0_17_PT,SAEPOVALL_PT) — paginated by year × geography
- **Granularity:** Both county (3,159 unique) and state (51) in same file, distinguished by `geo_lvl`
- **What it gives:** `SAEPOVRTALL_PT` (poverty rate all ages, %), `SAEMHI_PT` (median HH income $), `SAEPOVRT0_17_PT` (poverty rate under 18), `SAEPOVALL_PT` (count in poverty)

## 24. CMS Home Health Care Agencies
- **File:** `cms_home_health.csv` — 12,392 rows × 96 cols (12.7 MB)
- **Snapshot:** April 2026
- **Source:** [CMS Provider Data Catalog — Home Health Care Agencies](https://data.cms.gov/provider-data/sites/default/files/resources/f9a309e9463cdf0a7d7828f8d8d0e653_1775505949/HH_Provider_Apr2026.csv) — resource `6jpm-sxkc`
- **Granularity:** facility-level (one row per Medicare-certified home health agency)
- **What it gives:** Agency identity (CCN, name, address, ownership), services offered (Y/N for nursing / PT / OT / speech / medical social / home health aide), **`Quality of patient care star rating` (1–5★)**, plus dozens of process measure rates (timely care initiation, flu vaccination, depression assessment, fall risk, pain assessment, etc.)

## 25. California HCAI — Hospital Annual Utilization Report
- **File:** `ca_hcai.csv` — 226,902 rows × 49 cols (111 MB) — **California-only**
- **Years:** 2012–2017
- **Source:** [CHHS Open Data — Hospital Annual Utilization Report (machine-readable)](https://data.chhs.ca.gov/dataset/1902083c-f16a-434d-b8ac-f7a573a305df/resource/78622c04-a158-4c95-8ea3-7660725e9526/download/2012_current_year_hosp_util_mr.csv) — original is Windows-1252, converted to UTF-8 on disk
- **Granularity:** Long format — one row per (facility × year × measure)
- **What it gives:** Facility identity (OSHPD_ID, name, address, lat/lon, county), characteristics (TYPE_LIC, TYPE_CNTRL, trauma center, teaching hospital), admin geography (assembly / senate / congressional district, census tract, health service area), and reported measures encoded by `Measure/Variable` code with description and Amount/Response

---

## Blocked / not pulled

- **EPA EJSCREEN** — environmental justice indicators by census block group. EPA's `gaftp.epa.gov/EJScreen/` returns 404 (tool was reportedly removed from epa.gov in early 2025). Zenodo mirror at `https://zenodo.org/records/14767363` exists but the 2024 file is 5.2 GB and our IP was rate-limited (403 from Zenodo's anti-abuse system) during exploration. **Recommended path:** download `2024.zip` manually via browser, drop at `data/ejscreen_2024.zip`, then run a stream-aggregator to roll BG → county.

---

## Pre-existing files (not part of Phase 2)

- **`part_d.csv`** — 28,255 rows × 11 cols (32 MB) — CMS Part D drug spending by drug. Loaded by `data_loader.fetch_part_d_data()`.
- **`part_b.csv`** — 734 rows × 47 cols (310 KB) — CMS Part B drug spending by HCPCS. Loaded by `data_loader.fetch_part_b_data()`.

---

## Loaders implemented in `data_loader.py`

- `fetch_part_d_data()` — Part D
- `fetch_part_b_data()` — Part B
- `load_geo_variation()` — #1
- `load_ahrf()` — #2
- `load_hpsa()` — #3 (concatenates all 3 disciplines, filters to `Designated`)

The other 22 datasets do not yet have wrapper loaders — they are read directly by future analysis code.
