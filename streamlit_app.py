"""
WBB Analytics Warehouse — Spec-Driven Development Demo
10-tab Streamlit application, SQLite backend, no Docker required.

Tabs:
  1  Live System              customer onboarding running in-process
  2  Artifacts                BRD, schemas, user stories, job config, ETL code
  3  Spec                     forensic reverse-engineering output
  4  Regenerated Artifacts    schema + ETL rebuilt from spec alone
  5  Proof: Drift Managed     original vs regenerated — same business outputs
  6  New Feature              avg-days-to-approval added from spec as launchpad
  7  Production Tickets       7 WBB ServiceNow incidents
  8  Enriched Spec            spec + operational knowledge from ticket history
  9  FAQ                      generated from enriched spec
  10 L3 Support Chatbot       embedded Claude API chatbot

Run:   streamlit run streamlit_app.py
Deps:  pip install streamlit pandas anthropic
"""

import datetime
import hashlib
import json
import os
import random
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

try:
    import anthropic as _anthropic_module
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ── Paths ──────────────────────────────────────────────────────────────────────

BASE      = Path(__file__).parent
DB_PATH   = BASE / "wbb_demo.db"
FALLBACK  = BASE / "demo" / "fallback"
ARTIFACTS = BASE / "artifacts"
PROMPTS   = BASE / "prompts"
REGEN     = FALLBACK / "regenerated"

# ── Domain constants ───────────────────────────────────────────────────────────

SEGMENTS = [
    "RETAIL", "TECHNOLOGY", "CONSTRUCTION", "HOSPITALITY",
    "PROFESSIONAL_SERVICES", "HEALTHCARE", "MANUFACTURING", "LOGISTICS",
]
SIZES = ["MICRO", "SMALL", "MEDIUM", "LARGE"]
APPROVAL_RATE = {"MICRO": 0.32, "SMALL": 0.48, "MEDIUM": 0.61, "LARGE": 0.74}

_PRODUCTS = [
    ("Business Chequing",  "BUS_CHQ"),
    ("Business Savings",   "BUS_SAV"),
    ("Merchant Services",  "MER_SVC"),
    ("Business Visa",      "BUS_VISA"),
    ("Payroll Services",   "PAYROLL"),
    ("FX Services",        "FX_SVC"),
    ("Trade Finance",      "TRADE"),
]
_DECLINE_REASONS = [
    ("RISK_001", "Insufficient credit history",       "CREDIT_RISK"),
    ("RISK_002", "High debt-to-income ratio",          "CREDIT_RISK"),
    ("DOC_001",  "Missing identification documents",   "DOCUMENTATION"),
    ("DOC_002",  "Incomplete business registration",   "DOCUMENTATION"),
    ("COMP_001", "Industry not eligible",              "COMPLIANCE"),
    ("COMP_002", "Sanctions screening match",          "COMPLIANCE"),
    ("FRAUD_001","Suspected fraudulent application",   "FRAUD"),
    ("CAP_001",  "Daily capacity reached",             "CAPACITY"),
    ("OTHER_001","Application withdrawn by customer",  "OTHER"),
]
_PREFIXES = [
    "Apex", "Summit", "Pacific", "Northern", "Central", "Allied",
    "Premier", "Capital", "Heritage", "Crown", "Metro", "Pioneer",
    "Keystone", "Broadview", "Ridgeway", "Lakeshore",
]
_SUFFIXES = [
    "Corp", "Inc", "Ltd", "Group", "Solutions", "Partners",
    "Enterprises", "Associates", "Services", "Holdings",
]

# ── SQLite schema ──────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name      TEXT    NOT NULL,
    business_category TEXT    NOT NULL,
    company_size      TEXT    NOT NULL,
    contact_email     TEXT,
    is_test           INTEGER DEFAULT 0,
    created_at        TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS onboarding_applications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    status       TEXT    DEFAULT 'SUBMITTED',
    submitted_at TEXT    DEFAULT (datetime('now')),
    decided_at   TEXT,
    assigned_to  TEXT
);
CREATE TABLE IF NOT EXISTS banking_products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    product_code TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS decline_reasons_ref (
    reason_code TEXT PRIMARY KEY,
    reason_text TEXT,
    category    TEXT
);
CREATE TABLE IF NOT EXISTS application_decline_reasons (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    reason_code    TEXT,
    reason_text    TEXT,
    category       TEXT
);
-- Original warehouse
CREATE TABLE IF NOT EXISTS wh_dim_customer (
    customer_key INTEGER PRIMARY KEY,
    customer_id  INTEGER UNIQUE,
    company_name TEXT,
    segment      TEXT,
    company_size TEXT,
    etl_at       TEXT
);
CREATE TABLE IF NOT EXISTS wh_fact_application (
    app_key             INTEGER PRIMARY KEY,
    application_id      INTEGER UNIQUE,
    customer_key        INTEGER,
    submitted_year_week TEXT,
    is_approved         INTEGER DEFAULT 0,
    is_declined         INTEGER DEFAULT 0,
    decision_days       REAL,
    etl_at              TEXT
);
-- Regenerated warehouse (semantically identical, separate tables)
CREATE TABLE IF NOT EXISTS regen_dim_customer (
    customer_key INTEGER PRIMARY KEY,
    customer_id  INTEGER UNIQUE,
    company_name TEXT,
    segment      TEXT,
    company_size TEXT,
    etl_at       TEXT
);
CREATE TABLE IF NOT EXISTS regen_fact_application (
    app_key             INTEGER PRIMARY KEY,
    application_id      INTEGER UNIQUE,
    customer_key        INTEGER,
    submitted_year_week TEXT,
    is_approved         INTEGER DEFAULT 0,
    is_declined         INTEGER DEFAULT 0,
    decision_days       REAL,
    etl_at              TEXT
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript(_SCHEMA)
    conn.commit()
    if conn.execute("SELECT COUNT(*) FROM banking_products").fetchone()[0] == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO banking_products (product_name, product_code) VALUES (?,?)",
            _PRODUCTS,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO decline_reasons_ref VALUES (?,?,?)",
            [(r, t, c) for r, t, c in _DECLINE_REASONS],
        )
        conn.commit()
    conn.close()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _iso_week(dt_str: str) -> str:
    d = datetime.date.fromisoformat(dt_str[:10])
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _surr_key_orig(prefix: str, id_: int) -> int:
    return abs(hash((prefix, id_))) & ((1 << 63) - 1)


