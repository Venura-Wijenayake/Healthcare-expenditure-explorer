# U.S. Healthcare Intelligence Platform — Data Manifest

The `data/` directory is gitignored. This manifest documents every dataset, its source, and how to re-fetch it. To rebuild the data layer from scratch, follow the URLs below or run the corresponding script in `scripts/`.

**Inventory:** **81 datasets** across CMS, HRSA, CDC, AHRQ, NIH, NIMH, NCI, ONC, FDA, SAMHSA, Census, BLS, USDA, HUD, DOT, FCC, EPA, OSHA, AoA, RWJF, and California HCAI.

**Total disk usage:** ~1.28 GB across 86 files (81 datasets + 4 data dictionaries + this manifest + `ahrf_tech_docs/`).

**Coverage at a glance:**
- **Geographic:** national, all 50 states + DC + territories (PR/GU/VI/AS/MP), ~3,200 counties, ~73,000 census tracts (food access), ~245,000 census tracts (CDC PLACES rolled up to county)
- **Temporal:** longest series 1999–2025 (CDC mortality + cancer); most recent administrative snapshots dated through April 2026
- **Domains covered:** spending, enrollment, utilization, quality, workforce supply + projections, prescribing, mental health, substance use, communicable disease, chronic disease, maternal-child health, environmental + social determinants (broadband, food access, rent, transportation), nutrition assistance, vaccination, EHR adoption, payment-model participation

---

## CMS Medicare — Core Spending & Utilization (1–9)

### 1. CMS Medicare Geographic Variation
- **File:** `geo_variation_2014_2023.csv` — 33,639 rows × 247 cols (52.8 MB)
- **Years:** 2014–2023 (annual)
- **Source:** [CMS Medicare Geographic Variation by National, State & County](https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-geographic-comparisons/medicare-geographic-variation-by-national-state-county) — direct CSV via dataset UUID `6219697b-8f6c-4164-bed4-cd9317c58ebc`
- **Granularity:** national / state / county × age level (All / <65 / ≥65)
- **What it gives:** Medicare FFS spending (raw + standardized), beneficiary counts (FFS / MA / total), Part A+B coverage, demographics (sex / race / dual %), risk score, and 200+ service-line breakdowns (IP / SNF / HHA / HOS / OP) including utilization (admits / ED visits / readmits) and quality (ACSC, mortality)

