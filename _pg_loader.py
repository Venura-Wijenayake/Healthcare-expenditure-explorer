"""Private: Postgres query path for the hybrid storage layer.

Imported only by data_loader. Nothing in app.py should touch this
directly — the leading underscore is a hint, not a hard barrier.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import psycopg2.extensions

from infra import get_postgres_conn

logger = logging.getLogger(__name__)


# Cast NUMERIC -> float at the cursor boundary so pandas dtype inference
# behaves the same as it did under the supabase-py path (which JSON-decoded
# numerics as float). Affects DECIMAL/NUMERIC OIDs only — INTEGER/BIGINT
# keep psycopg2's default Python `int`. Process-global, runs once on import.
psycopg2.extensions.register_type(psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values,
    "DEC2FLOAT",
    lambda value, _cur: float(value) if value is not None else None,
))


# Logical filter name -> physical column in `observations`. Used as an
# allow-list when assembling WHERE clauses; never accept arbitrary keys.
_OBS_FILTER_TO_COL: dict[str, str] = {
    "state": "state",
    "county": "county",
    "year": "year",
    "month": "month",
    "sex": "sex",
    "race": "race",
    "age_group": "age_group",
    "metric_name": "metric_name",
}


def lookup_storage(dataset_key: str) -> dict | None:
    """Read one dataset_registry row by key.

    Defensive synonym: if storage_location='supabase' (legacy from the
    Supabase->Neon cutover), log a warning and rewrite to 'postgres' in
    the returned dict so the dispatcher routes correctly.
    """
    try:
        conn = get_postgres_conn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Postgres connect failed for %s lookup: %s", dataset_key, exc)
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT dataset_key, storage_location, parquet_path, "
                "row_count, granularity FROM dataset_registry "
                "WHERE dataset_key = %s LIMIT 1",
                (dataset_key,),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("registry lookup failed for %s: %s", dataset_key, exc)
        return None
    finally:
        conn.close()

    if not row:
        return None
    out = dict(zip(cols, row))
    if out.get("storage_location") == "supabase":
        logger.warning(
            "dataset_registry.storage_location='supabase' for %s — "
            "treating as 'postgres' (legacy Supabase->Neon cutover)",
            dataset_key,
        )
        out["storage_location"] = "postgres"
    return out


def inventory_stats() -> dict | None:
    """Aggregate dataset_registry for the header banner.

    Returns {"n_datasets", "total_rows", "n_agencies"} or None if
    Postgres is unreachable (caller supplies a fallback). NULL
    row_count rows contribute 0 via COALESCE.
    """
    try:
        conn = get_postgres_conn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Postgres connect failed for inventory_stats: %s", exc)
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(row_count), 0), "
                "COUNT(DISTINCT agency) FROM dataset_registry"
            )
            n_datasets, total_rows, n_agencies = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.warning("inventory_stats query failed: %s", exc)
        return None
    finally:
        conn.close()
    return {
        "n_datasets": int(n_datasets),
        "total_rows": int(total_rows),
        "n_agencies": int(n_agencies),
    }


def query_observations_long(dataset_key: str, filters: dict[str, Any]) -> pd.DataFrame:
    """Pull observations rows for one dataset_key, optionally filtered.

    All values are bound via psycopg2 placeholders. Column names come
    from the _OBS_FILTER_TO_COL allow-list, never from the caller.
    """
    where = ["dataset_key = %s"]
    params: list[Any] = [dataset_key]
    for logical, value in filters.items():
        if value is None:
            continue
        col = _OBS_FILTER_TO_COL.get(logical)
        if not col:
            continue
        if isinstance(value, (list, tuple, set)):
            placeholders = ",".join(["%s"] * len(value))
            where.append(f"{col} IN ({placeholders})")
            params.extend(value)
        else:
            where.append(f"{col} = %s")
            params.append(value)

    sql = (
        "SELECT dataset_key, state, county, year, month, sex, race, "
        "age_group, metric_name, metric_value FROM observations "
        "WHERE " + " AND ".join(where)
    )
    conn = get_postgres_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=cols)


def pivot_to_wide(long_df: pd.DataFrame) -> pd.DataFrame:
    """Turn observations rows back into a wide DataFrame, dropping all-null cols."""
    if long_df.empty:
        return long_df
    keep_index = [
        c for c in ("state", "county", "year", "month", "sex", "race", "age_group")
        if c in long_df.columns and long_df[c].notna().any()
    ]
    if not keep_index:
        keep_index = ["dataset_key"] if "dataset_key" in long_df.columns else None
    wide = long_df.pivot_table(
        index=keep_index,
        columns="metric_name",
        values="metric_value",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    return wide


def update_row_count(dataset_key: str, n: int) -> None:
    """UPDATE dataset_registry.row_count for one key. Best-effort."""
    try:
        conn = get_postgres_conn()
    except Exception as exc:  # noqa: BLE001
        logger.debug("row_count update skipped (connect failed): %s", exc)
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dataset_registry SET row_count = %s WHERE dataset_key = %s",
                (int(n), dataset_key),
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("row_count update failed for %s: %s", dataset_key, exc)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()
