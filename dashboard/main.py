"""
WBB Onboarding Dashboard
========================

FastAPI app serving the live demo dashboard.

Left panels: source DB (live operational data)
Right panels: warehouse (analytics layer, updated when ETL runs)

The visual contrast between the two sides is the point:
left updates continuously, right only updates after the ETL runs.
"""

import os
from datetime import datetime

import psycopg2
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

SOURCE_DSN = os.environ["WBB_SOURCE_DSN"]
TARGET_DSN = os.environ["WBB_TARGET_DSN"]
REGEN_TARGET_DSN = os.environ.get("WBB_REGEN_TARGET_DSN")


def source_conn():
    return psycopg2.connect(SOURCE_DSN)


def target_conn():
    return psycopg2.connect(TARGET_DSN)


def regen_target_conn():
    if not REGEN_TARGET_DSN:
        raise RuntimeError("WBB_REGEN_TARGET_DSN is not configured")
    return psycopg2.connect(REGEN_TARGET_DSN)


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/live-feed")
def live_feed():
    with source_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    a.application_id,
                    c.company_name,
                    COALESCE(c.business_category, '—')  AS category,
                    COALESCE(c.company_size, '—')       AS size,
                    a.status,
                    a.submitted_dt
                FROM wbb.onboarding_application a
                JOIN wbb.customer c ON c.customer_id = a.customer_id
                WHERE c.is_test = FALSE
                ORDER BY a.submitted_dt DESC, a.application_id DESC
                LIMIT 12
            """)
            rows = cur.fetchall()
    return [
        {
            "id":       r[0],
            "company":  r[1],
            "category": r[2],
            "size":     r[3],
            "status":   r[4],
            "time":     r[5].strftime("%H:%M:%S") if r[5] else "—",
        }
        for r in rows
    ]


@app.get("/api/funnel")
def funnel():
    with source_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.status, COUNT(*)
                FROM wbb.onboarding_application a
                JOIN wbb.customer c ON c.customer_id = a.customer_id
                WHERE c.is_test = FALSE
                GROUP BY a.status
            """)
            rows = dict(cur.fetchall())
    total = sum(rows.values())
    return {
        "total":     total,
        "submitted": rows.get("SUBMITTED", 0),
        "in_review": rows.get("IN_REVIEW", 0),
        "approved":  rows.get("APPROVED", 0),
        "declined":  rows.get("DECLINED", 0),
        "abandoned": rows.get("ABANDONED", 0),
    }


