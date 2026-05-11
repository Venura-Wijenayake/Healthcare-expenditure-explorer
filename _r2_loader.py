"""Private: DuckDB / R2 query path for the hybrid storage layer.

Imported only by data_loader. Nothing in app.py should touch this
directly — the leading underscore is a hint, not a hard barrier.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

import pandas as pd

from infra import Secrets, load_secrets

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_duckdb_conn = None
_secrets_cache: Secrets | None = None
_init_failed = False


# Logical filter name -> candidate parquet column names. Pre-melt CSVs
# don't have a stable convention; this list covers the common spellings.
_FILTER_COLUMNS: dict[str, list[str]] = {
    "state": ["state", "State", "STATE", "state_name", "state_abbr",
              "locationabbr", "practice_state"],
    "year":  ["year", "Year", "YEAR"],
    "county": ["county", "County", "COUNTY", "county_name"],
    "npi":   ["npi", "NPI"],
    "taxonomy_code": ["taxonomy_code"],
}


def _secrets() -> Secrets | None:
    """Lazy secrets load. Returns None on failure so callers fall back to CSV."""
    global _secrets_cache, _init_failed
    if _secrets_cache is not None:
        return _secrets_cache
    if _init_failed:
        return None
    try:
        _secrets_cache = load_secrets()
    except Exception as exc:  # noqa: BLE001
        logger.warning("R2/secrets unavailable: %s — using CSV fallback", exc)
        _init_failed = True
        return None
    return _secrets_cache


def get_duckdb():
    """Singleton DuckDB connection with httpfs+R2 secret loaded.

    Returns None if secrets are missing or DuckDB init fails — callers
    are expected to handle that as a CSV-fallback signal.
    """
    global _duckdb_conn
    if _duckdb_conn is not None:
        return _duckdb_conn
    secrets = _secrets()
    if secrets is None:
        return None
    with _lock:
        if _duckdb_conn is not None:
            return _duckdb_conn
        try:
            import duckdb
            con = duckdb.connect(database=":memory:")
            con.execute("INSTALL httpfs; LOAD httpfs;")
            con.execute(
                """
                CREATE OR REPLACE SECRET r2_secret (
                    TYPE R2,
                    KEY_ID ?,
                    SECRET ?,
                    ACCOUNT_ID ?
                )
                """,
                [
                    secrets.r2_access_key_id,
                    secrets.r2_secret_access_key,
                    secrets.r2_account_id,
                ],
            )
            _duckdb_conn = con
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDB/R2 init failed: %s — using CSV fallback", exc)
            return None
    return _duckdb_conn


def r2_bucket() -> str | None:
    s = _secrets()
    return s.r2_bucket_name if s else None


def _resolve_filter_column(con, parquet_uri: str, logical: str) -> str | None:
    """Pick the parquet column that matches a logical filter name."""
    candidates = _FILTER_COLUMNS.get(logical, [logical])
    cols = con.execute(
        "DESCRIBE SELECT * FROM read_parquet(?) LIMIT 0", [parquet_uri]
    ).fetchall()
    available = {row[0] for row in cols}
    for c in candidates:
        if c in available:
            return c
    return None


def query_r2(parquet_path: str, filters: dict[str, Any]) -> pd.DataFrame:
    """Read a Parquet file from R2 with optional filter pushdown."""
    con = get_duckdb()
    bucket = r2_bucket()
    if con is None or not bucket:
        raise RuntimeError("R2 / DuckDB not configured")
    uri = f"r2://{bucket}/{parquet_path}"

    where_parts: list[str] = []
    params: list[Any] = [uri]
    for logical, value in filters.items():
        if value is None:
            continue
        col = _resolve_filter_column(con, uri, logical)
        if not col:
            continue
        if isinstance(value, (list, tuple, set)):
            placeholders = ",".join("?" * len(value))
            # `col` comes from the controlled _FILTER_COLUMNS allow-list — not user input.
            where_parts.append(f'"{col}" IN ({placeholders})')
            params.extend(value)
        else:
            where_parts.append(f'"{col}" = ?')
            params.append(value)

    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = "SELECT * FROM read_parquet(?)" + where_clause
    return con.execute(sql, params).fetch_df()


def refresh_row_count(
    dataset_key: str,
    parquet_path: str,
    pg_update_fn: Callable[[str, int], None],
) -> None:
    """Best-effort UPDATE of dataset_registry.row_count from the parquet metadata.

    Inverts the dependency so this module never imports psycopg2 — the
    Postgres-side update is passed in as a callable.
    """
    con = get_duckdb()
    bucket = r2_bucket()
    if not (con and bucket):
        return
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [f"r2://{bucket}/{parquet_path}"],
        ).fetchone()[0]
        pg_update_fn(dataset_key, int(n))
    except Exception as exc:  # noqa: BLE001
        logger.debug("row_count refresh skipped for %s: %s", dataset_key, exc)