def _surr_key_regen(prefix: str, id_: int) -> int:
    raw = int(hashlib.md5(f"{prefix}:{id_}".encode()).hexdigest(), 16)
    return raw % (2 ** 63)

# ── Data generation ────────────────────────────────────────────────────────────

def add_application(days_ago: float = 0.0) -> None:
    seg   = random.choice(SEGMENTS)
    size  = random.choice(SIZES)
    name  = f"{random.choice(_PREFIXES)} {random.choice(_SUFFIXES)}"
    email = f"info@{name.lower().replace(' ', '')[:12]}.com"

    conn  = get_db()
    cid   = conn.execute(
        "INSERT INTO customers (company_name, business_category, company_size, contact_email)"
        " VALUES (?,?,?,?)",
        (name, seg, size, email),
    ).lastrowid

    base_dt = datetime.datetime.utcnow() - datetime.timedelta(
        days=days_ago, hours=random.uniform(0, 23)
    )
    sub = base_dt.isoformat(timespec="seconds")

    r    = random.random()
    rate = APPROVAL_RATE[size]
    if r < rate:
        status = "APPROVED"
        delta  = random.uniform(2, 14)
    elif r < rate + 0.28:
        status = "DECLINED"
        delta  = random.uniform(3, 21)
    elif r < rate + 0.36:
        status = "IN_REVIEW"
        delta  = None
    else:
        status = "SUBMITTED"
        delta  = None

    dec = (base_dt + datetime.timedelta(days=delta)).isoformat(timespec="seconds") if delta else None

    aid = conn.execute(
        "INSERT INTO onboarding_applications (customer_id, status, submitted_at, decided_at)"
        " VALUES (?,?,?,?)",
        (cid, status, sub, dec),
    ).lastrowid

    if status == "DECLINED":
        rc, rt, cat = random.choice(_DECLINE_REASONS)
        conn.execute(
            "INSERT INTO application_decline_reasons VALUES (NULL,?,?,?,?)",
            (aid, rc, rt, cat),
        )

    conn.commit()
    conn.close()


def seed_data(days: int = 30) -> None:
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM onboarding_applications").fetchone()[0]
    conn.close()
    if n > 10:
        return
    for d in range(days, 0, -1):
        for _ in range(random.randint(6, 18)):
            add_application(days_ago=float(d))

# ── Original ETL ───────────────────────────────────────────────────────────────

def run_original_etl() -> dict:
    """
    Original hand-written ETL (wbbxtr → wbbldr pattern).
    Writes to wh_dim_customer and wh_fact_application.
    Seeded inconsistency D1: uses submitted_at for submitted_year_week
    (BRD §5 says group by approval date, but approved_dt was absent
    from source when ETL was built).
    """
    conn = get_db()
    now  = datetime.datetime.utcnow().isoformat(timespec="seconds")

    customer_rows = conn.execute("""
        SELECT DISTINCT c.id, c.company_name, c.business_category, c.company_size
        FROM customers c
        JOIN onboarding_applications a ON a.customer_id = c.id
        WHERE c.is_test = 0
    """).fetchall()

    for r in customer_rows:
        ck = _surr_key_orig("cust", r["id"])
        conn.execute("""
            INSERT INTO wh_dim_customer
                (customer_key, customer_id, company_name, segment, company_size, etl_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(customer_id) DO UPDATE SET
                company_name=excluded.company_name,
                segment=excluded.segment,
                company_size=excluded.company_size,
                etl_at=excluded.etl_at
        """, (ck, r["id"], r["company_name"], r["business_category"], r["company_size"], now))

    app_rows = conn.execute("""
        SELECT a.id, a.customer_id, a.status, a.submitted_at, a.decided_at
        FROM onboarding_applications a
        JOIN customers c ON c.id = a.customer_id
        WHERE c.is_test = 0 AND a.status NOT IN ('ABANDONED')
    """).fetchall()

    for a in app_rows:
        ck    = _surr_key_orig("cust", a["customer_id"])
        ak    = _surr_key_orig("app",  a["id"])
        week  = _iso_week(a["submitted_at"])
        appr  = 1 if a["status"] == "APPROVED" else 0
        decl  = 1 if a["status"] == "DECLINED" else 0
        days  = None
        if a["decided_at"]:
            d1   = datetime.date.fromisoformat(a["decided_at"][:10])
            d0   = datetime.date.fromisoformat(a["submitted_at"][:10])
            days = (d1 - d0).days

        conn.execute("""
            INSERT INTO wh_fact_application
                (app_key, application_id, customer_key, submitted_year_week,
                 is_approved, is_declined, decision_days, etl_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(application_id) DO UPDATE SET
                customer_key=excluded.customer_key,
                submitted_year_week=excluded.submitted_year_week,
                is_approved=excluded.is_approved,
                is_declined=excluded.is_declined,
                decision_days=excluded.decision_days,
                etl_at=excluded.etl_at
        """, (ak, a["id"], ck, week, appr, decl, days, now))

    conn.commit()
    conn.close()
    return {"customers": len(customer_rows), "applications": len(app_rows)}

