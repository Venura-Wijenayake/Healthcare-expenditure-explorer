---
name: New dataset proposal
about: Propose adding a federally-disclosed dataset to the platform
title: "[DATASET] "
labels: new-dataset
---

**Dataset name**
The canonical name from the source agency.

**Source agency**
e.g. CMS, CDC, HRSA, BLS, AHRQ, FDA, SAMHSA, DOJ, OIG, Census.

**Canonical landing page URL**
The agency page that documents the dataset (not the file download link).

**Granularity**
State / county / facility / individual / national / other.

**Vintage and refresh cadence**
- Most recent published vintage:
- How often the agency updates it (weekly / quarterly / annual / ad-hoc):

**Why this dataset matters**
What question does it help answer? Which of the three lenses (Outbreak Watch /
CA Workforce Atlas / Provider Accountability) does it strengthen, or does it
support a new lens entirely?

**Anticipated access challenges**
- Is the file behind a login wall? (yes/no)
- Is the agency known to WAF-block datacenter egress? (yes/no/unknown — AAMC
  and HRSA do; CDC, CMS, BLS, DOJ do not)
- Are there licensing or PII restrictions to verify?

**Volunteering to write the fetch script?**
- [ ] Yes, I will submit a PR adding scripts/fetch_<dataset_key>.py
- [ ] No, just proposing — needs a contributor to pick up

**Additional context**
Anything else.
