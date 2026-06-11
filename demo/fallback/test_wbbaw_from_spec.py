"""
WBBAW conformance suite — generated from wbbaw_spec_v1.md (prompt 04).

Every test cites the spec section it verifies. The CHARACTERIZATION tests assert
the system's *as-built* behaviour, including the four documented discrepancies
(Spec §6 D1–D4): a "fix" to any of them turns these tests red, which is exactly
the drift signal we want. Open questions (Spec §7) appear as skipped tests so the
gaps show up as missing coverage rather than silent absence.

Run:  pytest test_wbbaw_from_spec.py -v
"""
import datetime
import sqlite3

import pytest

DB = "wbb_demo.db"


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def iso_week(dt_str: str) -> str:
    d = datetime.date.fromisoformat(dt_str[:10])
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def eligible(c):
    return c.execute(
        """SELECT a.id, a.status, a.submitted_at, a.decided_at
           FROM onboarding_applications a JOIN customers cu ON cu.id = a.customer_id
           WHERE cu.is_test = 0 AND a.status NOT IN ('ABANDONED')"""
    ).fetchall()


# ── Transformation rules — [Spec §4] ────────────────────────────────────────────

def test_fact_grain_one_row_per_eligible_application():
    # [Spec §4] Grain: one fact row per non-test, non-abandoned application.
    c = conn()
    facts = c.execute("SELECT COUNT(*) FROM wh_fact_application").fetchone()[0]
    assert facts == len(eligible(c))


def test_is_approved_iff_status_approved():
    # [Spec §4] is_approved is set when, and only when, status = APPROVED.
    c = conn()
    src = sum(1 for r in eligible(c) if r["status"] == "APPROVED")
    fact = c.execute("SELECT COALESCE(SUM(is_approved),0) FROM wh_fact_application").fetchone()[0]
    assert fact == src


def test_test_and_abandoned_excluded():
    # [Spec §4] Test customers (is_test=1) and ABANDONED applications are excluded.
    c = conn()
    fact_ids = {r[0] for r in c.execute("SELECT application_id FROM wh_fact_application")}
    elig_ids = {r["id"] for r in eligible(c)}
    assert fact_ids <= elig_ids


def test_decision_days_present_for_decided():
    # [Spec §4] decision_days = decided_at - submitted_at, for decided applications.
    c = conn()
    bad = c.execute(
        """SELECT COUNT(*) FROM wh_fact_application f
           JOIN onboarding_applications a ON a.id = f.application_id
           WHERE a.decided_at IS NOT NULL AND f.decision_days IS NULL"""
    ).fetchone()[0]
    assert bad == 0


# ── Characterization — pins the four as-built discrepancies [Spec §6] ────────────

def test_D1_fact_keyed_on_submission_not_approval():
    # [Spec §6 D1] BRD §5 says count by approval date; the ETL keys on SUBMISSION.
    # We assert the as-built behaviour: submitted_year_week == ISO week of submitted_at.
    c = conn()
    rows = c.execute(
        """SELECT f.submitted_year_week w, a.submitted_at s
           FROM wh_fact_application f JOIN onboarding_applications a ON a.id = f.application_id"""
    ).fetchall()
    assert all(r["w"] == iso_week(r["s"]) for r in rows)


def test_D2_segment_rename_chain_intact():
    # [Spec §6 D2] business_segment (BRD) / business_category (source) / segment (warehouse).
    c = conn()
    src_cols = {r["name"] for r in c.execute("PRAGMA table_info(customers)")}
    dim_cols = {r["name"] for r in c.execute("PRAGMA table_info(wh_dim_customer)")}
    assert "business_category" in src_cols and "segment" in dim_cols
    mismatched = c.execute(
        """SELECT COUNT(*) FROM wh_dim_customer d JOIN customers cu ON cu.id = d.customer_id
           WHERE d.segment <> cu.business_category"""
    ).fetchone()[0]
    assert mismatched == 0


def test_D3_decline_reason_not_persisted():
    # [Spec §6 D3] WBB-AW-011 marked Done; extract carries decline_description,
    # but the load never persists it and the fact has no column for it.
    c = conn()
    cols = {r["name"].lower() for r in c.execute("PRAGMA table_info(wh_fact_application)")}
    # Allow the legitimate is_declined flag; assert no decline reason/description column.
    assert not any((("decline" in x and x != "is_declined") or "reason" in x or "description" in x) for x in cols)


def test_D4_audit_program_orphaned():
    # [Spec §6 D4] job_config.yaml runs `wbbaudit`; no such program exists.
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]   # repo root
    job_config = (root / "artifacts" / "job_config.yaml").read_text(encoding="utf-8")
    assert "wbbaudit" in job_config
    assert not list(root.rglob("wbbaudit.py"))


# ── Equivalence — original ≡ regenerated [Spec §4 / governance] ──────────────────

def _weekly_volume(c, fact):
    return c.execute(
        f"SELECT submitted_year_week, COUNT(*), COALESCE(SUM(is_approved),0) "
        f"FROM {fact} GROUP BY 1 ORDER BY 1"
    ).fetchall()


def test_equivalence_weekly_volume():
    # [Governance] Different code, identical business answers.
    c = conn()
    assert [tuple(r) for r in _weekly_volume(c, "wh_fact_application")] == \
           [tuple(r) for r in _weekly_volume(c, "regen_fact_application")]


# ── Open questions — [Spec §7] surface as missing coverage, not silence ──────────

@pytest.mark.skip(reason="Spec §7: data-retention period unspecified in available artifacts")
def test_retention_policy():
    ...


@pytest.mark.skip(reason="Spec §7: late-arriving / amended applications behaviour unspecified")
def test_late_arriving_applications():
    ...