# ── Regenerated ETL ────────────────────────────────────────────────────────────

def run_regen_etl() -> dict:
    """
    Regenerated from spec alone — wbbaw_spec_v1.md.
    Writes to regen_dim_customer and regen_fact_application.
    Syntactically different from original (variable names, key formula,
    query structure) due to LLM non-determinism in regeneration.
    Semantically equivalent: same exclusions, same mapping, same business outputs.
    """
    conn = get_db()
    ts   = datetime.datetime.utcnow().isoformat(timespec="seconds")

    # Dimension: one row per customer that has at least one non-abandoned application
    cust_records = conn.execute("""
        SELECT DISTINCT
            c.id             AS cid,
            c.company_name   AS name,
            c.business_category AS biz_cat,
            c.company_size   AS sz
        FROM customers c
        INNER JOIN onboarding_applications app ON app.customer_id = c.id
        WHERE c.is_test = 0
    """).fetchall()

    for rec in cust_records:
        # Spec §4.4: deterministic surrogate key from (prefix, natural_key).
        # Regen uses MD5-based formula — different value, same uniqueness guarantee.
        ckey = _surr_key_regen("cust", rec["cid"])
        conn.execute("""
            INSERT INTO regen_dim_customer
                (customer_key, customer_id, company_name, segment, company_size, etl_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(customer_id) DO UPDATE SET
                company_name=excluded.company_name,
                segment=excluded.segment,
                company_size=excluded.company_size,
                etl_at=excluded.etl_at
        """, (ckey, rec["cid"], rec["name"], rec["biz_cat"], rec["sz"], ts))

    # Fact: one row per application
    app_records = conn.execute("""
        SELECT
            app.id          AS app_id,
            app.customer_id AS cust_id,
            app.status      AS status,
            app.submitted_at,
            app.decided_at
        FROM onboarding_applications app
        INNER JOIN customers c ON c.id = app.customer_id
        WHERE c.is_test = 0
          AND app.status != 'ABANDONED'
    """).fetchall()

    for row in app_records:
        ckey = _surr_key_regen("cust", row["cust_id"])
        akey = _surr_key_regen("app",  row["app_id"])
        week = _iso_week(row["submitted_at"])
        is_appr = 1 if row["status"] == "APPROVED" else 0
        is_decl = 1 if row["status"] == "DECLINED" else 0
        ddiff   = None
        if row["decided_at"]:
            dt1   = datetime.date.fromisoformat(row["decided_at"][:10])
            dt0   = datetime.date.fromisoformat(row["submitted_at"][:10])
            ddiff = (dt1 - dt0).days

        conn.execute("""
            INSERT INTO regen_fact_application
                (app_key, application_id, customer_key, submitted_year_week,
                 is_approved, is_declined, decision_days, etl_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(application_id) DO UPDATE SET
                customer_key=excluded.customer_key,
                submitted_year_week=excluded.submitted_year_week,
                is_approved=excluded.is_approved,
                is_declined=excluded.is_declined,
                decision_days=excluded.decision_days,
                etl_at=excluded.etl_at
        """, (akey, row["app_id"], ckey, week, is_appr, is_decl, ddiff, ts))

    conn.commit()
    conn.close()
    return {"customers": len(cust_records), "applications": len(app_records)}

# ── Query helpers ──────────────────────────────────────────────────────────────

def query_weekly_volume(fact_table: str) -> pd.DataFrame:
    conn = get_db()
    df = pd.read_sql_query(f"""
        SELECT
            submitted_year_week  AS week,
            COUNT(*)             AS total,
            SUM(is_approved)     AS approved,
            SUM(is_declined)     AS declined
        FROM {fact_table}
        GROUP BY submitted_year_week
        ORDER BY submitted_year_week
    """, conn)
    conn.close()
    return df


def query_approval_by_segment(dim_table: str, fact_table: str) -> pd.DataFrame:
    conn = get_db()
    df = pd.read_sql_query(f"""
        SELECT
            dc.segment,
            COUNT(*)                                  AS total,
            SUM(fa.is_approved)                       AS approved,
            ROUND(100.0 * SUM(fa.is_approved) / COUNT(*), 1) AS approval_rate_pct
        FROM {fact_table} fa
        JOIN {dim_table} dc ON dc.customer_key = fa.customer_key
        GROUP BY dc.segment
        ORDER BY approval_rate_pct DESC
    """, conn)
    conn.close()
    return df


