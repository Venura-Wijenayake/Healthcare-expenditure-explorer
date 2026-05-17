# Lighthouse Open Health

> An open-source Living Systematic Review of U.S. healthcare data.

## What this is

Federally-disclosed U.S. healthcare data is vast and public — and almost
unusable in aggregate. Medicare spending sits on one CMS portal,
physician-workforce files on another, disease surveillance across a dozen
CDC systems, nursing-home enforcement records on Care Compare, False
Claims Act recoveries in DOJ press releases. Dozens of agencies, dozens
of formats, no unified lookup. Answering a single cross-cutting question
("where is clinician supply lowest relative to preventable
hospitalizations?") today means manually reconciling five sites.

Lighthouse Open Health makes that whole corpus queryable in one place.
It is built as a **Living Systematic Review**: every public datapoint is
recallable, cross-referenceable, and AI-assisted, with the **full raw
data preserved** — no pre-computed summaries standing between you and the
source numbers. Datasets are rows in a registry, not bespoke code, so the
platform scales to thousands of sources without rearchitecting.

It is for the people who need federal health data but shouldn't have to
become data engineers to use it: **medical and public-health students**
learning the landscape, **patients and families** checking a specific
facility, and **policy analysts and journalists** who need defensible,
source-attributed numbers fast.

Federal data only. Not for clinical use. Public-data attribution is
preserved on every panel.

## The three lenses

Beyond general dataset exploration, three opinionated analytical lenses
anchor the platform — each answering a concrete question end-to-end.

### 🦠 Outbreak Watch
A rolling situation report: what disease threats CDC is warning about
*right now*, cross-referenced against active national surveillance feeds
(NNDSS, FluView ILINet, ArboNET, FoodNet, NORS, wastewater). There is no
fixed anchor — the featured advisory **rotates with the latest CDC Health
Alert Network message** (currently a 2026 multi-country hantavirus
cluster). Every panel discloses its own data vintage; nothing is
synthesized beyond what the feeds report.

### 🩺 CA Workforce Atlas
Where in California does the next clinician matter most? It maps
county-level physician supply against AHRQ preventable-hospitalization
(PQI) outcomes, surfacing the structural-failure zone where low supply
and high avoidable hospitalization coincide. The anchor demonstration
case is **Glenn County** — a rural Northern California county that is a
structural outlier on nearly every preventable-hospitalization domain.

### 🏛️ Provider Accountability
The fragmented federal accountability record for a single nursing home —
citations, Scope/Severity, civil money penalties, payment denials, SNF
quality measures — unified into one lookup for any of ~15,000 U.S.
facilities. The anchor case is **Coral Rehabilitation and Nursing of
Austin** (CCN 455862, TX): a 1-star facility with 18 immediate-jeopardy
citations and six-figure federal fines in three years.

## Live demo

**[medicare-healthcare-explorer.streamlit.app](https://medicare-healthcare-explorer.streamlit.app)**

![Glenn County demo](docs/screenshots/glenn-county.png)

## Quick stats

**98 federal datasets · 17.7M rows · 27 agencies · 3 analytical lenses · MIT licensed**

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| UI | **Streamlit** + **Plotly** | Fast data-app iteration; interactive charts without a JS frontend |
| Analytical store | **Cloudflare R2** (Parquet lakehouse) read via **DuckDB** | Large datasets stay as columnar Parquet; aggregations push down server-side instead of materializing full DataFrames |
| Metadata registry | **Neon Postgres** | `dataset_registry` is the single source of truth — datasets are rows, not code |
| Data wrangling | **pandas** | Small/medium transforms and the legacy CSV fallback path |
| AI Analyst | **Groq → OpenAI (GPT-4o mini) → Gemini → Together AI** | RAG over dataset summaries with a hot-swappable provider chain that fails over on rate-limit/auth errors |

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app runs without credentials in a degraded mode (it falls back to
local CSVs where present), but **full functionality needs
`.streamlit/secrets.toml`**:

- **Data backend** — `NEON_DATABASE_URL` and the `R2_*` keys
  (endpoint, access key, secret, bucket, account id) to reach the
  registry and the Parquet lakehouse.
- **AI Analyst** — at least one of `GROQ_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `TOGETHER_API_KEY`.

See `.streamlit/secrets.toml.example` for the LLM-key shape. Without the
data backend the dashboard still renders from any CSVs under `data/`.

## Contributing

Contributions are welcome — the most common one is **adding a dataset**,
which is a registry row plus a fetch script, not a code change. See
**[CONTRIBUTING.md](CONTRIBUTING.md)** for the full workflow, code style,
and refresh policy. The project runs a three-tier model
(**Contributor → Reviewer → Maintainer**); CONTRIBUTING.md explains how
to move between tiers. Please also read
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Data sources & attribution

All data on this platform is **federally disclosed and freely
redistributable** — U.S. government works are not subject to domestic
copyright. When you cite a figure, **cite the originating source agency**
(e.g. "CMS Nursing Home Care Compare, Mar 2026 snapshot"), **not this
platform**. Lighthouse Open Health is an access and cross-referencing
layer; the data's authority is the agency that published it. Per-panel
source and vintage labels are preserved precisely so citations stay
honest.

## License

Released under the **MIT License** — see [LICENSE](LICENSE).

## About the project

Built by Venura Wijenayake at L2A — Venura Wijenayake (Technical
Director, Learn to Achieve), a California 501(c)(3) public-benefit
nonprofit. The project is open source and community-contributable;
source code and contribution guide live at
[github.com/Venura-Wijenayake/Healthcare-expenditure-explorer](https://github.com/Venura-Wijenayake/Healthcare-expenditure-explorer).
