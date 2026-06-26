# WBB Analytics Warehouse — Frequently Asked Questions

Generated from the enriched WBBAW system specification (Sections 1–8).
A new team member should be able to answer these questions without reading the full spec.

---

## Pipeline & Operations

**Q: When does the nightly ETL run, and what is the SLA?**

The pipeline runs daily at 01:00 UTC. It must complete before 06:00 UTC to support morning reporting. The predecessor job is `wbb-operational-backup`; the successor is `wbb-reporting-refresh`. [Spec §5.1]

**Q: What are the four pipeline steps?**

Extract (`wbbxtr`), Load (`wbbldr`), Audit (`wbbaudit`), and Notify (`wbbnotify`). Note: the audit and notify programs are not currently implemented. The audit step is bypassed by workaround CHG-WBB-0029. Slack notifications are not functioning. [Spec §5.2, §8.2 Pattern 1, §8.2 Pattern 2]

**Q: The job failed at the audit step — what do I do?**

This is a known production pattern (INC-WBB-0011). The workaround CHG-WBB-0029 should already have the audit step commented out. If the job is failing at audit, confirm the workaround is applied in job_config.yaml. If reports are blocked, manually trigger `wbb-reporting-refresh`. Escalate to DEV referencing DEF-WBB-0041. [Spec §8.2 Pattern 1]

**Q: Why is #wbb-data-ops not receiving ETL alerts?**

The `wbbnotify` program is not implemented. Terminal steps (notify_success, notify_failure) call a program that does not exist. Monitor the job runner dashboard manually until DEF-WBB-0055 is resolved. [Spec §8.2 Pattern 2, §5.7]

**Q: What does RC_WARN (exit code 4) mean?**

The extract completed successfully but encountered at least one decline_reason_code that could not be resolved against the decline_reason reference table. This indicates a pre-November-2025 code not in the reference table. The load step still proceeds; the job runner's `on_warning: load` routing handles this. [Spec §4.1, §5.9]

**Q: How do I restart the pipeline after a failure?**

Set `RESTART_FROM=load` to restart from the load step (reuses the existing staging file). Set `RESTART_FROM=extract` to re-run the full extract and load. For a complete historical reload, set `ETL_MODE=FULL`. [Spec §5.3]

**Q: The nightly load started failing with foreign-key violations on fact_application right after a platform upgrade — what happened?**

This is discrepancy D5 (DEF-WBB-0060), first seen as INC-WBB-0018 after the 2026-04-28 platform refresh. The surrogate keys are computed in application code with Python's salted `hash()`, so they only stay stable while `PYTHONHASHSEED` is pinned. The legacy base image pinned it to `0`; the standardised image dropped it, so keys for existing customers changed and no longer matched the rows already in `dim_customer`. Returning customers fail the FK; new customers load fine. Interim fix: re-pin `PYTHONHASHSEED=0` and run a full reload (`ETL_MODE=FULL`). Treat any base-image or interpreter change as a data-integrity change, not just infrastructure. [Spec §6 D5, §5.10, §8.2 Pattern 3, §8.5 G4]

---

## Data & Schema

**Q: I'm querying dim_customer for the business type column — which column name do I use?**

Use `segment` in warehouse queries. The BRD calls this field `business_segment`; the source database uses `business_category`; the warehouse uses `segment` (conformed naming convention). Using `business_segment` or `business_category` against the warehouse will return a column-not-found error. [Spec §6 D2, §8.5 G1]

**Q: Why does the weekly onboarding volume dashboard show different numbers than the operational platform?**

The dashboard (`vw_weekly_onboarding_volume`) counts applications by submission date, not approval date. BRD §5 specifies that volume metrics should be counted by approval date, but the ETL was built before `approved_dt` was available in the source schema. The deviation is documented and acknowledged. Expect an offset equal to the lag between submission and approval (typically 2–14 days). This is not a data quality issue. [Spec §6 D1, §8.1 B2, §8.5 G2]

**Q: I'm trying to build the "top decline reasons" report from BRD §6. Where is the decline_description column on fact_application?**

There is no `decline_description` column on `fact_application`. This is defect DEF-WBB-0048. User story WBB-AW-011 was closed as Done but the load step never persisted the field. The extract carries `decline_description` to the staging file; the load drops it silently. The BRD §6 report is currently undeliverable. No workaround exists. [Spec §6 D3, §8.4 DEF-WBB-0048]

**Q: dim_customer.first_product_type is NULL for all customers — is this correct?**

Yes, currently. The nightly ETL explicitly sets `first_product_type` to NULL for all upserts with a code comment deferring population to "a separate job". That job has not been implemented. The column will remain NULL until it is. [Spec §7 Q9, §8 INC-WBB-0016]

**Q: What is the COMMIT_INTERVAL=5000 parameter in job_config.yaml?**

It is not implemented. `wbbldr.py` reads it from config but issues a single commit after all rows are loaded. At current nightly volumes (8,000–12,000 rows) there is no operational impact. [Spec §7 Q5, §8.1 B3]

---

## Column Mapping

**Q: What are all the names for the business classification field?**

Three names, one concept:
- `business_segment` — BRD (§3.1)
- `business_category` — source database (`wbb.customer`)
- `segment` — warehouse (`wbbaw.dim_customer`) — **use this for warehouse queries**

[Spec §6 D2]

**Q: How is the surrogate key for dim_customer generated?**

Using Python's built-in `hash()` function: `abs(hash(('cust', customer_id))) & ((1 << 63) - 1)`. Because the hash input is a tuple containing a string, CPython salts it per process via `PYTHONHASHSEED`, so the key is only stable while that seed is pinned — it is **not** guaranteed stable across Python version upgrades or platform migrations. This risk was realised in production by the 2026-04-28 platform refresh (discrepancy D5 / INC-WBB-0018). [Spec §4.4, §6 D5]

**Q: What does days_to_decision measure?**

Calendar days between `reviewed_dt` (the decision timestamp) and `submitted_dt` (the submission timestamp) in the source. For approved applications, `reviewed_dt` equals `approved_dt` after the 2026-01-08 source schema backfill. The field is NULL if no decision has been recorded. [Spec §4.3]

---

## Reporting Views

**Q: What are the two standard reporting views?**

- `vw_weekly_onboarding_volume` — counts submitted and approved applications by ISO week (by submission date — see D1 caveat).
- `vw_approval_rate_by_segment` — calculates approval rate per customer segment.

Both join from `fact_application` through `dim_customer`. [Spec §3, target schema]

**Q: Can I run the "top decline reasons" report against the current warehouse?**

No. The `decline_description` column was never loaded into `fact_application`. This is an open defect (DEF-WBB-0048). To get decline reason data, you must query the source database (`wbb.decline_reason` joined to `wbb.onboarding_application`) directly. [Spec §6 D3, §8.4]

---

## Source System

**Q: What applications are excluded from the ETL?**

Two exclusion rules at extract time:
1. Test accounts: `c.is_test = FALSE`
2. Abandoned applications: `a.status <> 'ABANDONED'`

DEMO accounts (`customer_type = 'DEMO'`) are not excluded in v1. This is a known v2 backlog item (WBB-AW-019). [Spec §4.1, §5.4]

**Q: What are the valid values for application status?**

`SUBMITTED`, `IN_REVIEW`, `APPROVED`, `DECLINED`, `ABANDONED`. ABANDONED applications are excluded by the ETL and do not appear in the warehouse. [Spec §2, onboarding_application table]

---

*This FAQ was generated from the enriched WBBAW specification (Sections 1–8). For issues not answered here, consult the full spec or escalate to DEV.*