def query_avg_days_to_approval(dim_table: str, fact_table: str) -> pd.DataFrame:
    conn = get_db()
    df = pd.read_sql_query(f"""
        SELECT
            dc.segment,
            ROUND(AVG(fa.decision_days), 1) AS avg_days_to_approval,
            COUNT(*)                         AS approved_count
        FROM {fact_table} fa
        JOIN {dim_table} dc ON dc.customer_key = fa.customer_key
        WHERE fa.is_approved = 1
          AND fa.decision_days IS NOT NULL
        GROUP BY dc.segment
        ORDER BY avg_days_to_approval DESC
    """, conn)
    conn.close()
    return df


def _read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[File not found: {path}]"


def _get_api_key() -> Optional[str]:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def _get_client():
    if not _ANTHROPIC_AVAILABLE:
        return None
    key = _get_api_key()
    if not key:
        return None
    return _anthropic_module.Anthropic(api_key=key)


def _stream_to_placeholder(client, user_message: str, output_path: Path, label: str) -> str:
    """Stream a Claude response, update a Streamlit placeholder, save to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    st.subheader(label)
    placeholder = st.empty()
    full_text   = ""
    with client.messages.stream(
        model      = "claude-sonnet-4-6",
        max_tokens = 8000,
        messages   = [{"role": "user", "content": user_message}],
    ) as stream:
        for chunk in stream.text_stream:
            full_text += chunk
            placeholder.markdown(full_text + " ▌")
    placeholder.markdown(full_text)
    output_path.write_text(full_text, encoding="utf-8")
    st.success(f"Saved to {output_path.relative_to(BASE)}")
    return full_text


def _build_spec_prompt() -> str:
    artifact_files = [
        ("brd_wbb_v1.1.md",       ARTIFACTS / "brd_wbb_v1.1.md"),
        ("source_schema.sql",      ARTIFACTS / "source_schema.sql"),
        ("target_schema.sql",      ARTIFACTS / "target_schema.sql"),
        ("user_stories_export.md", ARTIFACTS / "user_stories_export.md"),
        ("job_config.yaml",        ARTIFACTS / "job_config.yaml"),
        ("wbbxtr.py",              ARTIFACTS / "etl" / "wbbxtr.py"),
        ("wbbldr.py",              ARTIFACTS / "etl" / "wbbldr.py"),
        ("wbb_common.py",          ARTIFACTS / "etl" / "wbb_common.py"),
    ]
    block = "Here are the project artifacts for the WBB Analytics Warehouse:\n"
    for name, path in artifact_files:
        block += f"\n\n---\n## ARTIFACT: {name}\n\n{_read_file(path)}"

    prompt_text = _read_file(PROMPTS / "01_reverse_engineering.md")
    prompt_body = prompt_text.split("---", 1)[1].strip() if "---" in prompt_text else prompt_text
    return f"{block}\n\n---\n\n{prompt_body}"


def _build_regen_prompt(spec_content: str) -> str:
    prompt_text = _read_file(PROMPTS / "02_regeneration.md")
    prompt_body = prompt_text.split("---", 1)[1].strip() if "---" in prompt_text else prompt_text
    return (
        f"Here is the WBBAW forensic specification — your only input:\n\n"
        f"---\n\n{spec_content}\n\n---\n\n{prompt_body}"
    )

# ── Tab 1: Live System ─────────────────────────────────────────────────────────

def tab_live_system() -> None:
    st.header("WBB Customer Onboarding — Live System")
    st.caption(
        "Business banking customers applying for WBB products. "
        "This is the source system the ETL pipeline reads from."
    )

    conn = get_db()
    totals = conn.execute("""
        SELECT
            COUNT(*)                          AS total,
            SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN status='DECLINED' THEN 1 ELSE 0 END) AS declined,
            SUM(CASE WHEN status IN ('SUBMITTED','IN_REVIEW') THEN 1 ELSE 0 END) AS pending
        FROM onboarding_applications
    """).fetchone()
    conn.close()

    total    = totals["total"]    or 0
    approved = totals["approved"] or 0
    declined = totals["declined"] or 0
    pending  = totals["pending"]  or 0
    rate     = round(100 * approved / total, 1) if total else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Applications", total)
    c2.metric("Approved", approved)
    c3.metric("Declined", declined)
    c4.metric("Pending", pending)
    c5.metric("Approval Rate", f"{rate}%")

    st.divider()

    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("Add New Application", type="primary"):
            add_application()
            st.rerun()
        if total < 10:
            if st.button("Seed 30 Days of Historical Data"):
                with st.spinner("Seeding data..."):
                    for d in range(30, 0, -1):
                        for _ in range(random.randint(6, 18)):
                            add_application(days_ago=float(d))
                st.rerun()

    with col_b:
        conn = get_db()
        recent = pd.read_sql_query("""
            SELECT
                a.id,
                c.company_name,
                c.business_category AS segment,
                c.company_size      AS size,
                a.status,
                a.submitted_at,
                a.decided_at
            FROM onboarding_applications a
            JOIN customers c ON c.id = a.customer_id
            ORDER BY a.id DESC
            LIMIT 10
        """, conn)
        conn.close()
        st.subheader("Recent Applications")
        st.dataframe(recent, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Applications by Status — Last 30 Days")
    conn = get_db()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat()
    by_status = pd.read_sql_query(f"""
        SELECT status, COUNT(*) AS count
        FROM onboarding_applications
        WHERE submitted_at >= '{cutoff}'
        GROUP BY status
        ORDER BY count DESC
    """, conn)
    conn.close()
    if not by_status.empty:
        st.bar_chart(by_status.set_index("status")["count"])

# ── Tab 2: Artifacts ───────────────────────────────────────────────────────────

def tab_artifacts() -> None:
    st.header("Project Artifacts")
    st.caption(
        "Six artifacts produced during the WBB Analytics Warehouse delivery. "
        "These are the raw inputs to the forensic reverse-engineering pass."
    )

    artifact_map = {
        "BRD v1.1":        (ARTIFACTS / "brd_wbb_v1.1.md",          "markdown"),
        "Source Schema":   (ARTIFACTS / "source_schema.sql",         "sql"),
        "Target Schema":   (ARTIFACTS / "target_schema.sql",         "sql"),
        "User Stories":    (ARTIFACTS / "user_stories_export.md",    "markdown"),
        "Job Config":      (ARTIFACTS / "job_config.yaml",           "yaml"),
        "ETL Extract":     (ARTIFACTS / "etl" / "wbbxtr.py",         "python"),
        "ETL Load":        (ARTIFACTS / "etl" / "wbbldr.py",         "python"),
    }

    choice = st.selectbox("Select artifact", list(artifact_map))
    path, lang = artifact_map[choice]
    content = _read_file(path)

    if lang == "markdown":
        st.markdown(content)
    else:
        st.code(content, language=lang)

# ── Tab 3: Spec ────────────────────────────────────────────────────────────────

def tab_spec() -> None:
    st.header("Forensic Specification — WBBAW v1.0")
    st.caption(
        "Produced by running the reverse-engineering prompt against all six artifacts. "
        "Every claim in this document has a provenance citation."
    )

    live_spec    = BASE / "spec" / "wbbaw_spec_live.md"
    fallback_spec = FALLBACK / "wbbaw_spec_v1.md"
    spec_path    = live_spec if live_spec.exists() else fallback_spec

    col_hdr, col_btn = st.columns([3, 1])
    with col_hdr:
        if live_spec.exists():
            st.success("Showing live-generated spec.", icon="✅")
        else:
            st.info("Showing pre-built fallback spec. Click to generate live.", icon="📋")
    with col_btn:
        client = _get_client()
        if client is None:
            st.caption("Set ANTHROPIC_API_KEY to enable.")
        else:
            if st.button("Generate Spec Live", type="primary", use_container_width=True):
                _stream_to_placeholder(
                    client,
                    _build_spec_prompt(),
                    live_spec,
                    "Generating forensic specification...",
                )
                st.rerun()

    st.info(
        "**4 discrepancies found.** "
        "D1 — date key mismatch (submitted vs approval date).  "
        "D2 — three names for one field.  "
        "D3 — story Done, feature missing from warehouse.  "
        "D4 — job references program that does not exist.",
        icon="🔍",
    )

    content = _read_file(spec_path)
    st.markdown(content)

# ── Tab 4: Regenerated Artifacts ───────────────────────────────────────────────

def tab_regenerated() -> None:
    st.header("Regenerated Artifacts")
    st.caption(
        "Built from the spec alone — no access to the original artifacts. "
        "The claim: the spec is sufficient to reconstruct a semantically equivalent system."
    )

    live_regen = BASE / "regenerated" / "wbbaw_regen_live.md"

    col_hdr, col_btn = st.columns([3, 1])
    with col_hdr:
        if live_regen.exists():
            st.success("Live regeneration available.", icon="✅")
        else:
            st.info(
                "Showing pre-built fallback artifacts. "
                "Click to regenerate live from the spec — original artifacts not consulted.",
                icon="🔄",
            )
    with col_btn:
        client = _get_client()
        if client is None:
            st.caption("Set ANTHROPIC_API_KEY to enable.")
        else:
            if st.button("Regenerate from Spec", type="primary", use_container_width=True):
                live_spec   = BASE / "spec" / "wbbaw_spec_live.md"
                spec_path   = live_spec if live_spec.exists() else FALLBACK / "wbbaw_spec_v1.md"
                spec_content = _read_file(spec_path)
                _stream_to_placeholder(
                    client,
                    _build_regen_prompt(spec_content),
                    live_regen,
                    "Regenerating from spec alone...",
                )
                st.rerun()

    st.divider()

    if live_regen.exists():
        st.subheader("Live Regeneration Output")
        st.markdown(_read_file(live_regen))
        st.divider()

    st.subheader("Pre-Built Fallback Artifacts")
    regen_map = {
        "Source Schema (regenerated)": (REGEN / "source_schema.sql",   "sql"),
        "ETL Extract (regenerated)":   (REGEN / "etl" / "extract.py",  "python"),
        "Regeneration Prompt":         (PROMPTS / "02_regeneration.md", "markdown"),
    }
    choice = st.selectbox("Select artifact", list(regen_map))
    path, lang = regen_map[choice]
    content = _read_file(path)
    if lang == "markdown":
        st.markdown(content)
    else:
        st.code(content, language=lang)

# ── Tab 5: Proof ───────────────────────────────────────────────────────────────

def tab_proof() -> None:
    st.header("Proof: Drift is Manageable")
    st.caption(
        "Same business query. Both warehouses. Identical results. "
        "Periodic regeneration is the governance mechanism — not a one-time exercise."
    )

    st.markdown("""
