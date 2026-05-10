"""Shared infrastructure helpers for the Postgres (Neon) + R2 layer.

Single source of truth for backend connections. Both the runtime
loader (data_loader.py) and the migration scripts pull their
secrets and clients through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import boto3
import numpy as np
import pandas as pd
import psycopg2
from botocore.client import Config as BotoConfig
from psycopg2.extensions import AsIs, register_adapter

# Registered at module import. Both data_loader (via _pg_loader -> infra)
# and the migration script import infra, so adapters apply process-wide
# for any psycopg2 connection regardless of entry point.
register_adapter(np.int64,  lambda v: AsIs(int(v)))
register_adapter(np.int32,  lambda v: AsIs(int(v)))
register_adapter(np.int16,  lambda v: AsIs(int(v)))
register_adapter(np.float64, lambda v: AsIs(float(v)))
register_adapter(np.float32, lambda v: AsIs(float(v)))
register_adapter(np.bool_,   lambda v: AsIs(bool(v)))
register_adapter(type(pd.NA), lambda _v: AsIs("NULL"))

ROOT = Path(__file__).resolve().parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"


@dataclass
class Secrets:
    """All backend credentials. No supabase_* fields — the cutover to
    Neon retired the SUPABASE_URL / SUPABASE_SERVICE_KEY pair."""
    neon_database_url: str
    r2_endpoint_url: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_account_id: str


def load_secrets() -> Secrets:
    """Read .streamlit/secrets.toml. Raises if any required key is missing."""
    if not SECRETS_PATH.exists():
        raise FileNotFoundError(f"Missing secrets file: {SECRETS_PATH}")
    with SECRETS_PATH.open("rb") as f:
        cfg = tomllib.load(f)
    required = [
        "NEON_DATABASE_URL",
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_ACCOUNT_ID",
    ]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"Missing secrets in {SECRETS_PATH}: {missing}")
    return Secrets(
        neon_database_url=cfg["NEON_DATABASE_URL"],
        r2_endpoint_url=cfg["R2_ENDPOINT_URL"],
        r2_access_key_id=cfg["R2_ACCESS_KEY_ID"],
        r2_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
        r2_bucket_name=cfg["R2_BUCKET_NAME"],
        r2_account_id=cfg["R2_ACCOUNT_ID"],
    )


def get_postgres_conn(secrets: Secrets | None = None):
    """Return a fresh psycopg2 connection (autocommit=False).

    The caller is responsible for closing. No connection pool yet —
    the workload is small (per-process lru_cache fronts most reads,
    migrations are batch jobs).
    """
    if secrets is None:
        secrets = load_secrets()
    conn = psycopg2.connect(secrets.neon_database_url)
    conn.autocommit = False
    return conn


def make_r2(secrets: Secrets):
    """Return a boto3 S3 client bound to the R2 endpoint.

    Same logic as the previous migrate_to_supabase_r2.make_r2 — only
    the call site changed.
    """
    return boto3.client(
        "s3",
        endpoint_url=secrets.r2_endpoint_url,
        aws_access_key_id=secrets.r2_access_key_id,
        aws_secret_access_key=secrets.r2_secret_access_key,
        config=BotoConfig(signature_version="s3v4"),
    )