@app.get("/api/weekly-volume")
def weekly_volume():
    try:
        with target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT iso_year_week, applications_submitted,
                           applications_approved, applications_declined
                    FROM wbbaw.vw_weekly_onboarding_volume
                    ORDER BY iso_year_week DESC
                    LIMIT 8
                """)
                rows = list(reversed(cur.fetchall()))
        return {
            "weeks":     [r[0] for r in rows],
            "submitted": [r[1] for r in rows],
            "approved":  [r[2] for r in rows],
            "declined":  [r[3] for r in rows],
            "loaded":    True,
        }
    except Exception:
        return {"weeks": [], "submitted": [], "approved": [], "declined": [], "loaded": False}


@app.post("/api/reset")
def reset():
    """Clear source data and both warehouses for a clean demo restart."""
    with source_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wbb.customer_product")
            cur.execute("DELETE FROM wbb.onboarding_application")
            cur.execute("DELETE FROM wbb.customer")
        conn.commit()
    # Clear original warehouse
    try:
        with target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wbbaw.fact_application")
                cur.execute("DELETE FROM wbbaw.dim_customer")
            conn.commit()
    except Exception:
        pass
    # Clear regen warehouse
    try:
        with regen_target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wbbaw.fact_application")
                cur.execute("DELETE FROM wbbaw.dim_customer")
            conn.commit()
    except Exception:
        pass
    return {"status": "reset", "message": "Source and warehouses cleared. Generator will populate fresh data."}


@app.post("/api/run-etl")
def run_etl():
    """
    Mini ETL — loads today's source data into the warehouse inline.
    Runs extract + load logic directly without the full ETL container.
    """
    from datetime import date

    etl_ts = datetime.utcnow()
    run_date = date.today()
    inserted = 0
    upserted = 0

    with source_conn() as src:
        with src.cursor() as cur:
            cur.execute("""
                SELECT a.application_id, a.customer_id, a.submitted_dt,
                       a.status, a.reviewed_dt, a.approved_dt,
                       c.company_name, c.business_category, c.company_size, c.is_test
                FROM wbb.onboarding_application a
                JOIN wbb.customer c ON c.customer_id = a.customer_id
                WHERE c.is_test = FALSE AND a.status <> 'ABANDONED'
            """)
            rows = cur.fetchall()

    def dkey(dt):
        if dt is None:
            return None
        d = dt.date() if hasattr(dt, 'date') else dt
        return d.year * 10000 + d.month * 100 + d.day

    def skey(prefix, *parts):
        return abs(hash((prefix,) + parts)) & ((1 << 63) - 1)

    with target_conn() as tgt:
        with tgt.cursor() as cur:
            for r in rows:
                (app_id, cust_id, sub_dt, status, rev_dt, appr_dt,
                 company_name, biz_cat, size, is_test) = r

                cur.execute("""
                    INSERT INTO wbbaw.dim_customer
                        (customer_key, customer_id, company_name, segment,
                         company_size, is_test, etl_last_updated_dt)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (customer_id) DO UPDATE SET
                        company_name=EXCLUDED.company_name,
                        segment=EXCLUDED.segment,
                        company_size=EXCLUDED.company_size,
                        etl_last_updated_dt=EXCLUDED.etl_last_updated_dt
                    RETURNING customer_key
                """, (skey('cust', cust_id), cust_id, company_name,
                      biz_cat, size, is_test, etl_ts))
                actual_cust_key = cur.fetchone()[0]
                upserted += 1

                days = None
                if rev_dt and sub_dt:
                    days = (rev_dt.date() - sub_dt.date()).days

                cur.execute("""
                    INSERT INTO wbbaw.fact_application
                        (application_key, application_id, customer_key,
                         submitted_date_key, approved_date_key,
                         submitted_timestamp, approved_timestamp,
                         status, is_approved, is_declined,
                         days_to_decision, etl_load_dt)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (application_id) DO UPDATE SET
                        customer_key=EXCLUDED.customer_key,
                        submitted_date_key=EXCLUDED.submitted_date_key,
                        approved_date_key=EXCLUDED.approved_date_key,
                        submitted_timestamp=EXCLUDED.submitted_timestamp,
                        approved_timestamp=EXCLUDED.approved_timestamp,
                        status=EXCLUDED.status,
                        is_approved=EXCLUDED.is_approved,
                        is_declined=EXCLUDED.is_declined,
                        days_to_decision=EXCLUDED.days_to_decision,
                        etl_load_dt=EXCLUDED.etl_load_dt
                """, (skey('app', app_id), app_id, actual_cust_key,
                      dkey(sub_dt), dkey(appr_dt),
                      sub_dt, appr_dt,
                      status, status == 'APPROVED', status == 'DECLINED',
                      days, etl_ts))
                inserted += 1

        tgt.commit()

    return {"status": "ok", "dim_rows": upserted, "fact_rows": inserted}


@app.get("/api/approval-by-segment")
def approval_by_segment():
    try:
        with target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT segment, total_applications, approved_count, approval_rate_pct
                    FROM wbbaw.vw_approval_rate_by_segment
                    WHERE segment IS NOT NULL
                    ORDER BY total_applications DESC
                    LIMIT 8
                """)
                rows = cur.fetchall()
        return {
            "data": [
                {"segment": r[0], "total": r[1], "approved": r[2],
                 "rate": float(r[3] or 0)}
                for r in rows
            ],
            "loaded": True,
        }
    except Exception:
        return {"data": [], "loaded": False}