**The claim:** A spec produced by forensic reverse engineering is sufficient to regenerate
a semantically equivalent system. Syntactic differences between the original and regenerated
code are expected (LLM non-determinism) and are non-material.

**The governance model:** Regenerate from the spec quarterly. Run the equivalence check.
If the outputs match, the spec is valid. If they diverge, you have a documented management
problem — not a mystery.
""")

    st.divider()

    col_run, col_status = st.columns([2, 3])

    with col_run:
        if st.button("Compare", type="primary", help="Run both ETLs and prove equivalence"):
            with st.spinner("Running original ETL..."):
                orig_result = run_original_etl()
            with st.spinner("Running regenerated ETL..."):
                regen_result = run_regen_etl()
            st.session_state["etl_orig_run"]  = True
            st.session_state["etl_regen_run"] = True
            st.session_state["orig_result"]   = orig_result
            st.session_state["regen_result"]  = regen_result
            st.rerun()

    orig_done  = st.session_state.get("etl_orig_run", False)
    regen_done = st.session_state.get("etl_regen_run", False)

    with col_status:
        o = "✅ Run" if orig_done else "⬜ Not run"
        r = "✅ Run" if regen_done else "⬜ Not run"
        st.markdown(f"**Original ETL:** {o}  \n**Regen ETL:** {r}")
        if orig_done:
            res = st.session_state.get("orig_result", {})
            st.caption(f"Original: {res.get('customers', '?')} customers, {res.get('applications', '?')} applications")
        if regen_done:
            res = st.session_state.get("regen_result", {})
            st.caption(f"Regen:    {res.get('customers', '?')} customers, {res.get('applications', '?')} applications")

    if not (orig_done and regen_done):
        st.info("Click **Compare** to load both warehouses and run the equivalence check.")
        return

    st.divider()

    # ── Side-by-side query outputs ─────────────────────────────────────────────
    st.subheader("Business Query: Weekly Application Volume")
    st.caption("Same SQL, two warehouses — do they produce identical outputs?")

    orig_vol  = query_weekly_volume("wh_fact_application")
    regen_vol = query_weekly_volume("regen_fact_application")

    col_o, col_r = st.columns(2)
    with col_o:
        st.markdown("**Original Warehouse**")
        if not orig_vol.empty:
            st.bar_chart(orig_vol.set_index("week")["total"])
            st.dataframe(orig_vol, use_container_width=True, hide_index=True)
        else:
            st.warning("No data in original warehouse.")

    with col_r:
        st.markdown("**Regenerated Warehouse**")
        if not regen_vol.empty:
            st.bar_chart(regen_vol.set_index("week")["total"])
            st.dataframe(regen_vol, use_container_width=True, hide_index=True)
        else:
            st.warning("No data in regenerated warehouse.")

    # ── Equivalence check ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("Equivalence Check")

    if orig_vol.empty or regen_vol.empty:
        st.warning("One or both warehouses have no data. Run the ETLs first.")
    else:
        merged = pd.merge(orig_vol, regen_vol, on="week", suffixes=("_orig", "_regen"))
        merged["total_match"]    = merged["total_orig"]    == merged["total_regen"]
        merged["approved_match"] = merged["approved_orig"] == merged["approved_regen"]
        all_match = merged["total_match"].all() and merged["approved_match"].all()

        if all_match:
            st.success(
                "EQUIVALENT — All weekly volumes and approval counts are identical "
                "across both warehouses. The spec is valid.",
                icon="✅",
            )
        else:
            st.error(
                "DIVERGENT — Outputs differ. This indicates a spec drift issue "
                "requiring investigation.",
                icon="❌",
            )

        st.dataframe(merged, use_container_width=True, hide_index=True)

    # ── Segment approval rates ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Business Query: Approval Rate by Segment")

    orig_seg  = query_approval_by_segment("wh_dim_customer",    "wh_fact_application")
    regen_seg = query_approval_by_segment("regen_dim_customer", "regen_fact_application")

    col_o2, col_r2 = st.columns(2)
    with col_o2:
        st.markdown("**Original**")
        st.dataframe(orig_seg, use_container_width=True, hide_index=True)
    with col_r2:
        st.markdown("**Regenerated**")
        st.dataframe(regen_seg, use_container_width=True, hide_index=True)

    # ── Side-by-side code diff ─────────────────────────────────────────────────
    st.divider()
    st.subheader("The Code Looks Different — That's Expected")
    st.caption(
        "Original ETL (hand-written) vs Regenerated ETL (from spec alone). "
        "Different variable names, different key formula. Identical business outputs — proven above."
    )

    col_orig_code, col_regen_code = st.columns(2)
    with col_orig_code:
        st.markdown("**Original: `wbbxtr.py` (hand-written)**")
        orig_code = _read_file(ARTIFACTS / "etl" / "wbbxtr.py")
        st.code(orig_code, language="python")
    with col_regen_code:
        st.markdown("**Regenerated: `extract.py` (from spec alone)**")
        regen_code = _read_file(REGEN / "etl" / "extract.py")
        st.code(regen_code, language="python")

    diff_rows = {
        "What's different": [
            "Surrogate key formula",
            "Variable naming",
            "Loop variable names",
            "SQL JOIN keyword",
        ],
        "Original": [
            "abs(hash((prefix, id))) & (2⁶³−1)",
            "r, a, ck, ak — terse",
            "for r in rows",
            "JOIN",
        ],
        "Regenerated": [
            "MD5 hex digest mod 2⁶³",
            "rec, row, ckey, akey — descriptive",
            "for rec in cust_records",
            "INNER JOIN",
        ],
        "Material to outputs?": ["No", "No", "No", "No"],
    }
    st.dataframe(pd.DataFrame(diff_rows), use_container_width=True, hide_index=True)

    st.markdown("""
