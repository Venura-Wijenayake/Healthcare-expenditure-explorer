# Migration Playbook

Operational guide for the hybrid Postgres (Neon) + Cloudflare R2 data
layer. Authoritative routing logic lives in `routing.py`; this doc
paraphrases it and adds the budget + incident context that the code
can't carry.

## Routing policy

Copied from `routing.py:route_dataset`:

> Decision tree:
>   1. If the app reads categorical (non-numeric) columns directly,
>      we cannot melt the dataset into `observations` -> R2.
>   2. Else if `rows * numeric_columns < 100_000`, the long-format
>      representation fits comfortably in observations -> Postgres.
>   3. Else if `rows < 50_000` and the access pattern is point-lookup
>      heavy (filter by state/year), the indexed Postgres path wins
>      -> Postgres.
>   4. Otherwise default to R2 — analytical scans are cheaper as
>      columnar Parquet read by DuckDB.

Inputs:

| Field                                  | Source                                |
|----------------------------------------|---------------------------------------|
| `rows`                                 | `dataset_registry.row_count`          |
| `numeric_columns`                      | quick CSV head + dtype check          |
| `has_categorical_columns_used_by_app`  | manual list (see test_data_integrity) |
| `is_filter_heavy`                      | manual list (see test_data_integrity) |

Returns: `('postgres' | 'r2', reason)`.

## Decision record

**March 2026 — moved the hot tier from Supabase to Neon.** The routing
logic stayed identical; only the vendor changed. Reasons:

- **Scale-to-zero.** Idle compute costs nothing, so the L2A demo
  environments don't burn budget between sessions.
- **Instant branching.** OSS contributors can fork a real branch of
  the database in seconds, run their migration, and tear it down —
  no shared-staging contention.
- **Vanilla Postgres.** No platform-specific extensions or RPCs; we
  can lift-and-shift to any Postgres host if Neon's terms change.
  No platform lock-in.
- **No 7-day pause risk.** Supabase's free-tier projects pause after
  ~7 days of inactivity, which broke L2A demos that ran on a
  bi-weekly cadence. Neon's scale-to-zero suspends compute but keeps
  the project reachable on demand.

The migration scripts still carry the `migrate_to_supabase_r2.py` name
and the `SUPABASE_*` secret keys — renaming those is its own piece of
work. `routing.py` and the tier-1 sanity check are vendor-neutral.

## Decision record (May 2026): lakehouse-only

The polyglot Postgres + R2 architecture surfaced a data
integrity issue: the melt-to-observations logic silently
dropped measurement columns when source CSVs used
non-numeric placeholders for missing values. Affected
~36 datasets, was caught by Tier 2 of the integrity
test suite.

We chose to disable the postgres data tier entirely
rather than fix the melt logic, because:
- DuckDB-on-Parquet handles all current query patterns
  fast enough
- We don't perform cross-dataset SQL JOINs
- Preserving raw data is more important than indexed
  lookups for the open-source LSR vision
- Reduces architectural surface area (one path instead
  of two)

Postgres still hosts the metadata catalog
(dataset_registry, metric_registry) and remains
available for future write paths (user annotations,
derived analytics). The melt code path is preserved
in migrate_to_neon_r2.py for if/when a specific
dataset needs the postgres tier.

To re-enable postgres for a specific dataset later:
update routing.py to return ('postgres', ...) for that
dataset's metadata, fix any column-classification issues
in the melt logic, re-run migration.

## Steady-state disk budget

Neon free tier: **500 MB** project storage.

| Component                 | Estimated size                    |
|---------------------------|----------------------------------:|
| observations + 6 indexes  | ~200 bytes/row × N rows           |
| registries                | <5 MB                             |
| WAL (steady)              | 50–100 MB                         |
| system / catalog          | ~30 MB                            |
| **Baseline overhead**     | **~85 MB** (WAL + system + reg)   |

The 200 bytes/row figure is ~80 bytes heap + ~120 bytes spread across the
six btree indexes on `observations`. Under-estimating this is what caused
the original Supabase blow-out — see incident log. The migration script's
pre-flight (`scripts/migrate_to_neon_r2.py:predict_disk_usage`) uses the
same 200-byte figure so its prediction matches this table.

Worked example at N = 1.5M observation rows:
`1.5M × 200 = 300 MB` data + 85 MB baseline ≈ **385 MB** of 500 MB.
That leaves ~115 MB headroom — sounds OK until you remember VACUUM FULL
needs ~2x the table size in scratch space (see incident log), so the
realistic safety margin is much tighter.

## Operational budget rules

- **Max 50K rows per delete operation.** Larger work must be chunked.
  Big deletes generate WAL faster than autovacuum reclaims it.
- **Run plain `VACUUM` (not FULL) after >10K row deletes.** Plain VACUUM
  marks dead tuples reusable in place; FULL rewrites the whole table.
- **Never run multiple heavy ops in the same hour.** Sequence:
  delete → wait for autovacuum → manual VACUUM → only then next op.
- **Always check disk + WAL size before starting any heavy op.** The
  Supabase dashboard exposes both. If disk is above ~75% or WAL is
  past 100 MB, stop and let the system catch up.

## "Oh no" incident log

Things we hit in production that we didn't predict in advance. Each one
is a reason a rule above exists.

- **Dead-tuple bloat after large deletes.** Disk usage stayed high until
  VACUUM ran. We had assumed Postgres reclaimed eagerly — it doesn't.
  *Fix:* manual VACUUM after every >10K row delete.
- **WAL ballooning during deletes.** A single large transaction pushed
  WAL well past the 50 MB ballpark we'd budgeted. Briefly tipped the
  project over its disk ceiling.
  *Fix:* chunk deletes (≤50K rows per op), and never two heavy ops
  back-to-back.
- **VACUUM FULL needs ~2x table disk.** We ran it once on a near-full
  project and the project ran out of disk mid-operation. Recovery was
  painful.
  *Fix:* `VACUUM FULL` is now off-limits — codified in
  `scripts/demote_to_r2.py:vacuum_observations` and in
  `memory/feedback_supabase_vacuum.md`.
- **Original routing over-sent to Supabase.** The 10K-row threshold
  in `migrate_to_supabase_r2.py` was too generous; datasets like
  `cms_partd_prescribers`, `aoa_aging_services`, `cms_dialysis`,
  `cdc_svi`, `cms_aco`, and `fcc_broadband` were flagged for
  retroactive demotion to R2 once their long-format observation row
  counts blew past expectations.
  *Fix:* the new policy in `routing.py` gates on
  `rows * numeric_columns` (the actual size in `observations`) plus
  an explicit categorical-columns escape hatch.
