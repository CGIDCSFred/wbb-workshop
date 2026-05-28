"""
WBBAW Extract (wbbxtr)
======================

Nightly extract from wbb (operational) to the WBBAW staging file.
Reads new onboarding application records for the run date, joins to
customer, product, and decline reason reference data, applies exclusion
rules from BRD §2.3, and writes staged records for the load step.

Stories implemented:
- WBB-AW-005  Build nightly ETL extract
- WBB-AW-008  Derive is_approved and is_declined flags
- WBB-AW-011  Carry decline reason through to warehouse (partial —
              decline_reason lookup join is here; see wbbldr for load side)

Run modes:
- INCREMENTAL  Extract applications submitted on the run date
- FULL         Extract all applications from programme start (2025-10-01)

Source BRD:    WBB-BRD-AW-001 v1.1
Owner:         D. Osei, WBB Data Services
Last change:   2026-01-20 (added approved_dt carry-through after source
               schema change on 2026-01-08)
"""

import sys
from datetime import datetime

from wbb_common import (
    configure_logging,
    read_job_config,
    source_connection,
    write_staging_records,
    staging_path,
    RC_OK, RC_WARN, RC_RETRY, RC_FATAL,
)


log = configure_logging('WBBXTR')


# ---------------------------------------------------------------------------
# Extract query
# ---------------------------------------------------------------------------
# Joins the application record to the customer and decline reason context.
# The result row carries everything the load step needs.
#
# Note: business_category is read here under its source name. The warehouse
# renames this to segment at load time per dim_customer convention.
#
# Note: decline_reason is LEFT JOIN'd because only declined applications
# carry a reason code. Non-declined applications will have null
# decline_description in the staged record.
#
# Note: we intentionally do NOT filter out DEMO accounts here. DEMO
# accounts have is_test = FALSE by design (they generate realistic-looking
# data). The BRD §2.3 exclusion for test accounts is implemented via
# is_test = FALSE. DEMO account exclusion is tracked as a v2 backlog item
# (WBB-AW-019).
# ---------------------------------------------------------------------------
EXTRACT_QUERY = """
    SELECT
        a.application_id,
        a.customer_id,
        a.submitted_dt,
        a.status,
        a.reviewed_dt,
        a.approved_dt,
        a.decline_reason_code,

        c.company_name,
        c.business_category,
        c.company_size,
        c.is_test,
        c.customer_type,

        d.reason_description    AS decline_description,
        d.category              AS decline_category

    FROM wbb.onboarding_application a
    JOIN wbb.customer c
        ON c.customer_id = a.customer_id
    LEFT JOIN wbb.decline_reason d
        ON d.reason_code = a.decline_reason_code

    WHERE a.submitted_dt::date = %(run_date)s::date

      -- Exclusion: test accounts (BRD §2.3)
      AND c.is_test = FALSE

      -- Exclusion: abandoned applications (BRD §2.3)
      -- Customers who started but did not complete an application are
      -- excluded from all warehouse metrics.
      AND a.status <> 'ABANDONED'

    ORDER BY a.submitted_dt, a.application_id
"""

EXTRACT_QUERY_FULL = """
    SELECT
        a.application_id,
        a.customer_id,
        a.submitted_dt,
        a.status,
        a.reviewed_dt,
        a.approved_dt,
        a.decline_reason_code,

        c.company_name,
        c.business_category,
        c.company_size,
        c.is_test,
        c.customer_type,

        d.reason_description    AS decline_description,
        d.category              AS decline_category

    FROM wbb.onboarding_application a
    JOIN wbb.customer c
        ON c.customer_id = a.customer_id
    LEFT JOIN wbb.decline_reason d
        ON d.reason_code = a.decline_reason_code

    WHERE a.submitted_dt >= '2025-10-01'
      AND c.is_test = FALSE
      AND a.status <> 'ABANDONED'

    ORDER BY a.submitted_dt, a.application_id
"""


def extract(cfg):
    """Run the extract and return (record_count, warning_count)."""
    warnings = 0
    records = []

    if cfg.mode == 'FULL':
        log.info('FULL mode — extracting all applications from programme start')
        query = EXTRACT_QUERY_FULL
        params = {}
    else:
        log.info(f'INCREMENTAL mode — extracting applications for {cfg.run_date_iso}')
        query = EXTRACT_QUERY
        params = {'run_date': cfg.run_date_iso}

    with source_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            colnames = [d.name for d in cur.description]
            for row in cur:
                rec = dict(zip(colnames, row))

                for k, v in rec.items():
                    if isinstance(v, datetime):
                        rec[k] = v.isoformat()

                # Warning: decline_reason_code present but not in lookup
                if rec['decline_reason_code'] and rec['decline_description'] is None:
                    warnings += 1
                    if warnings <= 10:
                        log.warning(
                            f'application_id={rec["application_id"]} '
                            f'decline_reason_code={rec["decline_reason_code"]} '
                            f'not in decline_reason lookup'
                        )

                records.append(rec)

    path = staging_path()
    n = write_staging_records(records, path)
    log.info(f'Wrote {n} records to staging: {path}')
    if warnings > 0:
        log.info(f'Total decline_reason lookup warnings: {warnings}')

    return n, warnings


def main():
    try:
        cfg = read_job_config()
        log.info(f'WBBXTR starting: run_date={cfg.run_date} mode={cfg.mode}')

        count, warnings = extract(cfg)

        if count == 0:
            log.warning('Extract produced 0 records. Load step will skip.')
            return RC_WARN

        if warnings > 0:
            log.info(f'Extract completed with {warnings} lookup warnings.')
            return RC_WARN

        log.info('Extract completed successfully.')
        return RC_OK

    except ValueError as e:
        log.error(f'Parameter error: {e}')
        return RC_FATAL
    except Exception as e:
        log.error(f'Unexpected error: {e}', exc_info=True)
        return RC_RETRY


if __name__ == '__main__':
    sys.exit(main())
