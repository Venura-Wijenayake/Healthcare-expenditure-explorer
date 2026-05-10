"""Storage routing policy for the hybrid Postgres + R2 data layer.

Vendor-neutral: the hot tier is plain Postgres (currently hosted on
Neon — see docs/MIGRATION_PLAYBOOK.md). Authoritative for both the
migration scripts and the policy-compliance tier of
scripts/test_data_integrity.py. Update here, run the tests, fix
mismatches in the registry — never the other way around.
"""

from __future__ import annotations


def route_dataset(metadata: dict) -> tuple[str, str]:
    """All datasets route to R2 (lakehouse-only).

    The postgres path's melt-to-observations logic
    was found to drop measurement columns when CSVs use
    non-numeric placeholders ('#', '-', '*', etc.) for
    missing values. Pandas reads such columns as object
    dtype, the migration's column classifier marks them
    non-numeric, and they're dropped during column
    cleaning — silent data loss.

    Until that's fixed, all datasets store raw in R2
    where data is preserved byte-for-byte in Parquet.
    DuckDB filter pushdown handles state/year lookups
    fast enough that we don't lose meaningful
    performance.

    Original decision tree retained below as comments
    for when the postgres path is repaired.

    Args:
        metadata: dict with keys
            rows                                     (int)
            numeric_columns                          (int)
            has_categorical_columns_used_by_app      (bool)
            is_filter_heavy                          (bool)

    Returns:
        A 2-tuple of ('postgres' | 'r2', short reason string).
    """
    return ("r2", "lakehouse-only architecture (postgres path disabled)")

    # Original logic, currently disabled:
    # Decision tree:
    #   1. If numeric_columns == 0, there's nothing to unpivot into the
    #      long-format observations schema -> R2.
    #   2. Else if the app reads categorical (non-numeric) columns directly,
    #      we cannot melt the dataset into ``observations`` -> R2.
    #   3. Else if rows * numeric_columns < 100_000, the long-format
    #      representation fits comfortably in observations -> Postgres.
    #   4. Else if rows < 50_000 and the access pattern is point-lookup
    #      heavy (filter by state/year), the indexed Postgres path wins
    #      -> Postgres.
    #   5. Otherwise default to R2 — analytical scans are cheaper as
    #      columnar Parquet read by DuckDB.
    #
    # rows = metadata["rows"]
    # numeric_columns = metadata["numeric_columns"]
    # has_categorical = metadata["has_categorical_columns_used_by_app"]
    # is_filter_heavy = metadata["is_filter_heavy"]
    #
    # if numeric_columns == 0:
    #     return ("r2", "no numeric columns to unpivot")
    # if has_categorical:
    #     return ("r2", "preserves categorical columns")
    # if rows * numeric_columns < 100_000:
    #     return ("postgres", "small enough for observations table")
    # if rows < 50_000 and is_filter_heavy:
    #     return ("postgres", "point lookups via state/year")
    # return ("r2", "analytical scans favored")
