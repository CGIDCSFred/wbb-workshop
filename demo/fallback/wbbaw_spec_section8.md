### Section 8: Operational History and Known Failure Patterns

This section was produced by cross-referencing eight ServiceNow incidents raised against the WBBAW pipeline between 2026-02-03 and 2026-04-29 against the forensic specification (Sections 1–7). The incidents cover configuration items WBBAW-BATCH, WBBAW-REPORT, and WBBAW-DATA. Five map directly to the discrepancies catalogued in Section 6 (D1–D5); the remainder surface open questions or were closed by analyst guidance. The most recent incident (INC-WBB-0018) is an active P1 defect mitigated by an interim workaround. Sections 1–7 are carried forward from the forensic specification without modification.

---

#### 8.1 Confirmed System Behaviours

**B1 — Extract carries decline_description to staging**
The extract step correctly joins `wbb.decline_reason` and aliases `reason_description` as `decline_description`. This field is present in every staged JSONL record for declined applications. Confirmed by L3 inspection of staging file samples during INC-WBB-0013 investigation. [Spec §4.1, extract query decline_reason LEFT JOIN; INC-WBB-0013 work notes]

**B2 — submitted_date_key is the operative date for weekly volume reporting**
The vw_weekly_onboarding_volume view counts by submitted_date_key (submission date), not approved_date_key. This is documented as an as-built deviation from BRD §5 in the target schema DDL. Confirmed in production by count comparison (Operations team, INC-WBB-0012): 342 dashboard applications vs 289 platform approvals for week of 2026-02-09, explained entirely by the submission-vs-approval date difference. [Spec §6 D1; INC-WBB-0012]

**B3 — Load commits in a single transaction**
The load step issues one commit after all dimension and fact rows are processed. COMMIT_INTERVAL=5000 in job_config.yaml is not read by wbbldr.py. At current nightly volumes (8,000–12,000 rows) this is operationally acceptable. [Spec §7 Q5; INC-WBB-0015]

**B4 — business_category maps to segment in warehouse**
The source column `wbb.customer.business_category` maps to `wbbaw.dim_customer.segment` at load time. Confirmed by analyst incident (INC-WBB-0014): queries using `business_segment` (BRD name) or `business_category` (source name) against the warehouse fail; only `segment` is the correct warehouse column name. [Spec §6 D2; INC-WBB-0014]

**B5 — Surrogate keys are computed in application code and depend on the runtime**
The ETL derives dimension and fact surrogate keys with Python's salted `hash()` (`wbbldr.py`), not via the database. Key stability across deployments is a function of the runtime configuration (`PYTHONHASHSEED`), not the schema. Confirmed by INC-WBB-0018: the 2026-04-28 platform refresh changed the effective seed and broke `fact_application` → `dim_customer` referential integrity for returning customers. [Spec §4.4, §5.10, §6 D5; INC-WBB-0018]

---

#### 8.2 Known Failure Patterns

**Pattern 1 — Audit step abend: wbbaudit program not found**
- **Affected component:** WBBAW-BATCH, job_config.yaml audit step, `program: wbbaudit`
- **Observed symptom:** Nightly job completes extract and load successfully, then fails at audit step with "program not found" error. On-call paged. Downstream job wbb-reporting-refresh not triggered. Morning reports unavailable.
- **Root cause:** wbbaudit.py was never implemented. WBB-AW-014 (audit step implementation) was in progress at artifact freeze and was never completed or deployed.
- **Current status:** Workaround in place (CHG-WBB-0029). DEF-WBB-0041 open.
- **Resolution procedure for new L3 engineer:**
  1. Confirm job runner log shows audit step failure with "program not found".
  2. Confirm wbbaudit.py is absent from deployment: `ls /opt/wbbaw/bin/wbbaudit`.
  3. The workaround (CHG-WBB-0029) should already route load success directly to notify_success, bypassing the audit step. Verify job_config.yaml has the workaround applied.
  4. If the job has failed and reports are blocked, manually trigger `wbb-reporting-refresh`.
  5. Escalate to DEV referencing DEF-WBB-0041 if workaround is not in place.
- **Ticket provenance:** [INC-WBB-0011]

**Pattern 2 — Slack notifications absent**
- **Affected component:** WBBAW-BATCH, `program: wbbnotify`, #wbb-data-ops channel
- **Observed symptom:** #wbb-data-ops receives no ETL success or failure alerts. The channel has been silent since the audit-step workaround was applied (2026-02-03).
- **Root cause:** wbbnotify.py is not implemented. The terminal steps (notify_success, notify_failure) call a program that does not exist in the deployment. The job runner was configured to ignore terminal step failures, so no error surfaces in the job log.
- **Current status:** Unresolved. DEF-WBB-0055 open. Manual dashboard monitoring in place.
- **Resolution procedure:** Monitor job runner dashboard manually. Do not rely on Slack channel for ETL alerts until DEF-WBB-0055 is resolved.
- **Ticket provenance:** [INC-WBB-0017; related: INC-WBB-0011, DEF-WBB-0041]