@app.post("/api/run-etl/regen")
def run_etl_regen():
    """
    Mini ETL for the regenerated warehouse — loads source data into wbbaw_regen.
    Mirrors /api/run-etl logic but targets the regen warehouse via REGEN_TARGET_DSN.
    """
    from datetime import date

    etl_ts = datetime.utcnow()
    inserted = 0
    upserted = 0

    with source_conn() as src:
        with src.cursor() as cur:
            cur.execute("""
                SELECT a.application_id, a.customer_id, a.submitted_dt,
                       a.status, a.reviewed_dt, a.approved_dt,
                       c.company_name, c.business_category, c.company_size, c.is_test
                FROM wbb.onboarding_application a
                JOIN wbb.customer c ON c.customer_id = a.customer_id
                WHERE c.is_test = FALSE AND a.status <> 'ABANDONED'
            """)
            rows = cur.fetchall()

    def dkey(dt):
        if dt is None:
            return None
        d = dt.date() if hasattr(dt, 'date') else dt
        return d.year * 10000 + d.month * 100 + d.day

    def skey(prefix, *parts):
        return abs(hash((prefix,) + parts)) & ((1 << 63) - 1)

    try:
        with regen_target_conn() as tgt:
            with tgt.cursor() as cur:
                for r in rows:
                    (app_id, cust_id, sub_dt, status, rev_dt, appr_dt,
                     company_name, biz_cat, size, is_test) = r

                    cur.execute("""
                        INSERT INTO wbbaw.dim_customer
                            (customer_key, customer_id, company_name, segment,
                             company_size, is_test, etl_last_updated_dt)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (customer_id) DO UPDATE SET
                            company_name=EXCLUDED.company_name,
                            segment=EXCLUDED.segment,
                            company_size=EXCLUDED.company_size,
                            etl_last_updated_dt=EXCLUDED.etl_last_updated_dt
                        RETURNING customer_key
                    """, (skey('cust', cust_id), cust_id, company_name,
                          biz_cat, size, is_test, etl_ts))
                    actual_cust_key = cur.fetchone()[0]
                    upserted += 1

                    days = None
                    if rev_dt and sub_dt:
                        days = (rev_dt.date() - sub_dt.date()).days

                    cur.execute("""
                        INSERT INTO wbbaw.fact_application
                            (application_key, application_id, customer_key,
                             submitted_date_key, approved_date_key,
                             submitted_timestamp, approved_timestamp,
                             status, is_approved, is_declined,
                             days_to_decision, etl_load_dt)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (application_id) DO UPDATE SET
                            customer_key=EXCLUDED.customer_key,
                            submitted_date_key=EXCLUDED.submitted_date_key,
                            approved_date_key=EXCLUDED.approved_date_key,
                            submitted_timestamp=EXCLUDED.submitted_timestamp,
                            approved_timestamp=EXCLUDED.approved_timestamp,
                            status=EXCLUDED.status,
                            is_approved=EXCLUDED.is_approved,
                            is_declined=EXCLUDED.is_declined,
                            days_to_decision=EXCLUDED.days_to_decision,
                            etl_load_dt=EXCLUDED.etl_load_dt
                    """, (skey('app', app_id), app_id, actual_cust_key,
                          dkey(sub_dt), dkey(appr_dt),
                          sub_dt, appr_dt,
                          status, status == 'APPROVED', status == 'DECLINED',
                          days, etl_ts))
                    inserted += 1

            tgt.commit()
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    return {"status": "ok", "dim_rows": upserted, "fact_rows": inserted}


