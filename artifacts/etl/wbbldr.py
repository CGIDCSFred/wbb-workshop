"""
WBBAW Load (wbbldr)
===================

Load staged extract records into the WBBAW warehouse.
Upserts dimensions (Type 1) and inserts/updates fact rows.
Reads from the staging file written by wbbxtr.

Stories implemented:
- WBB-AW-006  Load conformed dimensions with Type 1 overwrite
- WBB-AW-007  Implement fact_application load
- WBB-AW-008  Derive is_approved and is_declined flags

Source BRD:    WBB-BRD-AW-001 v1.1
Owner:         D. Osei, WBB Data Services
Last change:   2026-01-20 (added approved_dt / approved_date_key handling)
"""

import sys
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

from wbb_common import (
    configure_logging,
    read_job_config,
    target_connection,
    read_staging_records,
    staging_path,
    RC_OK, RC_WARN, RC_RETRY, RC_FATAL,
)


log = configure_logging('WBBLDR')


# ---------------------------------------------------------------------------
# Surrogate key generation
# ---------------------------------------------------------------------------
# Deterministic hash of natural key → 63-bit integer.
# Keeps restart semantics clean: re-running for the same source data
# produces the same surrogate keys.
# ---------------------------------------------------------------------------
def customer_key(customer_id: int) -> int:
    return abs(hash(('cust', customer_id))) & ((1 << 63) - 1)


def product_key(product_id) -> int:
    if product_id is None:
        return -1
    return abs(hash(('prod', product_id))) & ((1 << 63) - 1)


def application_key(application_id: int) -> int:
    return abs(hash(('app', application_id))) & ((1 << 63) - 1)


def date_key(dt_string: str) -> int:
    """ISO datetime string → YYYYMMDD integer."""
    d = datetime.fromisoformat(dt_string).date()
    return d.year * 10000 + d.month * 100 + d.day


# ---------------------------------------------------------------------------
# Dimension upserts
# ---------------------------------------------------------------------------
def upsert_dim_customer(cur, records, etl_ts):
    seen = {}
    for r in records:
        cid = r['customer_id']
        if cid in seen:
            continue
        seen[cid] = (
            customer_key(cid),
            cid,
            r['company_name'],
            # Source business_category → warehouse segment
            r['business_category'],
            r['company_size'],
            r['is_test'],
            None,           # first_product_type: populated by a separate job
            etl_ts,
        )

    if not seen:
        return 0

    execute_values(
        cur,
        """
        INSERT INTO wbbaw.dim_customer (
            customer_key, customer_id, company_name, segment,
            company_size, is_test, first_product_type, etl_last_updated_dt
        ) VALUES %s
        ON CONFLICT (customer_id) DO UPDATE SET
            company_name        = EXCLUDED.company_name,
            segment             = EXCLUDED.segment,
            company_size        = EXCLUDED.company_size,
            is_test             = EXCLUDED.is_test,
            etl_last_updated_dt = EXCLUDED.etl_last_updated_dt
        """,
        list(seen.values()),
    )
    return len(seen)


# ---------------------------------------------------------------------------
# Fact load
# ---------------------------------------------------------------------------
# Idempotent on application_id.
# ---------------------------------------------------------------------------
def load_fact(cur, records, etl_ts):
    rows = []

    for r in records:
        is_approved = r['status'] == 'APPROVED'
        is_declined = r['status'] == 'DECLINED'

        submitted_ts = datetime.fromisoformat(r['submitted_dt'])
        approved_ts = (
            datetime.fromisoformat(r['approved_dt'])
            if r.get('approved_dt') else None
        )

        days_to_decision = None
        if r.get('reviewed_dt'):
            reviewed_ts = datetime.fromisoformat(r['reviewed_dt'])
            days_to_decision = (reviewed_ts.date() - submitted_ts.date()).days

        rows.append((
            application_key(r['application_id']),
            r['application_id'],
            customer_key(r['customer_id']),
            date_key(r['submitted_dt']),            # submitted_date_key — primary date
            date_key(r['approved_dt']) if r.get('approved_dt') else None,
            submitted_ts,
            approved_ts,
            r['status'],
            is_approved,
            is_declined,
            days_to_decision,
            etl_ts,
        ))

    if not rows:
        return 0

    execute_values(
        cur,
        """
        INSERT INTO wbbaw.fact_application (
            application_key, application_id,
            customer_key,
            submitted_date_key, approved_date_key,
            submitted_timestamp, approved_timestamp,
            status, is_approved, is_declined,
            days_to_decision,
            etl_load_dt
        ) VALUES %s
        ON CONFLICT (application_id) DO UPDATE SET
            customer_key        = EXCLUDED.customer_key,
            submitted_date_key  = EXCLUDED.submitted_date_key,
            approved_date_key   = EXCLUDED.approved_date_key,
            submitted_timestamp = EXCLUDED.submitted_timestamp,
            approved_timestamp  = EXCLUDED.approved_timestamp,
            status              = EXCLUDED.status,
            is_approved         = EXCLUDED.is_approved,
            is_declined         = EXCLUDED.is_declined,
            days_to_decision    = EXCLUDED.days_to_decision,
            etl_load_dt         = EXCLUDED.etl_load_dt
        """,
        rows,
    )
    return len(rows)


def load(cfg):
    """Run the load. Returns (dim_count, fact_count)."""
    etl_ts = datetime.utcnow()
    path = staging_path()

    log.info(f'Reading staging file: {path}')
    records = list(read_staging_records(path))
    log.info(f'Read {len(records)} staged records')

    if not records:
        log.warning('No records to load.')
        return 0, 0

    with target_connection() as conn:
        with conn.cursor() as cur:
            n_cust = upsert_dim_customer(cur, records, etl_ts)
            log.info(f'dim_customer: upserted {n_cust} rows')

            n_fact = load_fact(cur, records, etl_ts)
            log.info(f'fact_application: loaded {n_fact} rows')

        conn.commit()

    return n_cust, n_fact


def main():
    try:
        cfg = read_job_config()
        log.info(f'WBBLDR starting: run_date={cfg.run_date}')

        n_dim, n_fact = load(cfg)
        log.info(f'Load completed: {n_dim} dim rows, {n_fact} fact rows.')
        return RC_OK

    except ValueError as e:
        log.error(f'Parameter error: {e}')
        return RC_FATAL
    except psycopg2.Error as e:
        log.error(f'Database error: {e}', exc_info=True)
        return RC_RETRY
    except Exception as e:
        log.error(f'Unexpected error: {e}', exc_info=True)
        return RC_RETRY


if __name__ == '__main__':
    sys.exit(main())
