# Regenerated from spec alone — wbbaw_spec_v1.md
"""
wbbldr.py — Load step for the WBBAW ETL pipeline.

Reads the staging JSONL file produced by wbbxtr, then:
  1. Upserts wbbaw.dim_customer (Type 1 — overwrite on conflict).
  2. Loads wbbaw.fact_application (upsert on application_id).

Key behaviours (spec §4.2–§4.4):
  - Surrogate keys are 63-bit integers: abs(hash((prefix, natural_key))) & ((1<<63)-1)
  - dim_customer.segment maps from source business_category
  - dim_customer.first_product_type is set to NULL (populated by a separate job)
  - fact_application.submitted_date_key is the primary date (as-built; see D1)
  - fact_application.approved_date_key is populated where approved_dt is present
  - is_approved = True iff status == 'APPROVED'
  - is_declined = True iff status == 'DECLINED'
  - days_to_decision = calendar days between reviewed_dt and submitted_dt;
    NULL if reviewed_dt is absent

IMPORTANT — decline_description is present in each staged record (placed there
by wbbxtr's LEFT JOIN to decline_reason), but it is NOT written to any
warehouse table. fact_application has no decline_description column.
This implements the as-built behaviour documented in spec Discrepancy D3.
Do not add a decline_description column or persist the field.

dim_product is NOT upserted by this step (spec §4.2, §3, Q1, Q2).

A single commit is issued after all dimension and fact rows are processed
(spec §5.5, Q5). COMMIT_INTERVAL and ERROR_THRESHOLD env vars are read but
not acted on, matching the as-built behaviour.

Exit codes:
  RC_OK    (0)  — load completed without error
  RC_FATAL (12) — unrecoverable error
"""

import sys
from datetime import datetime, date

from common import (
    RC_FATAL,
    RC_OK,
    commit_interval,
    error_threshold,
    get_logger,
    read_staging,
    staging_path,
    target_connection,
)

log = get_logger("wbbldr")

_MASK63 = (1 << 63) - 1


# ---------------------------------------------------------------------------
# Surrogate key generation  (spec §4.4)
# All keys use Python's built-in hash() on a (prefix, natural_key) tuple.
# Deterministic for integer inputs (hash randomisation affects strings only).
# ---------------------------------------------------------------------------

def customer_key(customer_id: int) -> int:
    """63-bit surrogate key for a customer."""
    return abs(hash(("cust", customer_id))) & _MASK63


def product_key(product_id: int | None) -> int:
    """63-bit surrogate key for a product; returns -1 for NULL product_id."""
    if product_id is None:
        return -1
    return abs(hash(("prod", product_id))) & _MASK63


def application_key(application_id: int) -> int:
    """63-bit surrogate key for an application."""
    return abs(hash(("app", application_id))) & _MASK63


# ---------------------------------------------------------------------------
# Date key helper  (spec §4.3)
# ---------------------------------------------------------------------------

def date_key(dt_value) -> int | None:
    """
    Convert a submitted_dt / approved_dt value to a YYYYMMDD integer date key.
    Accepts datetime objects or ISO-format strings. Returns None for falsy input.
    """
    if not dt_value:
        return None
    if isinstance(dt_value, str):
        # Strip sub-second precision and timezone marker for parsing
        dt_value = datetime.fromisoformat(dt_value.replace("Z", "+00:00"))
    if isinstance(dt_value, datetime):
        d = dt_value.date()
    elif isinstance(dt_value, date):
        d = dt_value
    else:
        raise TypeError(f"Unexpected date type: {type(dt_value)}")
    return int(d.strftime("%Y%m%d"))


# ---------------------------------------------------------------------------
# dim_customer upsert  (spec §4.2)
# Type 1 SCD — overwrite company_name, segment, company_size, is_test,
# etl_last_updated_dt on conflict. first_product_type is NOT overwritten.
# ---------------------------------------------------------------------------

UPSERT_DIM_CUSTOMER = """
INSERT INTO wbbaw.dim_customer (
    customer_key,
    customer_id,
    company_name,
    segment,
    company_size,
    is_test,
    first_product_type,
    etl_first_loaded_dt,
    etl_last_updated_dt
)
VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
ON CONFLICT (customer_id) DO UPDATE SET
    company_name        = EXCLUDED.company_name,
    segment             = EXCLUDED.segment,       -- Source business_category → warehouse segment
    company_size        = EXCLUDED.company_size,
    is_test             = EXCLUDED.is_test,
    -- first_product_type: populated by a separate job; do not overwrite here
    etl_last_updated_dt = NOW()
"""


