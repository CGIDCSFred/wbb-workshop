"""
WBBAW Common Utilities
======================

Shared helpers for the WBB Analytics Warehouse ETL pipeline.
Used by wbbxtr (extract) and wbbldr (load).

Source BRD:    WBB-BRD-AW-001 v1.1
Owner:         D. Osei, WBB Data Services
"""

import os
import sys
import json
import logging
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import execute_values, RealDictCursor


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def configure_logging(program_name: str) -> logging.Logger:
    logger = logging.getLogger(program_name)
    logger.setLevel(logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(lambda r: r.levelno < logging.ERROR)
    stdout_handler.setFormatter(
        logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(
        logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    )

    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)
    return logger


# ---------------------------------------------------------------------------
# Job configuration
# ---------------------------------------------------------------------------
@dataclass
class JobConfig:
    run_date: str       # YYYY-MM-DD
    mode: str           # INCREMENTAL / FULL
    params: dict        # Additional config from job_config.yaml

    @property
    def run_date_iso(self) -> str:
        return self.run_date


def read_job_config() -> JobConfig:
    run_date = os.environ.get('RUN_DATE')
    if not run_date:
        run_date = datetime.utcnow().strftime('%Y-%m-%d')

    mode = os.environ.get('ETL_MODE', 'INCREMENTAL')
    if mode not in ('INCREMENTAL', 'FULL'):
        raise ValueError(f'ETL_MODE must be INCREMENTAL or FULL, got {mode!r}')

    params = {
        k[len('ETL_PARAM_'):]: v
        for k, v in os.environ.items()
        if k.startswith('ETL_PARAM_')
    }

    return JobConfig(run_date=run_date, mode=mode, params=params)


# ---------------------------------------------------------------------------
# Database connections
# ---------------------------------------------------------------------------
@contextmanager
def source_connection():
    """Connect to wbb (the operational source). Read-only."""
    conn = psycopg2.connect(os.environ['WBB_SOURCE_DSN'])
    conn.set_session(readonly=True)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def target_connection():
    """Connect to wbbaw (the warehouse). Read-write."""
    conn = psycopg2.connect(os.environ['WBB_TARGET_DSN'])
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Staging file
# ---------------------------------------------------------------------------
def staging_path() -> str:
    path = os.environ.get('STAGE_PATH', '/tmp/wbbaw_stage.jsonl')
    return path


def write_staging_records(records, path: str) -> int:
    n = 0
    with open(path, 'w') as f:
        for r in records:
            f.write(json.dumps(r, default=str) + '\n')
            n += 1
    return n


def read_staging_records(path: str):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
# 0  Success
# 4  Success with warnings
# 8  Recoverable failure — retry likely to succeed
# 12 Unrecoverable failure — manual intervention required
RC_OK    = 0
RC_WARN  = 4
RC_RETRY = 8
RC_FATAL = 12
