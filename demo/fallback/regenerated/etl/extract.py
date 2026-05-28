# Regenerated from spec alone — wbbaw_spec_v1.md
"""
wbbxtr.py — Extract step for the WBBAW ETL pipeline.

Reads from the WBB operational source database, applies exclusion rules,
joins to the decline_reason lookup, and writes a JSONL staging file.

Exclusion rules (spec §4.1, §5.4):
  1. Test accounts excluded:         c.is_test = FALSE
  2. Abandoned applications excluded: a.status <> 'ABANDONED'
  DEMO accounts (customer_type = 'DEMO') are NOT excluded in v1 (WBB-AW-019).

The decline_reason lookup is a LEFT JOIN — records with no matching
reason_code produce NULL decline_description / decline_category.
If a decline_reason_code is present but unresolvable, a warning is issued
and RC_WARN is returned (exit code 4). The load step still proceeds
(job_config.yaml: on_warning → load). (spec §4.1)

Timestamps are serialised to ISO-format strings before staging. (spec §4.1)

Exit codes:
  RC_OK   (0) — all records extracted without lookup warnings
  RC_WARN (4) — extraction succeeded but at least one unresolvable
                decline_reason_code was encountered
  RC_FATAL (12) — unrecoverable error (DB connection failure, etc.)
"""

import sys

from common import (
    RC_FATAL,
    RC_OK,
    RC_WARN,
    etl_mode,
    get_logger,
    run_date,
    source_connection,
    staging_path,
    write_staging,
    _json_default,
)

log = get_logger("wbbxtr")

# ---------------------------------------------------------------------------
# Extract queries
# ---------------------------------------------------------------------------

# INCREMENTAL: rows submitted on the run date only.
# Exclusion (BRD §2.3):
#   - is_test = FALSE   → exclude test accounts
#   - status <> 'ABANDONED' → exclude abandoned applications
# LEFT JOIN to decline_reason carries decline_description and decline_category.
EXTRACT_QUERY = """
SELECT
    a.application_id,
    a.customer_id,
    c.company_name,
    c.business_category,
    c.company_size,
    c.is_test,
    c.customer_type,
    a.submitted_dt,
    a.status,
    a.reviewed_dt,
    a.approved_dt,
    a.decline_reason_code,
    d.reason_description   AS decline_description,
    d.category             AS decline_category
FROM wbb.onboarding_application a
JOIN wbb.customer c
    ON c.customer_id = a.customer_id
LEFT JOIN wbb.decline_reason d
    ON d.reason_code = a.decline_reason_code
WHERE c.is_test = FALSE                         -- Exclusion: test accounts (BRD §2.3)
  AND a.status <> 'ABANDONED'                  -- Exclusion: abandoned applications (BRD §2.3)
  AND a.submitted_dt::date = %(run_date)s::date
"""

# FULL: all records since programme start (2025-10-01), no upper bound.
EXTRACT_QUERY_FULL = """
SELECT
    a.application_id,
    a.customer_id,
    c.company_name,
    c.business_category,
    c.company_size,
    c.is_test,
    c.customer_type,
    a.submitted_dt,
    a.status,
    a.reviewed_dt,
    a.approved_dt,
    a.decline_reason_code,
    d.reason_description   AS decline_description,
    d.category             AS decline_category
FROM wbb.onboarding_application a
JOIN wbb.customer c
    ON c.customer_id = a.customer_id
LEFT JOIN wbb.decline_reason d
    ON d.reason_code = a.decline_reason_code
WHERE c.is_test = FALSE                         -- Exclusion: test accounts (BRD §2.3)
  AND a.status <> 'ABANDONED'                  -- Exclusion: abandoned applications (BRD §2.3)
  AND a.submitted_dt >= '2025-10-01'
"""


# ---------------------------------------------------------------------------
# Main extract function
# ---------------------------------------------------------------------------

def extract() -> int:
    """
    Execute the extract query, serialise results to staging JSONL,
    and return an exit code.
    """
    mode      = etl_mode()
    date_str  = run_date()
    stage     = staging_path()

    log.info("Extract starting — mode=%s run_date=%s stage=%s", mode, date_str, stage)

    try:
        conn = source_connection()
    except Exception as exc:
        log.error("Failed to connect to source database: %s", exc)
        return RC_FATAL

    warn_count = 0
    records    = []

    try:
        with conn.cursor() as cur:
            if mode == "FULL":
                log.info("Running FULL extract (all records since 2025-10-01)")
                cur.execute(EXTRACT_QUERY_FULL)
            else:
                log.info("Running INCREMENTAL extract for %s", date_str)
                cur.execute(EXTRACT_QUERY, {"run_date": date_str})

            col_names = [desc[0] for desc in cur.description]

            for row in cur:
                rec = dict(zip(col_names, row))

                # Serialise datetimes to ISO strings before staging (spec §4.1)
                for field in ("submitted_dt", "reviewed_dt", "approved_dt"):
                    if rec.get(field) is not None:
                        rec[field] = rec[field].isoformat()

                # Warn if decline_reason_code is present but lookup returned nothing.
                # Indicates a pre-November-2025 code not in the reference table.
                if rec.get("decline_reason_code") and rec.get("decline_description") is None:
                    log.warning(
                        "Unresolvable decline_reason_code '%s' on application_id=%s — "
                        "code may pre-date the November 2025 reference table",
                        rec["decline_reason_code"],
                        rec["application_id"],
                    )
                    warn_count += 1

                records.append(rec)

    except Exception as exc:
        log.error("Extract query failed: %s", exc)
        conn.close()
        return RC_FATAL
    finally:
        conn.close()

    # Write staging file
    try:
        written = write_staging(records, stage)
        log.info("Wrote %d record(s) to staging file %s", written, stage)
    except Exception as exc:
        log.error("Failed to write staging file: %s", exc)
        return RC_FATAL

    if warn_count:
        log.warning(
            "Extract completed with %d unresolvable decline_reason_code warning(s) — "
            "returning RC_WARN (%d); load step will proceed",
            warn_count,
            RC_WARN,
        )
        return RC_WARN

    log.info("Extract completed successfully — RC_OK")
    return RC_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(extract())