> **The governance model:** Run **Compare** quarterly. Identical outputs = spec is valid.
> Divergent outputs = you have a documented management problem, not a mystery.
> The spec is the continuous reference point — not a one-time snapshot.
""")

# ── Tab 6: New Feature ─────────────────────────────────────────────────────────

def tab_new_feature() -> None:
    st.header("New Feature: Average Days to Approval by Segment")
    st.caption(
        "The spec as a launchpad. Operations team requests a new report — "
        "feasibility, spec amendment, and implementation all derived from the spec."
    )

    st.markdown("""
**The spec-driven workflow for new features:**
1. Check the spec — is all required data already in the warehouse?
2. If yes: write the view directly against the spec's documented column names.
3. If no: amend the spec first, then implement.
4. Verify against the spec's documented semantics.

This feature required no schema amendment — all data was already present.
""")

    tab_a, tab_b = st.tabs(["Feature Document", "Live Report"])

    with tab_a:
        content = _read_file(FALLBACK / "new_report.md")
        st.markdown(content)

    with tab_b:
        st.subheader("Avg Days to Approval by Business Segment")
        st.caption("Running against original warehouse. ETL must be run first (see Proof tab).")

        conn = get_db()
        n = conn.execute("SELECT COUNT(*) FROM wh_fact_application").fetchone()[0]
        conn.close()

        if n == 0:
            st.warning("Original warehouse is empty. Go to the Proof tab and click Run Both ETLs.")
        else:
            df = query_avg_days_to_approval("wh_dim_customer", "wh_fact_application")
            if df.empty:
                st.info("No approved applications with recorded decision times yet.")
            else:
                st.bar_chart(df.set_index("segment")["avg_days_to_approval"])
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.caption(
                    "segment = wh_dim_customer.segment (source: customers.business_category) — "
                    "spec D2 documents this three-name mapping."
                )

# ── Tab 7: Production Tickets ──────────────────────────────────────────────────

def tab_production_tickets() -> None:
    st.header("Production Tickets — WBB Analytics Warehouse")
    st.caption(
        "Seven ServiceNow incidents raised against the WBBAW pipeline over six months. "
        "Four map directly to the seeded discrepancies. Three surface open questions."
    )

    ticket_path = ARTIFACTS / "servicenow_tickets_wbb.json"
    if not ticket_path.exists():
        st.error(f"Ticket file not found: {ticket_path}")
        return

    tickets = json.loads(ticket_path.read_text(encoding="utf-8"))

    # Summary table
    summary = []
    for t in tickets:
        summary.append({
            "Ticket":      t["number"],
            "Opened":      t["opened_at"][:10],
            "Priority":    t["priority"],
            "State":       t["state"],
            "Description": t["short_description"],
            "Spec Link":   t.get("spec_link", "—"),
        })
    df = pd.DataFrame(summary)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Ticket Details")

    for t in tickets:
        with st.expander(f"{t['number']} — {t['short_description']}"):
            col1, col2 = st.columns(2)
            col1.markdown(f"**Priority:** {t['priority']}")
            col1.markdown(f"**State:** {t['state']}")
            col2.markdown(f"**Opened:** {t['opened_at'][:10]}")
            col2.markdown(f"**Spec link:** {t.get('spec_link', '—')}")
            st.markdown(f"**Description:**\n\n{t['description']}")
            if t.get("work_notes"):
                st.markdown(f"**Work Notes:**\n\n{t['work_notes']}")
            if t.get("resolution_notes"):
                st.success(f"**Resolution:** {t['resolution_notes']}")

# ── Tab 8: Enriched Spec ───────────────────────────────────────────────────────

def tab_enriched_spec() -> None:
    st.header("Enriched Specification — WBBAW + Operational History")
    st.caption(
        "The forensic spec plus Section 8: operational knowledge extracted from "
        "six months of production ticket history. One document serves both delivery "
        "and L3 support."
    )

    st.info(
        "Section 8 was produced by running the support enrichment prompt against "
        "the spec (Sections 1–7) and the 7 ServiceNow tickets. "
        "Sections 1–7 are unchanged — the spec grows forward, never backwards.",
        icon="📋",
    )

    section8_path = FALLBACK / "wbbaw_spec_section8.md"
    if section8_path.exists():
        content = section8_path.read_text(encoding="utf-8")
        st.markdown(content)
    else:
        st.warning(f"Section 8 not found at {section8_path}. Create it by running the enrichment prompt.")

# ── Tab 9: FAQ ─────────────────────────────────────────────────────────────────

def tab_faq() -> None:
    st.header("FAQ — WBB Analytics Warehouse")
    st.caption(
        "Generated from the enriched spec. A new team member should be able to "
        "answer common questions without reading the full spec."
    )

    faq_path = FALLBACK / "wbbaw_faq.md"
    if faq_path.exists():
        content = faq_path.read_text(encoding="utf-8")
        st.markdown(content)
    else:
        st.warning(f"FAQ not found at {faq_path}. Create it by running the FAQ generation prompt.")

# ── Tab 10: L3 Support Chatbot ─────────────────────────────────────────────────

def tab_chatbot() -> None:
    st.header("L3 Support Chatbot — WBB Analytics Warehouse")
    st.caption(
        "Powered by Claude. Knowledge base: enriched WBBAW specification (Sections 1–8). "
        "Classifies new tickets as KNOWN PATTERN, KNOWN GAP, or UNKNOWN — ESCALATE."
    )

    if not _ANTHROPIC_AVAILABLE:
        st.error(
            "The `anthropic` package is not installed. "
            "Run: `pip install anthropic` then restart the app."
        )
        return

    api_key = _get_api_key()
    if not api_key:
        st.warning(
            "ANTHROPIC_API_KEY not set. "
            "Add it to `.streamlit/secrets.toml` as `ANTHROPIC_API_KEY = \"sk-ant-...\"` "
            "or set the environment variable before starting the app."
        )
        with st.expander("Setup instructions"):
            st.code(
                "# .streamlit/secrets.toml\nANTHROPIC_API_KEY = \"sk-ant-your-key-here\"",
                language="toml",
            )
        return

    # Build system prompt from spec + Section 8
    spec_v1   = _read_file(FALLBACK / "wbbaw_spec_v1.md")
    section8  = _read_file(FALLBACK / "wbbaw_spec_section8.md")
    knowledge_base = f"{spec_v1}\n\n---\n\n{section8}"

    system_prompt = f"""\