**Pattern 3 — Post-upgrade foreign-key violations on fact_application (surrogate-key drift)**
- **Affected component:** WBBAW-BATCH, `wbbldr.py` surrogate-key generation; runtime environment
- **Observed symptom:** The night after a runtime / base-image change, the load step aborts with foreign-key violations — `fact_application.customer_key` not present in `dim_customer` — for returning customers. Applications from new customers load normally. Extract and staging are unaffected.
- **Root cause:** Surrogate keys use `abs(hash(('cust', customer_id)))`; the string element makes the hash salted by `PYTHONHASHSEED`. The legacy base image pinned `PYTHONHASHSEED=0`; the 2026-04-28 standardised image (CHG-WBB-0058) dropped it, so keys diverge from their stored values. The dimension upsert keeps the old `customer_key` (ON CONFLICT does not update it) while the fact load writes the new one.
- **Current status:** Mitigated. Interim workaround applied (re-pin `PYTHONHASHSEED=0` + full reload). DEF-WBB-0060 open for the durable fix.
- **Resolution procedure for new L3 engineer:**
  1. Confirm the load log shows FK violations on `fact_application_customer_key_fkey`, affecting returning customers only.
  2. Check `runtime_environment.md` / recent change records for a base-image or interpreter change in the preceding 24 hours.
  3. Confirm `PYTHONHASHSEED` is unset in the current job environment (`env | grep PYTHONHASHSEED`).
  4. Re-pin `PYTHONHASHSEED=0` in the wbbaw-batch job environment and re-run with `ETL_MODE=FULL` to rebuild keys consistently.
  5. Escalate to DEV referencing DEF-WBB-0060 for a runtime-independent key derivation.
- **Ticket provenance:** [INC-WBB-0018; DEF-WBB-0060]

---

#### 8.3 Active Workarounds

**Workaround 1 — Audit step bypass (CHG-WBB-0029)**
- **Component affected:** job_config.yaml, audit step
- **What the workaround does:** The audit step is commented out in the production job_config.yaml. The load step `on_success` routes directly to notify_success, bypassing the non-existent wbbaudit program.
- **Change record:** CHG-WBB-0029
- **Risk accepted:** No automated record count comparison between source and warehouse. The `COMPARE_COUNTS` and `ALERT_ON_VARIANCE` parameters are not enforced. A load that silently drops records will not be detected by the pipeline.
- **Resolution dependency:** Implementation of wbbaudit.py (DEF-WBB-0041).
- **Ticket provenance:** [INC-WBB-0011]

**Workaround 2 — PYTHONHASHSEED re-pin + full reload (INC-WBB-0018)**
- **Component affected:** wbbaw-batch job environment; dimension/fact surrogate keys
- **What the workaround does:** Restores `PYTHONHASHSEED=0` in the job environment (matching the legacy image) and triggers a full reload (`ETL_MODE=FULL`) so all dimension and fact keys are recomputed consistently under the pinned seed.
- **Change record:** applied 2026-04-29 (follow-up to CHG-WBB-0058)
- **Risk accepted:** The ETL still depends on a salted hash for key stability. Any future runtime change that does not preserve `PYTHONHASHSEED=0` will reintroduce the failure. The pin is a mitigation, not a fix.
- **Resolution dependency:** Runtime-independent surrogate-key derivation (DEF-WBB-0060).
- **Ticket provenance:** [INC-WBB-0018]

---

#### 8.4 Unresolved Defects

**DEF-WBB-0041 — wbbaudit program not implemented**
- **Defect summary:** The post-load audit step program (wbbaudit) referenced in job_config.yaml has never been implemented.
- **Spec claim contradicted:** Spec §5.6 documents the audit step as configured with COMPARE_COUNTS=true and ALERT_ON_VARIANCE=5. No code supports this.
- **Evidence:** INC-WBB-0011 confirmed absence of wbbaudit.py. User story WBB-AW-014 was in progress at artifact freeze and was not completed.
- **Current state:** Workaround CHG-WBB-0029 bypasses the step. Count validation is not performed.

**DEF-WBB-0048 — decline_description not persisted to warehouse (WBB-AW-011 incomplete)**
- **Defect summary:** User story WBB-AW-011 is marked Done but the decline_description field is never written to fact_application. The BRD §6 "top decline reasons" report is undeliverable.
- **Spec claim contradicted:** Spec §6 D3 documents this discrepancy. Acceptance criterion "[x] fact_application carries a human-readable decline reason" is falsely marked complete.
- **Evidence:** INC-WBB-0013 traced the data flow: field present in staging, absent from INSERT tuple in wbbldr.py, no column in target_schema.sql.
- **Current state:** No workaround. The BRD §6 report cannot be produced from the current warehouse schema. A schema amendment and load code change are required.