### 2. CMS Medicare Monthly Enrollment (additive fields only)
- **File:** `cms_enrollment_additive.csv` — 9,802 rows × 26 cols (1.9 MB)
- **Years:** 2013–2025 (monthly + annual aggregates)
- **Source:** [Medicare Monthly Enrollment](https://data.cms.gov/sites/default/files/2026-03/c2e42f20-57f6-4bbf-95a7-5267cec3f77c/Medicare%20Monthly%20Enrollment%20Data_December%202025.csv) — filtered to state-level + scoped to **additive** columns only (Part D, dual eligibility, ESRD splits) to avoid duplicating geo_variation's enrollment fields
- **Granularity:** state × year × month (12 months + "Year" annual aggregate)
- **What it gives:** Part D enrollment (PDP / MA-PD / LIS tiers), dual eligibility counts (Full / Partial / QMB / SLMB / QDWI), ESRD breakdowns
- **Dropped (overlap with #1):** `TOT_BENES`, `ORGNL_MDCR_BENES`, `MA_AND_OTH_BENES`, sex/race/age count breakdowns

### 3. CMS Medicare Inpatient by Geography & Service (state × DRG)
- **File:** `cms_inpatient_geo.csv` — 26,479 rows × 9 cols (3.0 MB)
- **Year:** 2023 (RY25 release, single-year file)
- **Source:** [Medicare Inpatient Hospitals — by Geography and Service](https://data.cms.gov/sites/default/files/2025-04/3b718a11-a28d-4c38-a13b-2c6eeb649980/MUP_PHY_R25_P05_V20_D23_Geo.csv)
- **Granularity:** state × DRG (739 DRGs × 51 states + 773 national rows)
- **What it gives:** `Tot_Dschrgs`, `Avg_Submtd_Cvrd_Chrg`, `Avg_Tot_Pymt_Amt`, `Avg_Mdcr_Pymt_Amt` per DRG per state. **(Substituted for AHRQ HCUP — bulk HCUP data is gated.)**

### 4. CMS Medicare Physician & Other Practitioners — by Geography & Service
- **File:** `cms_physician_payments.csv` — 268,634 rows × 15 cols (42 MB)
- **Year:** 2023 (RY25 release)
- **Source:** [Medicare Physician & Other Practitioners by Geography & Service](https://data.cms.gov/sites/default/files/2025-04/3b718a11-a28d-4c38-a13b-2c6eeb649980/MUP_PHY_R25_P05_V20_D23_Geo.csv)
- **Granularity:** Geo × HCPCS code × Place of Service
- **What it gives:** `Tot_Rndrng_Prvdrs`, `Tot_Benes`, `Tot_Srvcs`, `Avg_Sbmtd_Chrg`, `Avg_Mdcr_Alowd_Amt`, `Avg_Mdcr_Pymt_Amt`, `Avg_Mdcr_Stdzd_Amt`. HCPCS-by-state, not by-specialty (CMS doesn't publish state×specialty as a single CSV).

### 5. CMS Medicare Part D Prescribers — by Provider (state × specialty aggregation)
- **File:** `cms_partd_prescribers.csv` — 5,299 rows × 65 cols (2.3 MB)
- **Year:** 2023 (RY25 release)
- **Source:** [Medicare Part D Prescribers — by Provider](https://data.cms.gov/sites/default/files/2025-04/750769a3-bb0f-4f05-81dc-7dcb6e105cb0/MUP_DPR_RY25_P04_V10_DY23_NPI.csv) — 582 MB raw with 1.38M provider rows; aggregated client-side via `scripts/fetch_partd_prescribers.py` (chunked 200k pandas reads, group by `Prscrbr_State_Abrvtn` × `Prscrbr_Type`).
- **Granularity:** state × prescriber specialty (62 state codes × 204 specialties)
- **What it gives:** `provider_count`, total claims/beneficiaries/drug cost, brand/generic/opioid/MAPD/PDP/LIS shares (derived ratios), opioid + antibiotic + antipsychotic claims and cost, beneficiary demographics (age/sex/race/dual counts), claims-weighted `bene_avg_age` and `bene_avg_risk_scre`. **No drug names** (those live in #6) — this captures *who prescribes* by specialty.

### 6. CMS Medicare Part D Drug Spending (drug-level)
- **File:** `part_d.csv` — 28,255 rows × 11 cols (32 MB)
- **Source:** CMS Part D Spending by Drug (loaded by `data_loader.fetch_part_d_data()`)
- **Granularity:** drug name × year
- **What it gives:** Annual spending, claims, beneficiary counts, average cost per dose unit per drug.

### 7. CMS Medicare Part B Drug Spending (HCPCS-level)
- **File:** `part_b.csv` — 734 rows × 47 cols (310 KB)
- **Source:** CMS Part B Spending by HCPCS (loaded by `data_loader.fetch_part_b_data()`)
- **Granularity:** HCPCS code × year
- **What it gives:** Spending and utilization for physician-administered drugs paid under Part B.

### 8. CMS Medicare Chronic Conditions Prevalence
- **File:** `cms_chronic_conditions.csv` — 83,160 rows × 7 cols (4.2 MB)
- **Source:** CMS Chronic Conditions Data Warehouse public summary tables; parsed by `scripts/parse_cms_chronic.py`
- **Granularity:** state × year × sex × age band × condition
- **Key columns:** `year`, `state`, `state_fips`, `sex`, `age_band`, `condition`, `prevalence_pct`
- **What it gives:** Beneficiary-level prevalence rates for the 21 CMS-tracked chronic conditions (heart failure, diabetes, COPD, depression, Alzheimer's, etc.) stratified by sex × age band.

### 9. CMS Open Payments — General Payments (state-aggregated)
- **File:** `cms_open_payments.csv` — 60 rows × 6 cols (2.2 KB)
- **Year:** 2023 program year
- **Source:** Streamed from [`OP_DTL_GNRL_PGYR2023`](https://download.cms.gov/openpayments/PGYR2023_P01232026_01102026/OP_DTL_GNRL_PGYR2023_P01232026_01102026.csv) (raw 14.7M rows / ~5+ GB) and aggregated server-side by `Recipient_State`.
- **What it gives:** Per state: `n_payments`, `n_unique_recipients` (NPIs + teaching hospitals), `n_unique_manufacturers`, `total_usd`. National total: $3.31B in 2023 ✓

---

## CMS Medicare — Facilities & Quality (10–19)

### 10. CMS Hospital Compare — HCAHPS (patient satisfaction)
- **File:** `hospital_compare_hcahps_state.csv` — 2,856 × 8 (570 KB)
- **Source:** CMS Provider Data Catalog resource `84jm-wiui`
- **Granularity:** state × HCAHPS measure
- **What it gives:** Actual % top-box scores by state for 12 HCAHPS dimensions (communication with nurses, doctors, hospital cleanliness, etc.).

### 11. CMS Hospital Compare — Unplanned Hospital Visits
- **File:** `hospital_compare_readmissions_state.csv` — 784 × 14 (133 KB)
- **Source:** CMS Provider Data Catalog resource `4gkm-5ypv`
- **Granularity:** state × readmission/ED-visit measure
- **What it gives:** Distribution of hospitals (worse / same / better than national) per measure. **Not** state-aggregated rates.

### 12. CMS Hospital Compare — Complications & Deaths
- **File:** `hospital_compare_complications_state.csv` — 1,120 × 10 (104 KB)
- **Source:** CMS Provider Data Catalog resource `bs2r-24vh`
- **Granularity:** state × complication/mortality measure
- **What it gives:** Distribution of hospitals per measure (PSI-90, surgical complications, 30-day mortality by condition).

### 13. CMS Hospital Compare — General Info (hospital roster + star ratings)
- **File:** `hospital_compare_general_info.csv` — 5,426 × 38 (1.5 MB)
- **Source:** CMS Provider Data Catalog resource `xubh-q36u`
- **Granularity:** facility-level (one row per Medicare-certified hospital)
- **What it gives:** Hospital identity (CCN, name, address, ownership, type), 1–5 ★ overall rating, per-domain measure counts, emergency services flag.

### 14. CMS Nursing Home Provider Information
- **File:** `cms_nursing_home.csv` — 14,703 rows × 99 cols (9.1 MB)
- **Snapshot:** March 2026
- **Source:** [CMS Provider Data Catalog — Nursing Home Provider Information](https://data.cms.gov/provider-data/sites/default/files/resources/3059e5643c76d35f1185eb1ee2f38d63_1773439550/NH_ProviderInfo_Mar2026.csv) — resource `4pq5-n9py`
- **Granularity:** facility-level (one row per CMS-certified nursing home)
- **What it gives:** Identity (CCN, name, address, ownership, chain), beds, residents/day, **5-star ratings** (Overall, Health Inspection, Staffing, QM Long-Stay, QM Short-Stay), staffing hours-per-resident-per-day (RN, LPN, Nurse Aide, PT — Reported / Case-Mix / Adjusted), deficiencies per Rating Cycle with Health Deficiency Score, penalties.

### 15. CMS Home Health Care Agencies
- **File:** `cms_home_health.csv` — 12,392 rows × 96 cols (12.7 MB)
- **Snapshot:** April 2026
- **Source:** [CMS Provider Data Catalog — Home Health Care Agencies](https://data.cms.gov/provider-data/sites/default/files/resources/f9a309e9463cdf0a7d7828f8d8d0e653_1775505949/HH_Provider_Apr2026.csv) — resource `6jpm-sxkc`
- **Granularity:** facility-level (one row per Medicare-certified home health agency)
- **What it gives:** Agency identity, services offered (Y/N for nursing / PT / OT / speech / medical social / aide), **quality-of-patient-care 1–5★ rating**, and dozens of process measure rates (timely care, flu vaccination, depression screening, fall risk, pain assessment).

### 16. CMS Hospice — Provider Information
- **File:** `cms_hospice.csv` — 6,943 rows × 131 cols (8.2 MB)
- **Source:** CMS Provider Data Catalog — Hospice Provider Information
- **Granularity:** facility-level (one row per Medicare-certified hospice)
- **What it gives:** Identity (CCN, name, address, ownership), service area, certification dates, CAHPS Hospice Survey scores (% top-box across 8 measures), HQRP Star Rating, family caregiver experience metrics.

### 17. CMS Dialysis Facility Compare
- **File:** `cms_dialysis.csv` — 7,557 rows × 142 cols (7.3 MB)
- **Source:** CMS Provider Data Catalog — Dialysis Facility (5-Star quality program)
- **Granularity:** facility-level (one row per CMS-certified ESRD facility)
- **What it gives:** Facility identity (CCN, name, address, network, chain ownership), bed/station counts, **5-star quality rating**, transplant waitlist %, hospitalization rate, mortality rate, vascular access type %, fluid management metrics.

### 18. CMS Hospital Price Transparency Enforcement
- **File:** `cms_hospital_prices.csv` — 10,726 rows × 7 cols (1.0 MB)
- **Source:** CMS Hospital Price Transparency rule enforcement actions
- **Granularity:** action-level (one row per CMS notice/enforcement action against a hospital)
- **What it gives:** Hospital identity, address, action type, date — useful as a compliance/enforcement tracker, **not** as a price file (the underlying machine-readable price files are hospital-published and not aggregated by CMS).

### 19. CMS Medicare Advantage Star Ratings
- **File:** `cms_ma_star_ratings.csv` — 2,415 rows × 17 cols (390 KB)
- **Source:** CMS MA Star Ratings annual release
- **Granularity:** contract-level (one row per MA / MA-PD / PDP contract per rating year)
- **Key columns:** `Star Rating Year`, `Contract Number`, `Organization Type`, `Contract Name`, `Parent Organization`, `SNP`, `Part C Summary`, `Part D Summary`, `Overall`
- **What it gives:** Plan-level 1–5 ★ ratings on Part C (medical) and Part D (drug) summary scores, plus overall composite. Useful for joining to enrollment data to weight quality by membership.

---

## CMS Programs — APMs & Medicaid (20–22)

### 20. CMS Medicare Shared Savings Program ACOs
- **File:** `cms_aco.csv` — 5,001 rows × 314 cols (5.1 MB)
- **Source:** CMS Shared Savings Program ACOs Public Use File (multi-year)
- **Granularity:** ACO × performance year
- **What it gives:** ACO identity (`ACO_Num`, `ACO_NAME`, `Start_Date`, `Track2`, `Adv_Pay`), assigned beneficiaries (`N_AB`), benchmark (`MinSavPerc`, `BnchmkMinExp`), generated savings/losses, ~30 quality measure scores. Statutory permanent program — distinct from CMMI demos in #21.

### 21. CMS Innovation Center (CMMI) Model Participants
- **File:** `cms_innovation.csv` — 3,498 rows × 18 cols (904 KB)
- **Snapshot:** February 20, 2026
- **Source:** [Innovation Center Model Participants — data.cms.gov](https://data.cms.gov/cms-innovation-center-programs/cms-innovation-models-overview/innovation-center-model-participants); direct CSV `Innovation_Center_Model_Participants-ACOREACH_2_20_26.csv`
- **Granularity:** participating organization × CMMI model
- **What it gives:** 17 active CMMI models including Primary Care First (1,705), MD Total Cost of Care (537), Enhancing Oncology Model (372), GUIDE Dementia (327), BPCI Advanced (208), ACO REACH (75), Next Generation ACO (35), Making Care Primary (117), MA VBID (19), Vermont All-Payer (1). Columns: `Name of Initiative`, `Organization Name`, `State`, `Category`, `MSA_Name`, lat/lon. **Distinct from #20** (MSSP is statutory, CMMI is demo).

### 22. CMS Medicaid State Drug Utilization (state-aggregated)
- **File:** `cms_medicaid_drug.csv` — 522 rows × 8 cols (39 KB)
- **Years:** Multi-year, state-aggregated
- **Source:** CMS State Drug Utilization Data; aggregated by `scripts/fetch_medicaid_drug.py`
- **Granularity:** state × year
- **What it gives:** Total `units_reimbursed`, `number_of_prescriptions`, `total_amount_reimbursed`, Medicaid vs non-Medicaid splits, NDC record count.

---

## HRSA — Workforce, Access, Programs (23–34)

### 23. HRSA Area Health Resources File (AHRF) — state + national
- **File:** `ahrf_state_national_2025.csv` — 52 rows × 1,448 cols (250 KB) + tech docs in `ahrf_tech_docs/`
- **Years:** 2024–2025 release (variable years per column, suffixes `_23` / `_24`)
- **Source:** [HRSA Data Downloads — AHRF](https://data.hrsa.gov/DataDownload/AHRF/AHRF_SN_2024-2025_CSV.zip)
- **Granularity:** 50 states + DC + US national
- **What it gives:** Workforce supply by profession (physicians, RNs, LPNs, dentists, PAs, psychologists, pharmacists, etc.) — counts, demographic breakdowns, employment status (`*_emplymt_24`), median wage (`*_medn_wage_24`), plus population denominators (`popn_*`). Naming convention `<profession>_<metric>_<year>`.

### 24. HRSA HPSA — Primary Care
- **File:** `hpsa_primary_care.csv` — 77,724 rows × 66 cols (47 MB)
- **Source:** HRSA Data Warehouse — `https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv`
- **Granularity:** designation-level (one row per HPSA designation)
- **What it gives:** HPSA score, designated population, underserved population, FTE practitioners needed, designation type (Geographic / Population / Facility), rural status, lat/lon, county FIPS. Filter `HPSA Status == 'Designated'` for currently active.

### 25. HRSA HPSA — Dental
- **File:** `hpsa_dental.csv` — 45,176 rows × 65 cols (27 MB)
- **Source:** HRSA Data Warehouse — `BCD_HPSA_FCT_DET_DH.csv`
- Same schema as #24, dental discipline.

### 26. HRSA HPSA — Mental Health
- **File:** `hpsa_mental_health.csv` — 39,517 rows × 65 cols (24 MB)
- **Source:** HRSA Data Warehouse — `BCD_HPSA_FCT_DET_MH.csv`
- Same schema as #24, mental health discipline.

### 27. HRSA FQHC Site Roster
- **File:** `hrsa_fqhc.csv` — 18,880 rows × 56 cols (13.5 MB)
- **Snapshot:** Current (no time dimension)
- **Source:** [HRSA Health Center Service Delivery and Look-Alike Sites](https://data.hrsa.gov/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv)
- **Granularity:** site-level
- **What it gives:** Site identity, address, lat/lon, FQHC vs Look-Alike, status, hours, schedule, county/HHS region/congressional district. Patients-served counts live in #28.

### 28. HRSA UDS — FQHC Patients Served (cleaned)
- **File:** `hrsa_uds.csv` — 1,359 rows × 17 cols (180 KB)
- **Year:** 2024
- **Source:** Derived from #29 (Tables 3A/4/5 joined per awardee)
- **Granularity:** awardee-level (one row per H80 grantee)
- **What it gives:** State, name, address, urban/rural, total patients, M/F split (T3A), Medicaid + public-insurance counts (T4), medical/virtual/dental visits (T5).
- **Sanity check:** 32.4M total FQHC patients served in 2024 ✓

### 29. HRSA UDS H80 — Raw Awardee Workbook
- **File:** `hrsa_uds_h80_2024.xlsx` — 23 MB, 37 sheets
- **Year:** 2024
- **Source:** `https://www.hrsa.gov/sites/default/files/hrsa/foia/h80-2024.xlsx` — **note:** `www.hrsa.gov` returns 403 to programmatic clients; downloaded manually via browser.
- **Granularity:** 37 UDS reporting tables (1A, 1B, 2, 3A, 3B, 4, 5, 5A, 6A, 6B, 7, 8A, 9D, 9E, 10, 11–15, etc.) — one sheet per table
- **What it gives:** Full UDS workbook (demographics, chronic conditions seen, procedures, financial data) — much richer than the 17-column extract in #28.

### 30. HRSA Grants
- **File:** `hrsa_grants.csv` — 114,289 rows × 44 cols (88 MB)
- **Source:** HRSA grants public dataset (multi-year)
- **Granularity:** grant award-level
- **Key columns:** `Award Year`, `Financial Assistance`, `Grantee Name`, `Grantee City/State`, `Grantee Region Code`, plus program descriptors
- **What it gives:** Federal financial assistance from HRSA across all programs (Health Centers, Maternal & Child Health, Workforce, Ryan White, etc.) — useful for tracking flows of HRSA funding to organizations and states over time.

### 31. HRSA Maternal & Child Health (Title V)
- **File:** `hrsa_mch.csv` — 630,430 rows × 18 cols (100 MB)
- **Source:** HRSA Maternal & Child Health Bureau Title V Information System (TVIS)
- **Granularity:** state × year × measure × stratifier
- **Key columns:** `Measure Type`, `Measure`, `Measure Name`, `Data Source`, `State`, `Region`, `Year`, `Stratifier`
- **What it gives:** National Performance Measures (NPMs), National Outcome Measures (NOMs), and state-specific measures across the MCH lifecourse (preconception, prenatal, infant, child, CSHCN, adolescent). Long format.

### 32. HRSA Ryan White HIV/AIDS Program
- **File:** `hrsa_ryan_white.csv` — 2,200 rows × 61 cols (1.9 MB)
- **Source:** HRSA Ryan White recipient/sub-recipient roster
- **Granularity:** recipient/sub-recipient level
- **What it gives:** Provider identity, address, HAB Provider Type, indicators for Parts A–F funding received, services offered.

### 33. HRSA Telehealth Use (Medicare beneficiary stratifications)
- **File:** `hrsa_telehealth.csv` — 33,712 rows × 13 cols (2.6 MB)
- **Source:** HRSA telehealth data (Medicare claims-derived)
- **Granularity:** quarter × beneficiary geography × Medicare/Medicaid enrollment status × race × sex × entitlement status × age
- **What it gives:** Telehealth utilization rates and visit volumes broken out by beneficiary demographics — service-program data, **not** infrastructure (broadband infrastructure lives in #70).

### 34. HRSA Workforce Projections
- **File:** `hrsa_workforce_projections.csv` — 102,528 rows × 24 cols (58 MB)
- **Source:** HRSA Bureau of Health Workforce supply/demand model output
- **Granularity:** year × profession group × profession × state × rurality × scenario
- **Key columns:** `Year`, `Profession Group`, `Profession`, `State`, `Rurality`, plus scenario flags (`Fewer Graduates`, etc.)
- **What it gives:** Modeled supply, demand, and shortage projections (FTEs) for ~30 health professions out to ~2037 under multiple scenarios.

---

## CDC — Mortality, Morbidity, Surveillance (35–50)

### 35. CDC NCHS Leading Causes of Death — 1999–2017
- **File:** `cdc_mortality.csv` — 10,868 rows × 6 cols (965 KB)
- **Years:** 1999–2017 (last CDC-published CSV-downloadable state-level age-adjusted file; newer requires WONDER XML API)
- **Source:** [NCHS — Leading Causes of Death](https://data.cdc.gov/resource/bi63-dtpu.csv?$limit=20000) — Socrata `bi63-dtpu`
- **Granularity:** state × year × cause (11 leading causes + "All causes")
- **What it gives:** `aadr` (age-adjusted death rate per 100,000), `deaths`, `cause_name`, `_113_cause_name`.

### 36. CDC WONDER Mortality — 2018–2023 (extends #35)
- **File:** `cdc_wonder_mortality.csv` — 4,644 rows × 6 cols (263 KB)
- **Years:** **2018–2023** (fills the gap left by #35)
- **Source:** Socrata `3yf8-kanr` (Weekly Counts by Cause 2014–2019, filtered ≥2018) + `muzy-jte6` (Weekly Provisional 2020–2023); ACS state population for denominators. Script: `scripts/fetch_cdc_wonder_mortality.py`. *Note:* WONDER UCD APIs (D76/D77/D158/D159) explicitly forbid sub-national groupings — Socrata weekly aggregates were the workable path.
- **Granularity:** year × state × cause (13 causes 2018–2019, 15 causes 2020–2023 — adds COVID-19 underlying + multiple-cause)
- **Key columns:** `year`, `state`, `cause_name`, `deaths`, `population`, `crude_rate_per_100k`
- **Caveat:** Source provides **weekly counts only — no age stratification** — so true age-adjusted rates cannot be derived. Column is named `crude_rate_per_100k` to be transparent. NYC and US national rows have null populations (no ACS state match).

### 37. CDC PLACES — county-level chronic disease prevalence
- **File:** `cdc_places_county.csv` — 229,298 rows × 22 cols (63 MB)
- **Years:** 2022, 2023
- **Source:** [PLACES: Local Data for Better Health, County Data, 2025 release](https://data.cdc.gov/resource/swc5-untb.csv?$limit=300000) — Socrata `swc5-untb`
- **Granularity:** 229,218 county rows + 80 state-summary rows in same file (`len(locationid)==2` isolates state)
- **What it gives:** 40 measures across 6 categories (Health Outcomes, Health Status, Disability, Prevention, Health Risk Behaviors, Health-Related Social Needs). Model-based small-area estimates — **do not re-aggregate naively.**

### 38. CDC BRFSS Prevalence — state-level chronic disease
- **File:** `brfss_state_prevalence.csv` — 64,290 rows × 27 cols (22 MB)
- **Years:** 2018–2024
- **Source:** [BRFSS Prevalence Data 2011–present](https://data.cdc.gov/resource/dttw-5yxu.csv?$where=year>=2018%20AND%20break_out='Overall'%20AND%20data_value_type='Crude%20Prevalence')
- **Granularity:** state × year × topic × question × response (long format), filtered to `break_out='Overall'` + `Crude Prevalence`
- **What it gives:** State-level prevalence % with CIs and sample sizes for 21 classes / 63 topics: Diabetes, Hypertension, Cholesterol, Obesity, Cancer Screening, Smoking, Mental Health, Asthma, COPD, Arthritis, Oral Health.

### 39. CDC VSRR — Provisional Drug Overdose Death Counts
- **File:** `cdc_drug_overdose.csv` — 82,530 rows × 12 cols (17 MB)
- **Years:** 2015 – Oct 2025 (provisional)
- **Source:** [VSRR Provisional Drug Overdose Death Counts](https://data.cdc.gov/resource/xkb8-kh2a.csv?$limit=200000) — Socrata `xkb8-kh2a`
- **Granularity:** state × year × month × indicator (rolling 12-month-ending counts)
- **What it gives:** 12 indicators including total overdose deaths, Cocaine (T40.5), Heroin (T40.1), Methadone (T40.3), Natural/semi-synthetic (T40.2), Synthetic excl. methadone = fentanyl (T40.4), Psychostimulants (T43.6). Has lag-adjusted `predicted_value`.

### 40. CDC Births / Natality
- **File:** `cdc_births.csv` — 502 rows × 6 cols (15 KB)
- **Source:** CDC NCHS Natality (state-aggregated)
- **Granularity:** state × year
- **Key columns:** `year`, `state`, `fertility_rate_per_1000`, `births`, `pct_preterm`, `pct_low_birthweight`
- **What it gives:** Compact state-level natality summary covering recent years.

### 41. CDC Maternal Mortality
- **File:** `cdc_maternal_mortality.csv` — 260 rows × 12 cols (33 KB)
- **Source:** CDC NCHS NVSS maternal mortality
- **Granularity:** state × period × measure
- **Key columns:** `state`, `period`, `period_start_year`, `period_end_year`, `measure`, `deaths`, `births`, `rate_per_100k_live_births`
- **What it gives:** Maternal death counts and rates per 100k live births by state, multi-year periods (rolling).

### 42. CDC HIV Surveillance
- **File:** `cdc_hiv.csv` — 832 rows × 24 cols (49 KB)
- **Source:** CDC NCHHSTP AtlasPlus / HIV Surveillance Report
- **Granularity:** state × year
- **Key columns:** `year`, `geo_id`, `state_abbr`, `state`, plus rates and case counts stratified by sex (`newdx_state_rate_per_100k`, `newdx_male_*`, `newdx_female_*`, etc.)
- **What it gives:** New HIV diagnoses (rate per 100k + case counts) by state and year, demographic stratifications.

### 43. CDC STI Surveillance
- **File:** `cdc_sti.csv` — 1,918 rows × 7 cols (109 KB)
- **Source:** CDC NCHHSTP STI surveillance (chlamydia, gonorrhea, syphilis, congenital syphilis)
- **Granularity:** year × disease × reporting area
- **Key columns:** `year`, `disease`, `reporting_area`, `cases`, `mmwr_week_observed`, `snapshot_year`, `source_dataset_id`
- **What it gives:** Reported case counts by jurisdiction × disease × week — supports both annual and weekly views.

### 44. CDC Childhood Lead Exposure (CBLPP)
- **File:** `cdc_lead_exposure.csv` — 198 rows × 17 cols (15 KB)
- **Source:** CDC Childhood Blood Lead Surveillance / CBLPP
- **Granularity:** state × year
- **Key columns:** `year`, `state`, `pop_under72mo`, `children_tested`, `n_bll_ge_3_5`, `pct_bll_ge_3_5`, `n_bll_ge_5`, `pct_bll_ge_5`, plus higher BLL thresholds
- **What it gives:** Number of children <72 months tested for blood lead level, counts and percentages above various thresholds (3.5 µg/dL reference value, 5, 10, 25, 45 µg/dL).

### 45. CDC Oral Health (NOHSS)
- **File:** `cdc_oral_health.csv` — 34,332 rows × 16 cols (6.1 MB)
- **Source:** CDC National Oral Health Surveillance System
- **Granularity:** state × year × topic × indicator
- **Key columns:** `topic`, `year`, `location_abbr`, `location_desc`, `location_id`, `indicator`, `indicator_id`, `data_value`
- **What it gives:** Adult dental visits, edentulism, water fluoridation %, sealant prevalence, tooth loss, caries — long format.

### 46. CDC NHANES — National Health & Nutrition Examination Survey
- **File:** `cdc_nhanes.csv` — 6,072 rows × 18 cols (1.5 MB)
- **Source:** CDC NCHS NHANES summary statistics (national-level estimates)
- **Granularity:** survey cycle × topic × indicator × demographic stratification
- **Key columns:** `source`, `survey_years`, `geographic_level`, `location`, `topic`, `indicator`, `value_type`, `value_unit`
- **What it gives:** Pre-aggregated NHANES estimates (no microdata) — biomarker prevalence, nutrition, body measurements, dental, hearing, vision, physical activity. National only.

### 47. CDC Social Vulnerability Index (SVI)
- **File:** `cdc_svi.csv` — 3,144 rows × 158 cols (2.3 MB)
- **Source:** CDC/ATSDR Social Vulnerability Index 2022
- **Granularity:** county-level (one row per US county)
- **Key columns:** `ST`, `STATE`, `ST_ABBR`, `STCNTY`, `COUNTY`, `FIPS`, `LOCATION`, `AREA_SQMI`, plus 4 theme scores + overall SVI percentile
- **What it gives:** Composite social vulnerability percentile and 4 thematic subscores (socioeconomic, household composition/disability, minority/language, housing/transport) plus 16 underlying indicators.

### 48. CDC WISQARS — Injury & Death Surveillance
- **File:** `cdc_wisqars.csv` — 840 rows × 69 cols (305 KB)
- **Source:** CDC Injury Center WISQARS (Web-based Injury Statistics Query and Reporting System)
- **Granularity:** quarter × cause of death × rate type
- **Key columns:** `Year and Quarter`, `Time Period`, `Cause of Death`, `Rate Type`, `Unit`, `Overall Rate`, plus stratifications by sex, age, race
- **What it gives:** Injury-related death rates (homicide, suicide, unintentional, undetermined, legal intervention) with full demographic stratifications.

### 49. CDC National Wastewater Surveillance System (NWSS)
- **File:** `cdc_wastewater.csv` — 27,761 rows × 9 cols (2.4 MB)
- **Source:** CDC NWSS — pathogen wastewater monitoring
- **Granularity:** state/territory × week × pathogen
- **Key columns:** `state_territory`, `week_end`, `pathogen_target`, `wval_pop_weighted_mean`, `wval_mean`, `wval_median`, `wval_max`, `n_sites_reporting`
- **What it gives:** Population-weighted wastewater concentrations for SARS-CoV-2, influenza, RSV, mpox by state and week.

### 50. CDC Vaccination Coverage (combined)
- **File:** `cdc_vaccination.csv` — 252,883 rows × 21 cols (43 MB)
- **Years:** 2015–16 → 2024–25 seasons (flu/child/teen); 2020-12 → 2023-05 daily (COVID)
- **Source:** Four data.cdc.gov Socrata datasets stacked by `vaccine_type` + `source_dataset` columns:
  - FluVaxView — `vh55-3he6` (113,852 rows)
  - ChildVaxView NIS-Child — `fhky-rtsk` (84,117)
  - TeenVaxView NIS-Teen — `ee48-w5t6` (16,426)
  - COVID-19 Vaccinations Jurisdiction — `unsk-b7fc` (38,488)
- **Granularity:** geography × year/season × dimension (age/race/dose) × vaccine type
- **What it gives:** Coverage estimates with 95% CI for flu (all ages), childhood NIS-Child (DTaP, MMR, Hib, HepB, polio, varicella, rotavirus, PCV), adolescent NIS-Teen (HPV, Tdap, MenACWY, MenB, varicella), and full COVID-19 program (administered, series complete, additional doses, age 65+ subgroups).

---

## Other Federal Health Agencies (51–58)

### 51. AHRQ MEPS — Medical Expenditure Panel Survey
- **File:** `ahrq_meps.csv` — 32,793 rows × 8 cols (6.0 MB)
- **Source:** AHRQ MEPS Insurance Component / Household Component summary tables; built by `scripts/build_meps_ic.py`
- **Granularity:** year × state × table × indicator
- **Key columns:** `year`, `state`, `table_no`, `indicator`, `value`, `std_error`, `unit`, `raw_value`
- **What it gives:** State-level employer-sponsored insurance estimates (premium, contribution, cost-sharing, take-up rate, % offered) and household-survey expenditure estimates.

### 52. NCI / CDC US Cancer Statistics
- **File:** `nci_cancer.csv` — 1,140,819 rows × 11 cols (107 MB), pipe-delimited (`sep="|"`) + dictionary in `uscs_data_dictionary.xlsx`
- **Years:** 1999–2023
- **Source:** [CDC USCS 1999–2022 ASCII bundle](https://www.cdc.gov/cancer/uscs/USCS-1999-2022-ASCII.zip), file `BYAREA.TXT`
- **Granularity:** state × year × cancer site (27 sites) × race (12 categories) × sex (3) × event type (Incidence / Mortality)
- **What it gives:** `AGE_ADJUSTED_RATE` (per 100k), `COUNT`, `POPULATION`, `AGE_ADJUSTED_CI_LOWER/UPPER`. Both incidence and mortality in one file.

### 53. NIH RePORTER — Research Funding
- **File:** `nih_research_funding.csv` — 7,243 rows × 6 cols (219 KB)
- **Years:** FY 2020–2024
- **Source:** [NIH RePORTER Projects API](https://api.reporter.nih.gov/v2/projects/search) — paginated 500/page across 52 states × 5 fiscal years; aggregated by `scripts/fetch_nih_funding.py`. Total: 398,171 grants → 7,243 aggregated rows.
- **Granularity:** fiscal_year × state × NIH institute (IC code/abbrev)
- **Key columns:** `fiscal_year`, `state`, `institute_code`, `institute_abbrev`, `award_amount_usd`, `project_count`
- **What it gives:** Per-state NIH research dollars by institute (NCI, NIA, NIAID, NHLBI, NIMH, NIDA, etc.) per fiscal year — clean, no offset-cap warnings.

### 54. NIMH — Mental Health Indicators
- **File:** `nimh_mental_health.csv` — 16,794 rows × 14 cols (2.7 MB)
- **Source:** NIMH / Household Pulse / NCHS Mental Health Stress Indicator Files
- **Granularity:** indicator × subgroup × state × time period
- **Key columns:** `Indicator`, `Group`, `State`, `Subgroup`, `Phase`, `Time Period`, `Time Period Label`, `Time Period Start Date`, plus value + CI columns
- **What it gives:** Anxiety/depression symptom prevalence, mental health treatment access, unmet need — pandemic-era and post-pandemic time series.

### 55. ONC / ASTP — Hospital Health IT Adoption
- **File:** `onc_ehr_adoption.csv` — 624 rows × 42 cols (77 KB)
- **Years:** 2008–2020 (12 distinct years; 2016 gap)
- **Source:** [ONC Non-federal Acute Care Hospital Health IT Adoption and Use](https://healthit.gov/data/datasets/non-federal-acute-care-hospital-health-it-adoption-and-use/) — open API endpoint `https://www.healthit.gov/data/open-api?source=aha.csv`. Underlying source: AHA IT Supplement.
- **Granularity:** 50 states + DC + US national × year (52 regions × 12 years)
- **Key columns:** `region`, `period`, `pct_hospitals_cehrt`, `pct_hospitals_cehrt_2015`, plus rural/small/CAH breakouts (`pct_rural_hospitals_basic_ehr_no_notes`, `pct_critical_access_hospitals_basic_ehr_no_notes`), interoperability (`pct_hospitals_send_receive_find_integrate`, `pct_hospitals_hie_participate`, `pct_hospitals_api`), patient engagement (VDT, secure messaging).
- **What it gives:** Hospital EHR adoption + interoperability time series, with hospital-type breakouts. Sparsity is expected — many measures only collected select years.

### 56. FDA Adverse Events (FAERS summary)
- **File:** `fda_adverse_events.csv` — 288 rows × 4 cols (8.7 KB)
- **Source:** FDA FAERS public reports (annual aggregate)
- **Granularity:** year × indicator × country scope
- **Key columns:** `year`, `country_scope`, `indicator`, `report_count`
- **What it gives:** Annual FAERS report counts (serious / non-serious / death / hospitalization) at the program level — high-level pharmacovigilance summary, not record-level.

### 57. SAMHSA FindTreatment.gov Locator — Facilities
- **File:** `samhsa_facilities.csv` — 87,549 rows × 19 cols (27 MB)
- **Snapshot:** Current
- **Source:** [FindTreatment.gov locator API](https://findtreatment.gov/locator/exportsAsJson/v2) — paginated state-by-state pull, deduplicated on (name, city, state, phone).
- **Granularity:** facility-level
- **What it gives:** Facility identity, lat/lon, type_of_care, service_setting, payment_accepted, treatment approaches, special programs, derived flags (`is_substance_use`, `is_mental_health`, `is_co_occurring`).
- **Caveat:** Counts are higher than N-SUMHSS — FindTreatment includes individual buprenorphine prescribers and OTPs.

### 58. SAMHSA NSDUH — National Survey on Drug Use and Health
- **File:** `samhsa_nsduh.csv` — 10,136 rows × 8 cols (977 KB)
- **Source:** SAMHSA NSDUH state-level summary tables; built by `scripts/parse_samhsa_nsduh.py`
- **Granularity:** year period × table × measure × state × group
- **Key columns:** `years`, `table_id`, `measure`, `state`, `group`, `estimate_pct`, `ci_lower_pct`, `ci_upper_pct`
- **What it gives:** Past-month/past-year substance use, mental illness prevalence, treatment receipt, overall and stratified — long format, multi-period.

---

## Workforce / Occupational (59–61)

### 59. BLS OES — Healthcare Wages by State
- **File:** `bls_healthcare_wages.csv` — 4,136 rows × 32 cols (800 KB)
- **Year:** May 2024 OEWS estimates
- **Source:** [BLS OES state file `oesm24st.zip`](https://www.bls.gov/oes/special-requests/oesm24st.zip), filtered to SOC codes starting `29-` (practitioners) or `31-` (support). **Note:** BLS rejects generic User-Agents; use UA with email contact.
- **Granularity:** state × healthcare occupation (90 SOC codes × 54 areas)
- **What it gives:** Employment counts (`TOT_EMP`, `JOBS_1000`, `LOC_QUOTIENT`), wage percentiles hourly + annual (`H_MEAN`, `H_PCT10/25/MEDIAN/75/90`, `A_MEAN`, `A_PCT10/25/MEDIAN/75/90`).
- **Overlap note:** Conceptually overlaps AHRF (#23) which also has `*_emplymt_24` and `*_medn_wage_24` from BLS — this file adds wage *percentiles* and finer SOC granularity.

### 60. GME Residency Programs
- **File:** `gme_residency.csv` — 275 rows × 6 cols (8.3 KB)
- **Source:** Teaching hospital + GME public summary (CMS / AAMC-derived state aggregates)
- **Granularity:** state × year
- **Key columns:** `year`, `state`, `teaching_hospitals`, `residents_fte_total`, `total_hospitals`, `total_beds`
- **What it gives:** Counts of teaching hospitals and resident FTEs per state — useful for physician training pipeline analysis.

### 61. OSHA Healthcare Injuries
- **File:** `osha_healthcare_injuries.csv` — 2,892 rows × 14 cols (277 KB)
- **Source:** OSHA / BLS SOII Survey of Occupational Injuries & Illnesses (healthcare NAICS)
- **Granularity:** year × state × NAICS industry code
- **Key columns:** `year`, `state`, `naics_code`, `naics_description`, `rate_total_per100_trc`, `rate_injury_per100_trc`, `rate_illness_per10k_trc`, `rate_total_per100_dart`
- **What it gives:** Recordable injury/illness rates per 100 FTE in healthcare industries (hospitals, nursing facilities, ambulatory care, social assistance).

---

## Census — Demographics & Income (62–64)

### 62. Census ACS 5-Year Demographics (state-level)
- **File:** `acs_demographics.csv` — 52 rows × 22 cols (8 KB)
- **Years:** 2019–2023 5-year estimates (`/acs/acs5/2023` endpoint)
- **Source:** [Census ACS 5-year API](https://api.census.gov/data/2023/acs/acs5?get=NAME,B01001_001E,B19013_001E,B15003_001E,B15003_022E,B15003_023E,B15003_024E,B15003_025E,B18101_*&for=state:*)
- **Granularity:** 50 states + DC + PR
- **What it gives:** Total population, median household income, educational attainment subcomponents, disability subcomponents — designed to be consumed via simple aggregations (compute `BACHELORS_PLUS_PCT`, `WITH_DISABILITY_PCT`).

### 63. Census SAHIE — Small Area Health Insurance Estimates
- **File:** `census_sahie.csv` — 4,998 rows × 13 cols (385 KB)
- **Years:** 2006–2023 (18 years)
- **Source:** [Census SAHIE timeseries API](https://api.census.gov/data/timeseries/healthins/sahie?get=NAME,PCTUI_PT,PCTIC_PT,NUI_PT,NIC_PT,NIPR_PT,IPRCAT,IPR_DESC&for=state:*&time=from+2006+to+2023)
- **Granularity:** 51 states × year × IPR bracket (6 categories)
- **What it gives:** % uninsured (`PCTUI_PT`), % insured (`PCTIC_PT`), uninsured/insured counts by income-to-poverty bracket — supports computing poverty distribution + insurance rates.

### 64. Census SAIPE — Small Area Income & Poverty Estimates
- **File:** `census_saipe.csv` — 67,059 rows × 9 cols (3.7 MB)
- **Years:** 2003–2023 (21 years)
- **Source:** [Census SAIPE timeseries API](https://api.census.gov/data/timeseries/poverty/saipe?get=NAME,SAEPOVRTALL_PT,SAEMHI_PT,SAEPOVRT0_17_PT,SAEPOVALL_PT)
- **Granularity:** county (3,159 unique) and state (51), `geo_lvl` distinguishes
- **What it gives:** `SAEPOVRTALL_PT` (poverty rate %), `SAEMHI_PT` (median HH income $), `SAEPOVRT0_17_PT` (child poverty rate), `SAEPOVALL_PT` (count in poverty).

---

## Social Determinants & Infrastructure (65–72)

### 65. EPA EJSCREEN — Environmental Justice Indicators
- **File:** `epa_ejscreen.csv` — 32,133 rows × 13 cols (6.6 MB)
- **Source:** EPA EJScreen (county-aggregated). EPA's `gaftp.epa.gov/EJScreen/` was 404 in 2025; built from Zenodo mirror via `scripts/aggregate_ejscreen.py` (block-group → county roll-up).
- **Granularity:** year × county FIPS
- **Key columns:** `year`, `county_fips`, `population`, `pm25`, `ozone`, `diesel_pm`, `traffic_proximity`, `lead_paint`, plus other environmental burden indicators
- **What it gives:** County-level environmental burden indicators (air quality, traffic, lead paint risk, hazardous waste proximity) aggregated from EPA's block-group source.

### 66. USDA Food Access Research Atlas
- **Files:** `usda_food_access.csv` — 72,531 rows × 147 cols (47 MB) + dictionary `usda_food_access_dictionary.csv`
- **Year:** 2019 (USDA's most recent published version)
- **Source:** [USDA ERS Food Access Research Atlas](https://ers.usda.gov/media/5627/food-access-research-atlas-data-download-2019.zip?v=77599)
- **Granularity:** census tract level
- **What it gives:** Tract identity, population, urban flag, poverty rate, median family income, multiple food-desert flags (`LILATracts_*` for Low-Income+Low-Access at varying distances), distance-to-store flags, vehicle access flag.

### 67. USDA WIC — Women, Infants, Children Program
- **File:** `usda_wic.csv` — 275 rows × 20 cols (43 KB)
- **Years:** FY 2021–2025
- **Source:** USDA FNS WIC Program Data Tables — 4 annual + 4 monthly state-level Excel files from `https://www.fns.usda.gov/pd/wic-program`
- **Granularity:** state × fiscal year (55 jurisdictions: 50 states + DC + AS/GU/PR/VI)
- **Key columns:** `state`, `jurisdiction_type`, `fiscal_year`; participation columns (`total_participation_avg_monthly`, `total_women_avg_monthly` with pregnant/postpartum/breastfeeding splits, `total_infants_avg_monthly` with feeding-mode splits, `children_avg_monthly`); cost columns (`food_cost_total_usd`, `rebates_received_total_usd`, `nsa_cost_total_usd`, `total_program_cost_usd`, `avg_monthly_benefit_per_person_usd`).
- **Sanity check:** National sums reproduce USDA published totals (~6.2–6.9M monthly participants, $4.7–7.7B/year). FY 2021 has cost/participation totals only; demographic breakouts available FY 2022+.

### 68. HUD Fair Market Rents — FY2026 (revised)
- **File:** `hud_fair_market_rents.csv` — 4,764 rows × 14 cols (550 KB)
- **Year:** FY2026 (uses 2023 ACS data)
- **Source:** [HUD FMR FY2026 (revised)](https://www.huduser.gov/portal/datasets/fmr/fmr2026/FY26_FMRs_revised.xlsx) — converted from XLSX (required patching malformed `docProps/core.xml` date format inside the zipped XLSX)
- **Granularity:** county / county-subdivision per HUD FMR area
- **What it gives:** State, HUD area code, county/town name, metro flag, population, **40th-percentile rent** for 0/1/2/3/4-bedroom units (`fmr_0`–`fmr_4`).

### 69. DOT Transportation Infrastructure
- **File:** `dot_transportation.csv` — 3,142 rows × 21 cols (372 KB)
- **Source:** US DOT BTS state and county transportation infrastructure data
- **Granularity:** county-level (one row per US county)
- **Key columns:** `County FIPS`, `County Name`, `State FIPS`, `State Name`, `Primary and Commercial Airports`, `Non-Commercial -Civil Public Use Airports`, `Number of Bridges`, plus other infrastructure counts
- **What it gives:** County-level counts of airports, public airfields, bridges, transit stations, highway miles — useful for healthcare access analysis (drive time, ambulance routing).

### 70. FCC Broadband Availability (county-level)
- **File:** `fcc_broadband.csv` — 3,234 rows × 39 cols (754 KB)
- **Release:** FCC BDC June 2024
- **Source:** FCC Broadband Data Collection nationwide county summary, accessed via Esri Living Atlas mirror (item `22ca3a8bb2ff46c1983fb45414157b08`) after FCC.gov direct downloads timed out. Script: `scripts/fetch_fcc_broadband.py`. Underlying counts are FCC-reported BSLs, not Esri-derived.
- **Granularity:** county-level (50 states + DC + PR/GU/VI/AS/MP)
- **Key columns:** `GEOID`, `CountyName`, `StateAbbr`, `TotalPop`, `TotalBSLs`, `ServedBSLs` (≥100/20 Mbps low-latency), `UnderservedBSLs` (25/3 to 100/20), `UnservedBSLs` (<25/3), per-tech splits (Copper / Cable / Fiber / LTFW / LBRTFW), `UniqueProviders` (with per-tech provider counts), 12-month change columns, derived `pct_served_100_20`, `pct_underserved_25_3_to_100_20`, `pct_unserved`, `pct_fiber_served`.
- **Sanity check:** Median county 89.6% served at 100/20 Mbps, 15 unique providers — aligns with FCC published figures.

### 71. AoA Aging Services (Older Americans Act)
- **File:** `aoa_aging_services.csv` — 610 rows × 667 cols (2.0 MB) + dictionary `aoa_aging_services_DICTIONARY.csv`
- **Source:** Administration for Community Living / Administration on Aging — National Aging Program Information System (NAPIS) state report
- **Granularity:** state × year
- **Key columns:** `Year`, `State`, `Geo_Abbrv`, plus 600+ NAPIS measures (AaaFullTime, AAA volunteer counts, community staff, services delivered, expenditures by funding stream)
- **What it gives:** State-level aging-services delivery metrics covering Title III nutrition, transportation, supportive services, family caregiver, evidence-based health promotion, elder rights protection.

### 72. RWJF County Health Rankings
- **File:** `rwj_county_health_rankings.csv` — 3,205 rows × 796 cols (13 MB)
- **Source:** Robert Wood Johnson Foundation / University of Wisconsin Population Health Institute — annual County Health Rankings
- **Granularity:** county-level (one row per US county per release year)
- **Key columns:** `State FIPS Code`, `County FIPS Code`, `5-digit FIPS Code`, `State Abbreviation`, `Name`, `Release Year`, `Premature Death raw value`, plus ~390 measures × {raw_value, CI_low, CI_high}
- **What it gives:** Composite county rankings for Health Outcomes (length + quality of life) and Health Factors (health behaviors, clinical care, social/economic, physical environment), plus all underlying indicators (uninsured rate, primary care provider ratio, smoking, obesity, food insecurity, broadband flag, severe housing problems, etc.).

---

## State-Specific (73)

### 73. California HCAI — Hospital Annual Utilization Report
- **File:** `ca_hcai.csv` — 226,902 rows × 49 cols (111 MB) — **California-only**
- **Years:** 2012–2017
- **Source:** [CHHS Open Data — Hospital Annual Utilization Report](https://data.chhs.ca.gov/dataset/1902083c-f16a-434d-b8ac-f7a573a305df/resource/78622c04-a158-4c95-8ea3-7660725e9526/download/2012_current_year_hosp_util_mr.csv) — original Windows-1252, converted to UTF-8 on disk
- **Granularity:** Long format — one row per (facility × year × measure)
- **What it gives:** Facility identity (OSHPD_ID, name, address, lat/lon, county), characteristics (TYPE_LIC, TYPE_CNTRL, trauma center, teaching hospital), admin geography (assembly / senate / congressional district, census tract, health service area), and reported measures encoded by `Measure/Variable` code with description and Amount/Response.

---

## Final Batch (74–81)

### 74. CDC NHSN Healthcare-Associated Infections (HAI) — state SIRs
- **File:** `cdc_hai.csv` — 330 rows × 12 cols (22 KB)
- **Year:** 2024
- **Source:** [CDC HAI Progress Report — 2024 Acute Care Hospitals XLSX](https://www.cdc.gov/healthcare-associated-infections/media/excel/2024-SIR-ACH.xlsx) (data.cdc.gov Socrata had no HAI SIR resource at fetch time)
- **Granularity:** state/territory × infection type (55 jurisdictions × 6 infections)
- **What it gives:** Standardized Infection Ratios with 95% CI, observed and predicted counts, hospital reporting counts, validation status. Infections covered: CLABSI, CAUTI, MRSA hospital-onset BSI, hospital-onset C. difficile, SSI following colon surgery, SSI following abdominal hysterectomy. SIR < 1.0 means observed < predicted (better than the national baseline).
- **Reproducibility:** `scripts/fetch_cdc_hai.py`

### 75. CMS Timely & Effective Care — State
- **File:** `cms_timely_care.csv` — 1,736 rows × 8 cols (355 KB)
- **Period:** 2024 (rolling-window measures, end dates Dec 2024–Mar 2025)
- **Source:** CMS Provider Data Catalog resource `apyc-v239` — direct CSV `https://data.cms.gov/provider-data/sites/default/files/resources/c4f74a440cc6ce4ed941fa3c9de2ab58_1770163654/Timely_and_Effective_Care-State.csv` (the `/api/1/datastore/query/` endpoint failed; metastore distribution URL worked)
- **Granularity:** 56 jurisdictions × 31 process measures
- **What it gives:** Process-of-care numeric scores (not better/same/worse buckets) for ED throughput (OP_18 median ED time, OP_22 left-without-being-seen), sepsis bundle compliance (SEP_1, severe-sepsis 3hr/6hr, septic-shock 3hr/6hr), healthcare personnel flu vaccination (IMM_3), head-CT-within-45-min for stroke (OP_23), safe use of opioids, colonoscopy follow-up (OP_29, OP_31).
- **Distinct from** the four existing `hospital_compare_*` files which carry hospital count distributions or HCAHPS top-box, not process-measure scores.

### 76. CDC NNDSS Notifiable Disease Surveillance
- **File:** `cdc_nndss.csv` — 430,925 rows × 15 cols (47.8 MB)
- **Years:** 2022–2024 (weekly NNDSS = 2024; Lyme aggregated = 2022–2023)
- **Source:** Two stacked Socrata datasets on data.cdc.gov: `x9gk-5huc` (NNDSS Weekly Data 2024, 425,880 rows) + `x5j9-wybp` (Lyme aggregated 2022–2023, 5,045 rows). Distinguished by `disease_table` column.
- **Granularity:** reporting area × MMWR week × disease
- **What it gives:** Weekly case counts for ~115 notifiable infectious diseases plus 52-week max and YTD cumulative comparisons. Diseases include tuberculosis, hepatitis A/B/C variants, salmonellosis (Typhi, Paratyphi, other), Lyme disease (with case-status / sex / age stratifications in the aggregated table), pertussis, mumps, measles, malaria, meningococcal disease, Legionellosis, arboviral diseases (West Nile, dengue, etc.), STEC, listeriosis, vibriosis, Q fever, anthrax, botulism.
- **Distinct from** `cdc_hiv.csv` (separate HIV surveillance system), `cdc_sti.csv` (chlamydia/gonorrhea/syphilis), `cdc_drug_overdose.csv`, and the mortality files — NNDSS measures *case incidence* of reportable infections.
- **Reproducibility:** `scripts/fetch_cdc_nndss.py`

### 77. BLS State Unemployment — Local Area Unemployment Statistics (LAUS)
- **File:** `bls_unemployment.csv` — 3,672 rows × 5 cols (140 KB)
- **Years:** 2020–2025 (Dec 2025 not yet published as of 2026-04; 51 nulls)
- **Source:** **Fallback to FRED** (BLS public API rejected the LAUS series IDs without registration). FRED endpoint pattern: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<STATE>URN` (e.g. `CAURN` = California unemployment rate, monthly, not seasonally adjusted). 51 series fetched (50 states + DC).
- **Granularity:** state × year × month
- **Key columns:** `state`, `year`, `month`, `unemployment_rate`, `source`
- **What it gives:** Monthly unemployment rate time series. Rate range 1.5–30.1% (Nevada April 2020 COVID-era peak validated against BLS published value).
- **Distinct from** `bls_healthcare_wages.csv` (May 2024 OEWS wage snapshot — no time dimension, no unemployment).
- **Reproducibility:** `scripts/fetch_bls_unemployment.py` (tries BLS API first, falls back to FRED)

### 78. HRSA Nurse Corps — Loan Repayment + Scholarship
- **File:** `hrsa_nurse_corps.csv` — 53 rows × 25 cols (10 KB)
- **Year:** FY 2024 (data as of 2024-09-30)
- **Source:** Combined three sources — [Nurse Corps Field Strength FY2024 XLSX](https://data.hrsa.gov/DataDownload/StaticDocuments/FY%202024%20Nurse%20Corps%20Field%20Strength.xlsx), [Scholar Pipeline FY2024 XLSX](https://data.hrsa.gov/DataDownload/StaticDocuments/FY%202024%20Nurse%20Corps%20Scholar%20Pipeline.xlsx), and Appendix C of the [FY2024 Report to Congress PDF](https://www.govinfo.gov/content/pkg/CMR-HE20_9000-00198829/pdf/CMR-HE20_9000-00198829.pdf) for facility-level LRP dollar amounts (aggregated to state).
- **Granularity:** state (50 states + DC + PR + VI = 53)
- **Key columns:** `state`, `fiscal_year`, `total_field_strength`, `nc_lrp_field_strength`, `nc_sp_field_strength`, `nc_lrp_dollars` (real, parsed from PDF), `nc_sp_dollars_estimated` (apportioned), `nc_total_dollars_estimated`, plus nurse-type breakdowns (RN, NP, NP-Psych, RNA, CNM, CNS, faculty), rural/non-rural, scholar-pipeline counts.
- **Validation:** Total LRP $51.85M, total SP $25.96M, total $77.81M, 1,753 LRP + 672 SP = 2,425 field strength — match the FY2024 Report to Congress.
- **Caveat:** SP dollars are an estimate apportioned by SP field-strength share (HRSA does not publish per-state SP $).

### 79. CDC Alzheimer's Disease & Healthy Aging
- **File:** `cdc_alzheimers.csv` — 69,859 rows × 30 cols (27.8 MB)
- **Years:** 2015–2022 (8 years)
- **Source:** data.cdc.gov Socrata `hfr9-rurv` — [Alzheimer's Disease and Healthy Aging Data](https://data.cdc.gov/Healthy-Aging/Alzheimer-s-Disease-and-Healthy-Aging-Data/hfr9-rurv). BRFSS-based, older-adult focused.
- **Granularity:** 59 locations (50 states + DC + territories + HHS regions + national) × topic × age stratification
- **Key columns:** `yearstart`/`yearend`, `locationabbr`/`locationdesc`, `class`, `topic`, `question`, `data_value` (%), CIs, `stratificationcategory1`/`stratification1` (age group), `stratificationcategory2`/`stratification2` (sex/race).
- **Topics:** Cognitive Decline (subjective cognitive decline, functional difficulties, need for assistance, talked to provider), Caregiving (provide care, expected caregiving, duration, intensity, care for someone with cognitive impairment), Mental Health for older adults (frequent mental distress, lifetime depression diagnosis).
- **Distinct from** `brfss_state_prevalence.csv` — the agent deliberately dropped the AD&HA "Screenings and Vaccines" class to avoid overlap; retained classes are caregiving + cognitive decline + older-adult mental health, which are not in the main BRFSS file.

### 80. SAMHSA N-MHSS — National Mental Health Services Survey
- **File:** `samhsa_nmhss.csv` — 54 rows × 65 cols (13 KB)
- **Year:** 2023 (reference date 2023-03-31)
- **Source:** **PUF microdata gated** (SAMHSA CDN returned 404 for all documented PUF zip URLs). Fallback: parsed the 2023 [N-SUMHSS State Profiles PDF](https://www.samhsa.gov/data/sites/default/files/reports/rpt53014/2023-nsumhss-state-profiles.pdf) (765 pages, 28 MB) — same survey, state-level aggregates.
- **Granularity:** 50 states + DC + PR + national + territories combined = 54 jurisdictions
- **Key columns:** Facility totals (`total_facilities`, `total_clients`, `response_rate_pct`), service settings (`facilities_24h_hospital_inpatient`, `facilities_24h_residential`, `facilities_less_than_24h_care`), **bed capacity** (`beds_hospital_inpatient`, `beds_residential`, `beds_total`, capacity columns), 11 facility-type counts (`ft_psychiatric_hospital`, `ft_cmhc`, `ft_ccbhc`, `ft_vamc`, etc.), 13 treatment approaches (`approach_cbt`, `approach_dbt`, `approach_ect`, `approach_ketamine`, `approach_emdr`, `approach_telehealth`, etc.), 14 supportive services, 8 dedicated programs, 5 payer mix counts.
- **Validation:** State sums match national totals (9,853 vs 9,856 facilities; 88,873 vs 88,893 beds — diff = U.S. Territories row reported separately).
- **Distinct from** `samhsa_facilities.csv` — that's the FindTreatment.gov locator (87,549 rows, includes individual buprenorphine prescribers, no bed counts). N-MHSS is a survey of formal mental health treatment facilities with bed capacity — different unit of observation.

### 81. CMS Skilled Nursing Facility Quality Reporting Program (SNF QRP)
- **File:** `cms_snf.csv` — 838,071 rows × 16 cols (175 MB)
- **Release:** March 2026 refresh (issued Oct 2025); reporting periods Oct 2022–Mar 2025 vary by measure
- **Source:** CMS Provider Data Catalog `fykj-qjee` — direct CSV `https://data.cms.gov/provider-data/sites/default/files/resources/22278e3bbf43d60484dc40838338b596_1773439551/Skilled_Nursing_Facility_Quality_Reporting_Program_Provider_Data_Mar2026.csv`
- **Granularity:** facility × measure (long format) — 14,703 unique facilities (CCN) × 57 distinct measure codes × 53 states/territories
- **Key columns:** `CMS Certification Number (CCN)`, `Provider Name`, `State`, `County/Parish`, `Measure Code`, `Score`, `Footnote`, `Start Date`, `End Date`, `LOCATION1`.
- **Distinct from `cms_nursing_home.csv`** — that file holds rolled-up 5-star ratings + structural inputs (beds, staffing HPRD, deficiencies). This file holds the **underlying QRP measure scores the 5-stars don't expose**, including:
  - **S_004 PPR-PD** — Risk-standardized 30-day post-discharge readmission
  - **S_005 DTC** — Discharge to community
  - **S_006 MSPB** — Medicare Spending Per Beneficiary ratio (NOT in 5-star file)
  - **S_007/S_013** — Functional outcome measures
  - **S_038/S_039 HAI** — Healthcare-associated infections requiring hospitalization
  - **S_040–S_045** — IMPACT Act assessment-completion / transfer-of-health-information measures
- Same facility universe (CCN joins cleanly to `cms_nursing_home.csv`); complementary content.

### 83. CDC/ATSDR Social Vulnerability Index 2022 — tract level
- **File:** `cdc_svi_tract.csv` — 84,120 rows × 158 cols (61 MB)
- **Year:** 2022 (latest available; SVI is on a biennial cadence — next release expected ~late 2026)
- **Source:** CDC/ATSDR Geospatial Research, Analysis & Services Program (GRASP). Portal: [SVI Data & Tools Download](https://svi.cdc.gov/dataDownloads/data-download.html). Direct CSV (constructed from the portal's `loadXML.js`): `https://svi.cdc.gov/Documents/Data/2022/csv/states/SVI_2022_US.csv` (the U.S.-database file — tracts ranked nationally, vs. state-database files that rank tracts only within their state).
- **Granularity:** U.S. census tract (one row per tract; 84,120 tracts across 50 states + DC; FIPS unique; 778 zero-population tracts carry -999 sentinel in ranking columns).
- **Schema highlights** (full dictionary in the [SVI 2022 Documentation PDF](https://svi.cdc.gov/map25/data/docs/SVI2022Documentation_ZCTA.pdf)):
  - **Identifiers:** `FIPS` (11-char tract GEOID), `ST` / `STATE` / `ST_ABBR`, `STCNTY`, `COUNTY`, `LOCATION`, `AREA_SQMI`.
  - **`E_*` (estimates)** of underlying ACS variables (e.g. `E_TOTPOP`, `E_POV150`, `E_UNEMP`).
  - **`EP_*` (percentages)** of those estimates.
  - **`EPL_*` (percentile rankings, 0-1)** per variable, higher = more vulnerable.
  - **`SPL_THEMES`** summed theme scores; **`RPL_THEME1`–`RPL_THEME4`** ranked percentile per theme.
  - **`RPL_THEMES`** overall vulnerability percentile rank (the headline metric, 0-1).
  - **`F_*`** per-variable flag (1 if variable ≥ 90th percentile); **`F_TOTAL`** composite count of flags per tract.
  - **Themes:** 1 = Socioeconomic Status, 2 = Household Characteristics, 3 = Racial & Ethnic Minority Status, 4 = Housing Type & Transportation.
- **What it gives:** Per-tract national-percentile rank of social vulnerability across 16 ACS-derived factors. Powers "who is most exposed if an outbreak hits" overlays for Outbreak Watch and the population-vulnerability axis for the future Workforce Atlas. Cross-cuts to provider-shortage and chronic-disease views.
- **Distinct from** `cdc_svi.csv` (#47, the **county-level** 3,144-row SVI rollup also from CDC/ATSDR 2022) — same source, more granular geography. Cross-cuts to `census_sahie.csv` (insurance), `census_saipe.csv` (income/poverty), `epa_ejscreen.csv` (environmental burden).
- **License:** Open public data; attribute CDC/ATSDR.
- **Refresh cadence:** Biennial (next release ~late 2026; tract universe will re-base on the next ACS 5-year window).
- **R2 path:** `cdc_svi_tract.parquet` (lakehouse-only routing).
- **Reproducibility:** `scripts/fetch_cdc_svi.py`

---

## Reproducibility scripts (in `scripts/`)

The following scripts handle non-trivial fetches/parsing where a one-line wget wasn't sufficient:

- `fetch_nih_funding.py` — paginated NIH RePORTER pull (52 states × 5 fiscal years), aggregates to state × institute
- `fetch_partd_prescribers.py` — chunked stream of 582 MB CMS Part D Prescribers raw file, aggregates to state × specialty with derived ratios
- `fetch_cdc_wonder_mortality.py` — paginated Socrata pulls for two NCHS weekly-deaths datasets covering 2018–2023; joins ACS population for crude rates
- `fetch_cdc_svi.py` — direct CSV pull of the 2022 SVI U.S.-database tract-level file (all 158 columns retained); validates row count + FIPS uniqueness + RPL_THEMES range
- `fetch_fcc_broadband.py` — pulls FCC BDC county summary from the Esri Living Atlas mirror (FCC.gov direct downloads were unreliable)
- `fetch_medicaid_drug.py` — CMS State Drug Utilization data, state-aggregated
- `aggregate_ejscreen.py` — rolls EJScreen block-group data up to county
- `build_meps_ic.py` — assembles AHRQ MEPS Insurance Component summary tables
- `parse_cms_chronic.py` — parses CMS Chronic Conditions Data Warehouse summary tables
- `parse_samhsa_nsduh.py` — extracts SAMHSA NSDUH state-level summary tables

---

## Loaders implemented in `data_loader.py`

- `fetch_part_d_data()` — Part D drug spending (#6)
- `fetch_part_b_data()` — Part B drug spending (#7)
- `load_geo_variation()` — Medicare Geographic Variation (#1)
- `load_ahrf()` — AHRF (#23)
- `load_hpsa()` — HPSA (#24/25/26 concatenated, filtered to `Designated`)

The remaining 68 datasets are read directly by analysis code as needed; no wrapper loaders required.