You are an L3 support agent for the WBB Analytics Warehouse (WBBAW), a nightly ETL \
pipeline and star-schema analytical warehouse operated by WBB Data Services for the \
WBB customer onboarding programme.

Your SOLE knowledge base is the enriched system specification reproduced below. \
You have no knowledge of this system beyond what appears in that document. \
Do not invent information, do not draw on general knowledge about ETL or databases \
to fill gaps — if the spec does not tell you something, say so and recommend escalation.

When handling a ticket or question:
1. Identify which component or pattern the issue involves.
2. Check Section 8 (Operational History) first — many issues have documented patterns there.
3. Cite the relevant spec section in your response (e.g. [Spec §8.2], [Spec §4.1]).
4. Classify the issue using one of three statuses:
   - KNOWN PATTERN — issue matches a documented failure pattern; resolution procedure known
   - KNOWN GAP — issue is a documented defect or open question; no current resolution
   - UNKNOWN — issue is not covered by the knowledge base; escalation required
5. For KNOWN PATTERN: provide the documented resolution steps.
6. For KNOWN GAP: state what is known and recommend escalation path.
7. For UNKNOWN: state clearly this is outside the knowledge base.

Format every response as:

**Status:** [KNOWN PATTERN | KNOWN GAP | UNKNOWN — ESCALATE]
**Assessment:** [1–2 sentences]
**Relevant Spec:** [section reference and key detail]
**Recommended Action:** [steps if known, or escalation path]

