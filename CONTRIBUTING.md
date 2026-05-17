# Contributing to Lighthouse Open Health

Thanks for helping make federal health data usable. The single most
valuable contribution is **adding a dataset** — and because datasets are
rows in a registry rather than bespoke code, you do not need to be a
software engineer to contribute one.

## Contributor model

The project runs a three-tier model. Tiers are earned through merged
work, not applied for.

- **Contributor** — opens pull requests, follows these guidelines, and
  earns commits via merged work. Anyone starts here; your first merged
  dataset makes you one.
- **Reviewer** — reviews and approves Contributor PRs. Trusted domain
  experts and active contributors with a track record of sound,
  well-sourced submissions.
- **Maintainer** — merges PRs, manages releases, and sets project
  direction. Currently just Venura Wijenayake.

Sustained, high-quality contribution is the path from Contributor to
Reviewer. Open an issue if you'd like to take on a domain area.

## Adding a new dataset

This is the most common contribution type. **Datasets are database rows
in `dataset_registry`, not code** — the platform scales to 10,000+
datasets without code changes, so adding one is mostly sourcing,
documentation, and a small fetch script.

1. **Open a "New dataset proposal" issue first**
   (use the template). This gets feedback on fit, licensing, and access
   challenges *before* you write a fetch script — please don't skip it.
2. **Add a fetch script** at `scripts/fetch_<dataset_key>.py` that
   downloads the source and writes a clean CSV into `data/`.
3. **Register metadata** — add an entry to the `DATASET_METADATA` dict
   in `scripts/migrate_to_neon_r2.py` (`name`, `agency`, `category`).
4. **Document it** — add a row to `data/MANIFEST.md` recording the
   canonical source URL, vintage, granularity, schema, and any caveats
   (methodology breaks, suppressed cells, encoding quirks).
5. **Open the PR.** Automated validation runs: source-URL reachability
   (or a documented WAF workaround), `DATASET_METADATA` presence,
   `MANIFEST.md` presence, a PII/public-agency sanity check, and a lint
   of the fetch script.
6. **Review & merge** — a Reviewer approves; a Maintainer merges and
   runs the migration so the registry picks up the new row.

A dataset is only accepted if it is **federally disclosed and freely
redistributable**. No login-walled, licensed, or individually
identifiable data.

## Adding a new analytical view

Views live in `views/<lens_name>.py` with a `render()` entry point and
are imported into `app.py` as a tab. The three existing lens views are
the reference patterns — read them before starting:

- `views/ca_workforce_atlas.py` — geographic anchor case
- `views/accountability.py` — single-entity lookup
- `views/outbreak_watch.py` — time-aware rolling dashboard

Follow the **discovery-first** practice these views model: inspect the
data before designing panels, verify every number against the source,
and handle missing-county / null / pre-season / methodology-break edge
cases gracefully and *honestly* (disclose data vintage; never synthesize
beyond what the data states).

## Code style

- **Python 3.13**, type hints, and docstrings on public functions.
- **Use the existing helpers** — `data_loader.load_dataset()`,
  `_pg_loader`, `_r2_loader`. Do not read raw files directly or
  hand-roll DB connections.
- **Cache expensive aggregations** with `@st.cache_data`.
- **For large datasets, push aggregations down to DuckDB server-side** —
  do not materialize full multi-hundred-thousand-row DataFrames into
  pandas just to aggregate them.
- Match the surrounding code's idiom, comment density, and naming.

## Refresh schedule

Datasets are refreshed on a three-tier cadence (project policy):

- **Weekly** — wastewater, unemployment, and surveillance feeds.
- **Quarterly** — CMS / CDC / clinical data.
- **Annual** — census, NCI, and structural workforce data.

When proposing a dataset, state which tier it belongs to in the issue.

## Code of Conduct

Participation is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md). By contributing you agree to
uphold it.

## License

By contributing, you agree that your contributions are licensed under
the project's [MIT License](LICENSE).