**DEF-WBB-0055 — wbbnotify program not implemented**
- **Defect summary:** The Slack notification program (wbbnotify) referenced in job_config.yaml has never been implemented.
- **Spec claim contradicted:** Spec §5.7 documents wbbnotify as sending alerts to #wbb-data-ops on success and failure. Spec §7 Q8 records this as an open question.
- **Evidence:** INC-WBB-0017 confirmed absence of wbbnotify.py. Terminal steps fail silently.
- **Current state:** Manual monitoring of job runner dashboard. No automated Slack alerts.

**DEF-WBB-0051 — COMMIT_INTERVAL parameter unimplemented**
- **Defect summary:** COMMIT_INTERVAL=5000 in job_config.yaml is not read by wbbldr.py.
- **Spec claim contradicted:** Spec §7 Q5 records this as an open question.
- **Evidence:** INC-WBB-0015 confirmed no batched commit loop in load code.
- **Current state:** No current operational impact at nightly volumes of 8,000–12,000 rows. Risk increases if volumes grow substantially.

**DEF-WBB-0060 — Surrogate keys depend on PYTHONHASHSEED (runtime-coupled keys)**
- **Defect summary:** Application-level surrogate keys (`wbbldr.py`) are derived from Python's salted `hash()` and are only stable while `PYTHONHASHSEED` is pinned. They are coupled to runtime configuration rather than to the data.
- **Spec claim contradicted:** Spec §4.4 / §7 Q4 flagged this as an unassessed risk; §6 D5 documents its realisation. The keys are not, in fact, stable across platform changes.
- **Evidence:** INC-WBB-0018 — FK violations after the 2026-04-28 platform refresh; root cause traced to the dropped `PYTHONHASHSEED=0` override.
- **Current state:** Interim mitigation in place (Workaround 2). Durable fix (deterministic, runtime-independent key derivation) not yet implemented.

---

#### 8.5 Operational Guidance Confirmed

**G1 — Correct warehouse column name for business classification**
Use `wbbaw.dim_customer.segment` in all warehouse queries. Do not use `business_segment` (BRD name) or `business_category` (source name) — both will return column-not-found errors against the warehouse. [Spec §6 D2; INC-WBB-0014]

**G2 — Weekly volume dashboard counts by submission date**
The vw_weekly_onboarding_volume view counts by submission date, not approval date. When comparing dashboard figures to operational platform figures, expect a systematic offset equal to the lag between submission and approval (typically 2–14 days). This is a known documented deviation from BRD §5, not a data quality issue. [Spec §6 D1; INC-WBB-0012]

**G3 — wbbaudit bypass is permanently in place until DEF-WBB-0041 is resolved**
The audit step is bypassed by CHG-WBB-0029. Count variances between source and warehouse will not be automatically detected. Manual spot checks against source counts are advisable after any full reload. [INC-WBB-0011]

**G4 — Application-level keys are not stable across runtime changes**
Surrogate keys for `dim_customer` / `fact_application` are computed by Python's salted `hash()` and only stay stable while `PYTHONHASHSEED` is pinned in the job environment. Before any runtime, base-image, or interpreter change, confirm `PYTHONHASHSEED=0` is preserved, or plan a full reload immediately after. Treat a base-image change as a data-integrity change, not just an infrastructure one. [Spec §6 D5, §5.10; INC-WBB-0018]

---

*Section 8 added from operational history — six months of production incidents (2026-02-03 to 2026-04-29), eight incidents analysed, configuration items WBBAW-BATCH, WBBAW-REPORT, WBBAW-DATA.*

---

**New Open Questions (added from operational history)**

The following items are added to Section 7 based on unresolved defects identified from ticket analysis:

**Q11 — When will wbbaudit and wbbnotify be implemented?** [Added from operational history, INC-WBB-0011, INC-WBB-0017, DEF-WBB-0041, DEF-WBB-0055] The two missing programs represent a gap between the designed pipeline (four steps) and the running pipeline (two steps plus workaround). Not specified whether a sprint has been planned to close these defects together.

**Q12 — What is the remediation plan for the decline_description gap?** [Added from operational history, INC-WBB-0013, DEF-WBB-0048] The BRD §6 report is currently undeliverable. Remediation requires both a fact_application schema amendment and a wbbldr.py load code change. Not specified whether this is planned, or whether the business will accept the current gap.

**Q13 — What is the plan to update vw_weekly_onboarding_volume to use approved_date_key?** [Added from operational history, INC-WBB-0012, WBB-AW-020] The approved_dt column was backfilled in the source schema (2026-01-08). The ETL populates approved_date_key on the fact. The view has not been updated. Backlog item WBB-AW-020 exists but has no sprint assignment.

**Q14 — When will surrogate-key generation be made runtime-independent?** [Added from operational history, INC-WBB-0018, DEF-WBB-0060] The interim mitigation re-pins `PYTHONHASHSEED=0`, but the keys remain coupled to runtime configuration rather than to the data. Not specified whether a deterministic key derivation (e.g. a stable hash over the integer natural key, or a database-generated surrogate) is planned, or whether the environment pin is considered a sufficient long-term control.
