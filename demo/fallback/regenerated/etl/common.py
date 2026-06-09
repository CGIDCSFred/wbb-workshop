# Regenerated from spec alone — wbbaw_spec_v1.md
"""
wbb_common.py — Shared utilities for the WBBAW ETL pipeline.

Provides:
  - Logging setup
  - Source and target DB connections (from WBB_SOURCE_DSN / WBB_TARGET_DSN)
  - Staging file read/write (newline-delimited JSON / JSONL)
  - Job config from environment variables
  - Exit code constants

Spec references: wbb_common.py sections throughout spec §2, §3, §5.8, §5.9.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Generator, Iterator

import psycopg2

# ---------------------------------------------------------------------------
# Exit codes  (spec §5.9)
# ---------------------------------------------------------------------------
RC_OK    = 0    # success
RC_WARN  = 4    # success with warnings (job continues downstream)
RC_RETRY = 8    # recoverable failure; retry likely to succeed
RC_FATAL = 12   # unrecoverable failure; manual intervention required

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)

def get_logger(name: str) -> logging.Logger:
    """Return a named logger at the configured level."""
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Database connections  (spec §2, §3, §5.8)
# ---------------------------------------------------------------------------

def source_connection() -> psycopg2.extensions.connection:
    """
    Open a read-only connection to the WBB operational source database.
    Connection string injected via WBB_SOURCE_DSN (secrets manager).
    """
    dsn = os.environ.get("WBB_SOURCE_DSN")
    if not dsn:
        raise EnvironmentError("WBB_SOURCE_DSN environment variable is not set")
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=False)
    return conn


def target_connection() -> psycopg2.extensions.connection:
    """
    Open a read-write connection to the WBBAW warehouse target database.
    Connection string injected via WBB_TARGET_DSN (secrets manager).
    """
    dsn = os.environ.get("WBB_TARGET_DSN")
    if not dsn:
        raise EnvironmentError("WBB_TARGET_DSN environment variable is not set")
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Staging file  (spec §1, §5.8)
# Default path: /tmp/wbbaw_stage.jsonl; override via STAGE_PATH env var.
# Format: newline-delimited JSON (one JSON object per line).
# ---------------------------------------------------------------------------

def staging_path() -> str:
    """Return the configured staging file path."""
    return os.environ.get("STAGE_PATH", "/tmp/wbbaw_stage.jsonl")


def write_staging(records: "list[dict[str, Any]]", path: "Optional[str]" = None) -> int:
    """
    Write a list of record dicts to the staging JSONL file.
    Each record is serialised as a single JSON line.
    Returns the number of records written.
    """
    dest = path or staging_path()
    with open(dest, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=_json_default) + "\n")
    return len(records)


def read_staging(path: "Optional[str]" = None) -> "Generator[dict[str, Any], None, None]":
    """
    Yield record dicts from the staging JSONL file one line at a time.
    Empty lines are skipped.
    """
    src = path or staging_path()
    with open(src, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _json_default(obj: Any) -> str:
    """Serialise datetime objects to ISO-format strings (spec §4.1)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


# ---------------------------------------------------------------------------
# Job configuration helpers  (spec §5.4, §5.5, §5.8)
# ---------------------------------------------------------------------------

def etl_mode() -> str:
    """
    Return ETL_MODE: 'INCREMENTAL' (default) or 'FULL'.
    INCREMENTAL: extract for today's UTC date only.
    FULL: extract all records since programme start (2025-10-01).
    """
    return os.environ.get("ETL_MODE", "INCREMENTAL").upper()


def run_date() -> str:
    """
    Return the run date as an ISO date string (YYYY-MM-DD).
    Defaults to today's UTC date; overrideable via RUN_DATE env var.
    """
    override = os.environ.get("RUN_DATE")
    if override:
        return override
    return datetime.now(timezone.utc).date().isoformat()


def commit_interval() -> int:
    """
    Return COMMIT_INTERVAL (default 5000).
    NOTE: this parameter is present in job_config.yaml but is not used by
    the current load implementation, which issues a single commit after the
    full batch. Exposed here for completeness. (spec §5.5, Q5)
    """
    return int(os.environ.get("COMMIT_INTERVAL", "5000"))


def error_threshold() -> int:
    """
    Return ERROR_THRESHOLD (default 50).
    NOTE: not referenced in the current load code. (spec §5.5, Q6)
    """
    return int(os.environ.get("ERROR_THRESHOLD", "50"))