@app.get("/api/equivalence")
def equivalence():
    """
    Run the same weekly-volume query against both warehouses and compare results.
    Returns original rows, regenerated rows, whether they match, and diff count.
    """
    query = """
        SELECT iso_year_week, applications_submitted, applications_approved, applications_declined
        FROM wbbaw.vw_weekly_onboarding_volume
        ORDER BY iso_year_week DESC LIMIT 5
    """

    def fetch_rows(conn_fn):
        with conn_fn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()

    try:
        orig_rows = fetch_rows(target_conn)
    except Exception:
        orig_rows = []

    try:
        regen_rows = fetch_rows(regen_target_conn)
    except Exception:
        regen_rows = []

    if not orig_rows and not regen_rows:
        return {
            "original": [], "regenerated": [],
            "matches": False, "diff_count": 0, "loaded": False,
        }

    def fmt(rows):
        return [
            {
                "week":      r[0],
                "submitted": r[1],
                "approved":  r[2],
                "declined":  r[3],
            }
            for r in rows
        ]

    orig_fmt  = fmt(orig_rows)
    regen_fmt = fmt(regen_rows)

    # Compare row by row (keyed on week)
    orig_by_week  = {r["week"]: r for r in orig_fmt}
    regen_by_week = {r["week"]: r for r in regen_fmt}
    all_weeks = sorted(set(orig_by_week) | set(regen_by_week), reverse=True)[:5]

    diff_count = 0
    for week in all_weeks:
        o = orig_by_week.get(week)
        r = regen_by_week.get(week)
        if o != r:
            diff_count += 1

    matches = (diff_count == 0) and bool(orig_rows) and bool(regen_rows)

    return {
        "original":    orig_fmt,
        "regenerated": regen_fmt,
        "matches":     matches,
        "diff_count":  diff_count,
        "loaded":      bool(orig_rows) and bool(regen_rows),
    }


_NEW_FEATURE_VIEW_SQL = """
CREATE OR REPLACE VIEW wbbaw.vw_avg_days_to_approval_by_segment AS
SELECT
    c.segment,
    COUNT(*)                                    AS approved_applications,
    ROUND(AVG(f.days_to_decision), 1)           AS avg_days_to_approval,
    MIN(f.approved_timestamp)::date             AS period_start,
    MAX(f.approved_timestamp)::date             AS period_end
FROM wbbaw.fact_application f
JOIN wbbaw.dim_customer c ON f.customer_key = c.customer_key
WHERE f.is_approved = TRUE
  AND f.days_to_decision IS NOT NULL
  AND c.segment IS NOT NULL
GROUP BY c.segment
ORDER BY avg_days_to_approval;
"""


@app.post("/api/new-feature/deploy")
def new_feature_deploy():
    """Deploy vw_avg_days_to_approval_by_segment to both warehouses."""
    orig_ok  = False
    regen_ok = False

    try:
        with target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_NEW_FEATURE_VIEW_SQL)
            conn.commit()
        orig_ok = True
    except Exception:
        pass

    try:
        with regen_target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_NEW_FEATURE_VIEW_SQL)
            conn.commit()
        regen_ok = True
    except Exception:
        pass

    status = "deployed" if (orig_ok and regen_ok) else "partial"
    return {"status": status, "original": orig_ok, "regenerated": regen_ok}


@app.get("/api/new-feature/query")
def new_feature_query():
    """
    Query vw_avg_days_to_approval_by_segment from both warehouses and compare.
    """
    query = """
        SELECT segment, approved_applications, avg_days_to_approval
        FROM wbbaw.vw_avg_days_to_approval_by_segment
        ORDER BY segment
    """

    def fetch_rows(conn_fn):
        with conn_fn() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()

    try:
        orig_rows = fetch_rows(target_conn)
    except Exception:
        return {"original": [], "regenerated": [], "matches": False, "deployed": False}

    try:
        regen_rows = fetch_rows(regen_target_conn)
    except Exception:
        return {"original": [], "regenerated": [], "matches": False, "deployed": False}

    def fmt(rows):
        return [
            {
                "segment":  r[0],
                "approved": int(r[1]),
                "avg_days": float(r[2]) if r[2] is not None else None,
            }
            for r in rows
        ]

    orig_fmt  = fmt(orig_rows)
    regen_fmt = fmt(regen_rows)

    # Compare by segment
    orig_by_seg  = {r["segment"]: r for r in orig_fmt}
    regen_by_seg = {r["segment"]: r for r in regen_fmt}
    all_segs = sorted(set(orig_by_seg) | set(regen_by_seg))

    diff_count = sum(1 for s in all_segs if orig_by_seg.get(s) != regen_by_seg.get(s))
    matches = (diff_count == 0) and bool(orig_rows) and bool(regen_rows)

    return {
        "original":    orig_fmt,
        "regenerated": regen_fmt,
        "matches":     matches,
        "diff_count":  diff_count,
        "deployed":    bool(orig_rows) and bool(regen_rows),
    }