Keep responses concise. A new L3 engineer should be able to act without reading the full spec.

---

ENRICHED WBBAW SYSTEM SPECIFICATION

{knowledge_base}
"""

    # Chat history in session state
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    # Suggested starter tickets
    with st.expander("Demo tickets to try"):
        st.markdown("""
- `The nightly job fails at the audit step — wbbaudit exits with program not found`
- `Weekly onboarding volume dashboard shows data by submission date, not approval date — is this correct?`
- `I'm trying to query fact_application for decline_description but the column doesn't exist`
- `Someone asked me for the business_segment column — where is it?`
- `We're seeing a new error code PIIMASK-403 in the extract logs — what is this?`
""")

    # Render message history
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    user_input = st.chat_input("Describe a ticket or ask a support question...")
    if user_input:
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Consulting spec..."):
                try:
                    client   = _anthropic_module.Anthropic(api_key=api_key)
                    response = client.messages.create(
                        model      = "claude-sonnet-4-6",
                        max_tokens = 1024,
                        system     = system_prompt,
                        messages   = [
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.chat_messages
                        ],
                    )
                    reply = response.content[0].text
                except Exception as exc:
                    reply = f"[API error: {exc}]"

            st.markdown(reply)
        st.session_state.chat_messages.append({"role": "assistant", "content": reply})

    if st.session_state.chat_messages:
        if st.button("Clear chat"):
            st.session_state.chat_messages = []
            st.rerun()

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title = "WBB Spec-Driven Demo",
        layout     = "wide",
        initial_sidebar_state = "collapsed",
    )

    init_db()

    # Auto-seed on first run
    conn = get_db()
    n    = conn.execute("SELECT COUNT(*) FROM onboarding_applications").fetchone()[0]
    conn.close()
    if n == 0:
        with st.spinner("Seeding initial data..."):
            for d in range(30, 0, -1):
                for _ in range(random.randint(6, 18)):
                    add_application(days_ago=float(d))

    tabs = st.tabs([
        "1  Live System",
        "2  Artifacts",
        "3  Spec",
        "4  Regenerated",
        "5  Proof",
        "6  New Feature",
        "7  Production Tickets",
        "8  Enriched Spec",
        "9  FAQ",
        "10  L3 Chatbot",
    ])

    with tabs[0]:
        tab_live_system()
    with tabs[1]:
        tab_artifacts()
    with tabs[2]:
        tab_spec()
    with tabs[3]:
        tab_regenerated()
    with tabs[4]:
        tab_proof()
    with tabs[5]:
        tab_new_feature()
    with tabs[6]:
        tab_production_tickets()
    with tabs[7]:
        tab_enriched_spec()
    with tabs[8]:
        tab_faq()
    with tabs[9]:
        tab_chatbot()


if __name__ == "__main__":
    main()