def upsert_dim_customer(cur, staged_records: list[dict]) -> int:
    """
    Upsert dim_customer for every unique customer_id in the staged batch.
    Returns the number of customers processed.
    """
    seen: set[int] = set()
    count = 0
    for r in staged_records:
        cid = r["customer_id"]
        if cid in seen:
            continue
        seen.add(cid)
        cur.execute(
            UPSERT_DIM_CUSTOMER,
            (
                customer_key(cid),
                cid,
                r["company_name"],
                r["business_category"],   # Source business_category → warehouse segment
                r["company_size"],
                r["is_test"],
                None,                     # first_product_type: populated by a separate job
            ),
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# fact_application load  (spec §4.3)
# Idempotent upsert on application_id.
#
# NOTE: decline_description is present in each staged record but is NOT
# referenced here and is NOT written to any warehouse table.
# fact_application has no decline_description column (spec D3).
# ---------------------------------------------------------------------------

UPSERT_FACT_APPLICATION = """
INSERT INTO wbbaw.fact_application (
    application_key,
    application_id,
    customer_key,
    submitted_date_key,
    approved_date_key,
    submitted_timestamp,
    approved_timestamp,
    status,
    is_approved,
    is_declined,
    days_to_decision,
    etl_load_dt
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
    etl_load_dt         = NOW()
"""


def _days_to_decision(r: dict) -> int | None:
    """
    Calendar days between reviewed_dt and submitted_dt.
    Returns None if reviewed_dt is absent.
    """
    if not r.get("reviewed_dt") or not r.get("submitted_dt"):
        return None
    try:
        reviewed = datetime.fromisoformat(r["reviewed_dt"].replace("Z", "+00:00"))
        submitted = datetime.fromisoformat(r["submitted_dt"].replace("Z", "+00:00"))
        return (reviewed.date() - submitted.date()).days
    except (ValueError, AttributeError):
        return None


def load_fact(cur, staged_records: list[dict]) -> int:
    """
    Insert or update fact_application rows for all staged records.
    Returns the number of rows processed.
    """
    count = 0
    for r in staged_records:
        app_id  = r["application_id"]
        cid     = r["customer_id"]
        status  = r["status"]

        # Derived flags
        is_approved = (status == "APPROVED")
        is_declined = (status == "DECLINED")

        # Date keys
        submitted_dk = date_key(r.get("submitted_dt"))    # primary date (as-built; see D1)
        approved_dk  = date_key(r.get("approved_dt"))     # nullable

        # days_to_decision
        dtd = _days_to_decision(r)

        # NOTE: r['decline_description'] exists but is intentionally not used here.
        # The warehouse fact table has no decline_description column (spec D3).

        cur.execute(
            UPSERT_FACT_APPLICATION,
            (
                application_key(app_id),
                app_id,
                customer_key(cid),
                submitted_dk,           # submitted_date_key — primary date
                approved_dk,
                r.get("submitted_dt"),
                r.get("approved_dt"),
                status,
                is_approved,
                is_declined,
                dtd,
            ),
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main load function
# ---------------------------------------------------------------------------

def load() -> int:
    """
    Read the staging file, upsert dimensions, load facts, commit once.
    Returns an exit code.
    """
    stage = staging_path()
    log.info("Load starting — stage=%s", stage)

    # Log configured-but-unused parameters for observability (spec Q5, Q6)
    log.info(
        "Configured parameters (not used by current load): "
        "COMMIT_INTERVAL=%d  ERROR_THRESHOLD=%d",
        commit_interval(),
        error_threshold(),
    )

    # Read all staged records into memory
    try:
        staged_records = list(read_staging(stage))
    except FileNotFoundError:
        log.error("Staging file not found: %s", stage)
        return RC_FATAL
    except Exception as exc:
        log.error("Failed to read staging file: %s", exc)
        return RC_FATAL

    log.info("Read %d staged record(s)", len(staged_records))

    if not staged_records:
        log.info("No staged records — nothing to load; RC_OK")
        return RC_OK

    # Connect to warehouse
    try:
        conn = target_connection()
    except Exception as exc:
        log.error("Failed to connect to target database: %s", exc)
        return RC_FATAL

    try:
        with conn.cursor() as cur:
            # 1. Upsert dim_customer
            cust_count = upsert_dim_customer(cur, staged_records)
            log.info("dim_customer: upserted %d customer(s)", cust_count)

            # 2. Load fact_application
            fact_count = load_fact(cur, staged_records)
            log.info("fact_application: upserted %d row(s)", fact_count)

        # Single commit after full batch (spec §5.5, Q5)
        conn.commit()
        log.info("Committed. Load complete — RC_OK")

    except Exception as exc:
        log.error("Load failed, rolling back: %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return RC_FATAL
    finally:
        conn.close()

    return RC_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(load())
