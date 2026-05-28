# WBB Analytics Warehouse — Forensic Specification

**Specification version:** 1.0  
**Produced by:** Forensic reverse engineering of artifact bundle (BRD v1.1, source schema, target schema, user stories export, job_config.yaml, wbbxtr.py, wbbldr.py, wbb_common.py)  
**Artifact bundle versions:** WBB-BRD-AW-001 v1.1 (15 Jan 2026), source schema last modified 2026-01-08, target schema last modified 2026-01-20, user stories export dated 28 Jan 2026, job_config.yaml last updated 2026-01-20, ETL code last changed 2026-01-20  
**Analyst note:** This document records what the artifacts say, not what any individual believed was intended. Where the artifacts disagree, both positions are recorded and the discrepancy is catalogued in Section 6. Where the artifacts are silent, the gap is named in Section 7.

---

### 1. System Overview

The WBB Analytics Warehouse (WBBAW) is a nightly-refresh reporting data warehouse for the WBB customer onboarding programme. It consolidates data from the WBB operational platform — a PostgreSQL operational database holding the full lifecycle of business customer applications — into a star schema model optimised for trending, segmentation, and funnel analysis. The warehouse serves three internal teams: Customer Growth, Operations, and Finance. Customer-facing reporting and real-time access are explicitly out of scope [BRD §2.2].

The system consists of three distinct layers. First, a source operational database (schema `wbb`, PostgreSQL 14+) holding the customer, application, product, and decline reason records produced by the WBB onboarding platform [source_schema.sql, header]. Second, a staging file (`/tmp/wbbaw_stage.jsonl` by default, configurable via `STAGE_PATH`) that carries extracted records between the extract and load steps in JSONL format [wbb_common.py, `staging_path`]. Third, a target analytical database (schema `wbbaw`, PostgreSQL 14+) holding the star schema fact and dimension tables, plus two reporting views [target_schema.sql, header].

The pipeline runs nightly at 01:00 UTC, coordinated by a job runner that reads `job_config.yaml`. The job must complete before 06:00 UTC to support morning reporting [BRD §7; job_config.yaml, header comment]. The pipeline has four steps: extract (program `wbbxtr`), load (program `wbbldr`), audit (program `wbbaudit`), and notification (program `wbbnotify`) [job_config.yaml, `steps`].

The warehouse was built in five sprints between November 2025 and January 2026. Seven user stories were delivered and closed. Two stories — WBB-AW-013 (historical validation) and WBB-AW-014 (audit step and Slack notification implementation) — were in progress at the time of the user story export [user_stories_export.md, Notes on this export].

---

### 2. Source System

The source is the WBB operational database (`wbb` schema, PostgreSQL 14+), owned by WBB Platform Engineering and initially deployed 2025-10-15 [source_schema.sql, header]. The ETL pipeline reads from this database using a connection string injected from a secrets manager via the environment variable `WBB_SOURCE_DSN` [wbb_common.py, `source_connection`; job_config.yaml, `environment`]. The pipeline opens a read-only session against the source [wbb_common.py, `conn.set_session(readonly=True)`].

The source schema comprises five tables relevant to the warehouse.

**`wbb.customer`** holds the business entity applying for WBB services. Key columns are: `customer_id` (integer primary key, serial), `company_name` (varchar, not null), `business_category` (varchar, free-text, not validated against a controlled vocabulary), `company_size` (varchar, values MICRO / SMALL / MEDIUM / LARGE), `is_test` (boolean, default false, marks QA test accounts), and `customer_type` (varchar, values STANDARD / EMPLOYEE / TEST / DEMO) [source_schema.sql, `customer` table]. The schema comment explicitly warns that `business_category` is entered by the applicant and may carry unexpected values; downstream consumers must handle these gracefully [source_schema.sql, customer table note]. A separate `customer_type = 'DEMO'` population exists for sales team demonstration accounts; these have `is_test = FALSE` by design [source_schema.sql, customer table comment].

**`wbb.onboarding_application`** holds one row per application. Key columns are: `application_id` (integer primary key, serial), `customer_id` (foreign key to customer), `submitted_dt` (timestamp, not null), `status` (varchar, values SUBMITTED / IN_REVIEW / APPROVED / DECLINED / ABANDONED), `reviewed_dt` (timestamp, populated when status moves to APPROVED or DECLINED), `approved_dt` (timestamp, populated when status = APPROVED — added to the schema 2026-01-08, with a backfill run that set `approved_dt` = `reviewed_dt` for pre-existing approved records), and `decline_reason_code` (varchar, foreign key to `decline_reason`, null for non-declined applications) [source_schema.sql, `onboarding_application` table].

**`wbb.banking_product`** is a reference table of banking products. Key columns are: `product_id`, `product_code`, `product_name`, `product_type` (values ACCOUNT / PAYROLL / WIRE / LENDING), and `is_active` (boolean) [source_schema.sql, `banking_product` table]. Seven products are seeded: two account products (CHQ001, SAV001), one payroll product (PAY001), two wire products (WIR001, WIR002), and two lending products (LND001, LND002) [source_schema.sql, seed inserts].

**`wbb.customer_product`** records which products have been activated for each customer, with a foreign key back to the originating application [source_schema.sql, `customer_product` table]. The ETL extract does not currently join to this table; the warehouse does not currently populate the product dimension from activations [wbbxtr.py, `EXTRACT_QUERY` — no join to `customer_product`].

**`wbb.decline_reason`** is a reference table added November 2025 mapping `reason_code` to `reason_description` and `category` [source_schema.sql, `decline_reason` table]. Eleven reason codes are seeded across five categories: CREDIT_RISK (CR001–CR003), INCOMPLETE_DOCS (ID001–ID003), FRAUD_INDICATOR (FR001–FR002), DUPLICATE (DU001), and OTHER (OT001–OT002) [source_schema.sql, decline_reason inserts]. The schema notes that applications declined before November 2025 may have `decline_reason_code` values not present in this table; downstream consumers must handle missing lookups gracefully [source_schema.sql, decline_reason table note].

---

### 3. Target System

The target is the WBBAW warehouse (`wbbaw` schema, PostgreSQL 14+), owned by WBB Data Services. The target database is populated by the ETL and read-only to the reporting layer. The connection string is injected via `WBB_TARGET_DSN` [job_config.yaml, `environment`; wbb_common.py, `target_connection`].

The schema is a star schema with one fact table and three conformed dimensions [target_schema.sql, header]. All dimensions use Type 1 (overwrite) SCD behaviour, per BRD §4.3 [target_schema.sql, dim_customer comment; target_schema.sql, header comment].

**`wbbaw.dim_date`** is a standard date dimension pre-populated for the window 2025-10-01 through 2030-12-31. It is not written by the nightly ETL; it is maintained by a separate quarterly job [target_schema.sql, dim_date comment]. The surrogate key is an integer in YYYYMMDD format (`date_key`). Useful columns include `iso_year_week` (formatted 'YYYY-Www') and `is_business_day` [target_schema.sql, `dim_date` DDL].

**`wbbaw.dim_customer`** holds one row per customer. The surrogate key `customer_key` is a 63-bit integer derived deterministically from a hash of `('cust', customer_id)` [wbbldr.py, `customer_key` function]. The natural key `customer_id` carries a UNIQUE constraint and is the upsert conflict target [target_schema.sql, dim_customer DDL; wbbldr.py, `upsert_dim_customer`]. The column `segment` maps to `wbb.customer.business_category`; the column name was changed in the warehouse to follow conformed naming conventions [target_schema.sql, dim_customer comment; wbbldr.py, `upsert_dim_customer`, comment "Source business_category → warehouse segment"]. The column `first_product_type` was added 2026-01-20 and is populated by a separate job, not by the nightly ETL (set to NULL during the nightly load) [target_schema.sql, dim_customer DDL; wbbldr.py, `upsert_dim_customer`, comment "first_product_type: populated by a separate job"].

**`wbbaw.dim_product`** holds one row per banking product. An "Unknown Product" member is seeded at `product_key = -1` to serve as a default for unresolvable product references [target_schema.sql, dim_product DDL and seed insert]. The nightly ETL does not upsert `dim_product`; the load code in `wbbldr.py` contains no function for this dimension. The product dimension is therefore not refreshed nightly. Not specified in available artifacts how or when `dim_product` is initially loaded with the live product catalogue beyond the static seed values in the schema DDL.

**`wbbaw.fact_application`** is the central fact, one row per application, with surrogate key `application_key` and natural key `application_id` (UNIQUE) as the upsert conflict target [target_schema.sql, fact_application DDL; wbbldr.py, `load_fact`]. Key columns: `customer_key` (FK to dim_customer), `submitted_date_key` (FK to dim_date, NOT NULL), `approved_date_key` (FK to dim_date, nullable — null if not approved), `submitted_timestamp`, `approved_timestamp`, `status`, `is_approved` (boolean, derived), `is_declined` (boolean, derived), `days_to_decision` (integer, null if decision not yet made), and `etl_load_dt` [target_schema.sql, fact_application DDL]. The fact table carries no `decline_description` column [target_schema.sql, fact_application DDL; fact_application header comment explicitly notes: "Note: there is no decline_description column on this fact."].

Two reporting views are defined. **`wbbaw.vw_weekly_onboarding_volume`** counts applications submitted and approved per ISO week, joining on `submitted_date_key` [target_schema.sql, view DDL]. **`wbbaw.vw_approval_rate_by_segment`** calculates approval rate per customer segment, joining fact to dim_customer on `customer_key` [target_schema.sql, view DDL].

---

### 4. Transformation Rules

**4.1 Extract rules (wbbxtr)**

The extract executes a parameterised SQL query against the source database. In INCREMENTAL mode it filters to `a.submitted_dt::date = %(run_date)s::date` (the run date, defaulting to today's UTC date). In FULL mode it filters to `a.submitted_dt >= '2025-10-01'` (programme start) with no upper bound [wbbxtr.py, `EXTRACT_QUERY` and `EXTRACT_QUERY_FULL`].

The extract query joins `wbb.onboarding_application` to `wbb.customer` (inner join on `customer_id`) and `wbb.decline_reason` (left join on `decline_reason_code`). `reason_description` is aliased as `decline_description` and carried to staging. `category` is aliased as `decline_category` and also carried [wbbxtr.py, `EXTRACT_QUERY`].

Two exclusion rules are applied at extract time. First, test accounts are excluded: `c.is_test = FALSE` [wbbxtr.py, EXTRACT_QUERY, comment "Exclusion: test accounts (BRD §2.3)"]. Second, abandoned applications are excluded: `a.status <> 'ABANDONED'` [wbbxtr.py, EXTRACT_QUERY, comment "Exclusion: abandoned applications (BRD §2.3)"]. DEMO accounts (`customer_type = 'DEMO'`) are explicitly not excluded in v1; this is noted as a v2 backlog item WBB-AW-019 [wbbxtr.py, EXTRACT_QUERY header comment; BRD §8].

The extract raises a warning (exit code 4, `RC_WARN`) if a `decline_reason_code` is present on a record but returns no match in the `decline_reason` lookup, indicating a pre-November-2025 code not in the table [wbbxtr.py, `extract` function, warning block]. The job_config.yaml routes `on_warning` to the load step, meaning the load proceeds even when lookup warnings occur [job_config.yaml, extract step, `on_warning: load`].

Timestamps are serialised to ISO format strings before writing to the staging JSONL file [wbbxtr.py, `extract` function, datetime serialisation block].

**4.2 Dimension load rules (wbbldr)**

`dim_customer` is upserted on conflict with `customer_id`. For each unique `customer_id` in the staged batch, the loader builds a tuple containing: a deterministic surrogate key derived from `hash(('cust', customer_id))`, the natural key, `company_name`, `business_category` mapped to `segment`, `company_size`, `is_test`, NULL for `first_product_type`, and the ETL timestamp. On conflict, the upsert overwrites `company_name`, `segment`, `company_size`, `is_test`, and `etl_last_updated_dt` (Type 1 behaviour). `first_product_type` is not overwritten by the nightly ETL [wbbldr.py, `upsert_dim_customer`].

`dim_product` is not upserted by `wbbldr`. No function for product dimension loading appears in the load code [wbbldr.py, full source — no `upsert_dim_product` function].

**4.3 Fact load rules (wbbldr)**

For each staged record, the loader derives the following:

- `is_approved`: `True` if `status == 'APPROVED'`, otherwise `False` [wbbldr.py, `load_fact`].
- `is_declined`: `True` if `status == 'DECLINED'`, otherwise `False` [wbbldr.py, `load_fact`].
- `submitted_date_key`: YYYYMMDD integer derived from `submitted_dt` [wbbldr.py, `load_fact`, comment "submitted_date_key — primary date"].
- `approved_date_key`: YYYYMMDD integer derived from `approved_dt` if present, otherwise NULL [wbbldr.py, `load_fact`].
- `days_to_decision`: difference in calendar days between `reviewed_dt` and `submitted_dt`, if `reviewed_dt` is present; otherwise NULL [wbbldr.py, `load_fact`].

The fact INSERT is idempotent on `application_id` via ON CONFLICT DO UPDATE, overwriting all attribute columns [wbbldr.py, `load_fact`, INSERT statement].

The `decline_description` field present in each staged record (populated by the extract's join to `decline_reason`) is not read by the load step and is not written to any warehouse table [wbbldr.py, `load_fact` — `decline_description` absent from the INSERT tuple and column list].

**4.4 Surrogate key generation**

All surrogate keys are generated as 63-bit integers using Python's built-in `hash()` function, seeded with a tuple of a type prefix and the natural key. The formulas are `abs(hash(('cust', customer_id))) & ((1 << 63) - 1)` for customers, `abs(hash(('prod', product_id))) & ((1 << 63) - 1)` for products (returns -1 for NULL `product_id`), and `abs(hash(('app', application_id))) & ((1 << 63) - 1)` for applications [wbbldr.py, surrogate key functions]. These are deterministic within a Python process but are not guaranteed to be stable across Python version upgrades or platform changes. Not specified in available artifacts whether this is considered a risk.

**4.5 Default handling for unresolvable references**

The `dim_product` table seeds an "Unknown Product" member at `product_key = -1` [target_schema.sql, dim_product seed]. The BRD states that unresolvable dimension references should default to designated Unknown members rather than failing the load [BRD §5]. However, no code in the available ETL files performs a product dimension lookup or routes unresolved product references to the Unknown member. The `dim_product` default member exists in the schema but the mechanism for using it is not present in the available code [wbbldr.py, full source].

Unresolvable customer segment values (unexpected `business_category` entries) are carried through to `dim_customer.segment` as-is, per BRD §3.1 instruction to handle gracefully and default to "Unknown" [BRD §3.1]. The actual code maps `business_category` directly to `segment` without a normalisation or Unknown-defaulting step [wbbldr.py, `upsert_dim_customer`]. Whether unexpected values are mapped to a canonical "Unknown" label or retained verbatim is not specified in the ETL code.

---

### 5. Operational Behaviour

**5.1 Schedule and SLA**

The job runs daily at 01:00 UTC. The SLA requires completion before 06:00 UTC. The predecessor job is `wbb-operational-backup`, which must complete before the WBBAW pipeline starts. The successor job `wbb-reporting-refresh` is triggered on exit code 0 or 4 (success or success-with-warnings) [job_config.yaml, header comment and `on_success` / `on_warning` routing].

**5.2 Step sequence and routing**

The four-step sequence and its routing logic are as follows, as specified in `job_config.yaml`:

1. **extract** (program `wbbxtr`): on success → load; on failure → notify_failure; on warning → load (the load proceeds even with lookup warnings).
2. **load** (program `wbbldr`): on success → audit; on failure → notify_failure.
3. **audit** (program `wbbaudit`): on success → notify_success; on failure → notify_failure.
4. **notify_success** or **notify_failure** (program `wbbnotify`): terminal steps. notify_success sets `TRIGGER_DOWNSTREAM: "true"`; notify_failure sets `PAGE_ONCALL: "true"` [job_config.yaml, steps].

**5.3 Restart behaviour**

The job supports restart from a named step. Setting `RESTART_FROM=extract` restarts from the extract step; setting `RESTART_FROM=load` restarts from the load step. A full historical re-run is triggered by setting `ETL_MODE=FULL` [job_config.yaml, Restart comment]. The fact load is idempotent on `application_id`, enabling restarts without duplicate fact rows [wbbldr.py, `load_fact`, ON CONFLICT clause; user story WBB-AW-005 acceptance criterion].

**5.4 Extract parameters**

The extract step runs with two boolean parameters: `EXCLUDE_TEST: "true"` and `EXCLUDE_ABANDONED: "true"`. These correspond to the two exclusion rules applied in `EXTRACT_QUERY`. The default run mode is `ETL_MODE: INCREMENTAL` [job_config.yaml, extract step params].

**5.5 Load parameters**

The load step runs with `COMMIT_INTERVAL: "5000"` and `ERROR_THRESHOLD: "50"` [job_config.yaml, load step params]. The `COMMIT_INTERVAL` parameter is not referenced in the available `wbbldr.py` source; its effect is not specified in available artifacts. The `ERROR_THRESHOLD` parameter is also not referenced in the available load code.

**5.6 Audit step**

The audit step is configured to run program `wbbaudit` with parameters `COMPARE_COUNTS: "true"`, `ALERT_ON_VARIANCE: "5"`, and `AUDIT_LOG: /var/log/wbbaw/audit` [job_config.yaml, audit step]. No file named `wbbaudit.py` exists in the available codebase. The word "audit" does not appear in any Python file in the artifact bundle. The user story WBB-AW-012 recommended adding this step and raised WBB-AW-014 to implement it; WBB-AW-014 was recorded as in progress at the time of the user story export [user_stories_export.md, WBB-AW-012 comments; Notes on this export]. See Discrepancy D4.

**5.7 Notification**

The notification program `wbbnotify` posts to Slack channel `#wbb-data-ops` on both success and failure paths [job_config.yaml, notify steps; BRD §7]. On failure, `PAGE_ONCALL: "true"` pages the on-call engineer. No `wbbnotify.py` file exists in the available codebase.

**5.8 Environment and secrets**

Database connection strings are injected from a secrets manager via `WBB_SOURCE_DSN` and `WBB_TARGET_DSN`. The staging file path defaults to `/tmp/wbbaw_stage.jsonl`. Log level defaults to INFO [job_config.yaml, environment block; wbb_common.py].

**5.9 Exit codes**

The ETL uses a four-value exit code convention: RC_OK = 0 (success), RC_WARN = 4 (success with warnings), RC_RETRY = 8 (recoverable failure, retry likely to succeed), RC_FATAL = 12 (unrecoverable failure, manual intervention required) [wbb_common.py, exit codes].

---

### 6. Discrepancies Found

Four discrepancies were identified through cross-artifact analysis. Each is documented below with source citations, quoted evidence, and an analyst assessment of the as-built behaviour.

---

**D1 — Date key used for weekly volume reporting conflicts with BRD intent**

*BRD position [BRD §5]:*
> "Count applications by approval date. Weekly volume metrics must reflect the date on which the application decision was made (approved or declined), not the date of initial submission. The submission date is retained on the fact for pipeline analysis."

*As-built position [target_schema.sql, fact_application header comment]:*
> "Note: submitted_date_key is the primary date dimension used for weekly volume reporting. The BRD (§5) specifies that volume metrics should be counted by the date the application was approved, not the date it was submitted. This warehouse uses submitted_date_key as the primary date because approved_dt was not available in the source schema at the time the ETL was built (it was added in the source schema on 2026-01-08). The approved_date_key is populated where available. Reconciling the BRD's intent with the as-built behaviour is a known open item; see the WBBAW backlog."

*Corroborating evidence [user_stories_export.md, WBB-AW-007, D. Osei comment, 17 Dec 2025]:*
> "Note on date keys — `approved_dt` was not in the source schema when I built this (it was added to the source on 2026-01-08). I've wired up `submitted_date_key` as the primary date for now. The `vw_weekly_onboarding_volume` view counts by submitted date, which is what BRD §5 says should be approved date. Will need to revisit once approved_dt is backfilled in the source."

*Corroborating evidence [target_schema.sql, vw_weekly_onboarding_volume comment]:*
> "Note: this view counts by submitted_date_key, which corresponds to the application submission date — not the approval date. See fact_application header comment for context on this known discrepancy vs. BRD §5."

*Code confirmation [wbbldr.py, `load_fact`, inline comment]:*
> `date_key(r['submitted_dt']),  # submitted_date_key — primary date`

*Analyst note:* The as-built behaviour is unambiguous. `submitted_date_key` drives weekly volume counts in the published view. `approved_date_key` is populated on the fact table where `approved_dt` is available (the source schema column was added 2026-01-08 and backfilled), but the reporting view does not use it. The BRD requirement has not been implemented. The discrepancy is acknowledged in the schema comments and the Jira thread. This is the primary date used by the current production reporting view.

---

**D2 — Customer classification field has three different names across the artifact bundle**

*BRD position [BRD §3]:*
> "Attributes include company name, business_segment, company size, and registration number."
> "The `business_segment` field is entered by the applicant at registration and is not validated against a controlled vocabulary." [BRD §3.1]

*Source schema position [source_schema.sql, customer table]:*
> Column defined as `business_category VARCHAR(100)` — not `business_segment`.
> Schema header comment: "Some column naming is inconsistent across tables (e.g. business_category vs. segment in downstream usage). Do not rename without a coordinated release."

*Target schema position [target_schema.sql, dim_customer]:*
> Column defined as `segment VARCHAR(100)` — neither `business_segment` nor `business_category`.
> Comment: "Note: segment here corresponds to wbb.customer.business_category. The column has been renamed in the warehouse to follow conformed naming conventions (segment is the standard term across the warehouse). The BRD refers to this concept as business_segment; see BRD §3.1."

*User story evidence [user_stories_export.md, WBB-AW-006, D. Osei comment, 4 Dec 2025]:*
> "One naming note — BRD §3 calls the business classification field `business_segment`, but the source schema uses `business_category`. Mapping source `business_category` to warehouse column `segment` per warehouse naming conventions. Flagged to P. Nguyen for BRD update."

*Code confirmation [wbbldr.py, `upsert_dim_customer`, inline comment]:*
> `r['business_category'],   # Source business_category → warehouse segment`

*Analyst note:* Three names refer to one concept: `business_segment` in the BRD, `business_category` in the operational source, and `segment` in the warehouse. The mapping is correctly implemented in the ETL code. The BRD has not been updated to reflect the canonical name despite the commitment recorded in WBB-AW-006. The operational source column name is `business_category` and should be treated as authoritative for source queries.

---

**D3 — User story WBB-AW-011 is marked Done but the decline description is never persisted to the warehouse**

*User story position [user_stories_export.md, WBB-AW-011]:*
> Status: **Done**, Sprint 5 (closed 16 Jan 2026).  
> Acceptance criterion: "[x] `fact_application` carries a human-readable decline reason for declined applications"  
> D. Osei comment, 15 Jan 2026: "Extract updated to join decline_reason and carry through `reason_description` as `decline_description`. Closing."  
> P. Nguyen comment, 16 Jan 2026: "Verified in staging environment. Closing sprint 5."

*Extract behaviour [wbbxtr.py, EXTRACT_QUERY]:*
The extract query performs `LEFT JOIN wbb.decline_reason d ON d.reason_code = a.decline_reason_code` and selects `d.reason_description AS decline_description`. The `decline_description` field is written to the staging JSONL file for every record [wbbxtr.py, `extract` function — `records.append(rec)` includes all query columns].

*Load behaviour [wbbldr.py, `load_fact`]:*
The `load_fact` function reads staged records and constructs a tuple for each row. The `decline_description` key, while present in each staged record, is never referenced in the tuple construction and is absent from the INSERT column list. The INSERT statement for `fact_application` lists these columns: `application_key, application_id, customer_key, submitted_date_key, approved_date_key, submitted_timestamp, approved_timestamp, status, is_approved, is_declined, days_to_decision, etl_load_dt`. No `decline_description` or equivalent column appears [wbbldr.py, `load_fact`, INSERT statement].

*Target schema confirmation [target_schema.sql, fact_application DDL]:*
No column named `decline_description`, `decline_reason_description`, `reason_description`, or any equivalent exists on `fact_application`. The schema header comment states explicitly: "Note: there is no decline_description column on this fact." [target_schema.sql, fact_application header comment].

*Analyst note:* The acceptance criterion that "`fact_application` carries a human-readable decline reason" cannot be satisfied because the column does not exist in the target table. The extract carries `decline_description` through to staging correctly; the breakage is in the load step, where the field is silently dropped. The story closure comment by P. Nguyen ("Verified in staging environment") may have verified only that the staging file contains the field, not that it lands in the warehouse. This discrepancy is not flagged anywhere in the code — it must be discovered by tracing the data flow from source query through to DDL. The BRD requirement [BRD §5: "Carry the decline reason through to the warehouse"] and the reporting use case [BRD §6: "Top decline reasons. Among declined applications, what are the most common reasons, ranked?"] are both undeliverable against the current warehouse schema.

---

**D4 — job_config.yaml references program wbbaudit which does not exist in the codebase**

*job_config.yaml position [job_config.yaml, audit step]:*
> `program: wbbaudit`  
> Parameters: `COMPARE_COUNTS: "true"`, `ALERT_ON_VARIANCE: "5"`, `AUDIT_LOG: /var/log/wbbaw/audit`

*Codebase evidence:* No file named `wbbaudit.py` exists in the artifact bundle. The word "audit" does not appear in any of the three Python files (wbbxtr.py, wbbldr.py, wbb_common.py). The string "wbbaudit" appears only in `job_config.yaml`.

*User story evidence [user_stories_export.md, WBB-AW-012, K. Walsh comment, 15 Jan 2026]:*
> "Recommendation: use the standard WBB job notification pattern. Add a post-load audit step (wbbaudit) to validate record counts before notifying downstream. [...] Implementation ticket WBB-AW-014 to be raised."

*User story evidence [user_stories_export.md, Notes on this export]:*
> "WBB-AW-014 — Implement post-load audit step and Slack notification (in progress)"

*Analyst note:* The audit step was designed in WBB-AW-012 and added to `job_config.yaml`, but the implementation (WBB-AW-014) was not complete at the time of the artifact export. The job as configured will fail at the audit step on every execution. If the job runner invokes `wbbaudit` as a subprocess, it will receive a "program not found" error; the `on_failure: notify_failure` routing on the audit step means the pipeline will alert on failure rather than silently skipping the step. The nightly pipeline cannot complete successfully in its current configured state.

---

### 7. Open Questions

The following gaps were identified during analysis. Each represents something the artifacts do not specify. They are recorded here without invented answers.

**Q1 — How is `dim_product` refreshed?**  
The target schema seeds `dim_product` with the seven reference products at DDL time. No upsert function for `dim_product` exists in `wbbldr.py`. The BRD describes `dim_product` as a conformed dimension [BRD §4.2], but no ETL mechanism for refreshing it is present in the available code. Not specified in available artifacts whether product dimension maintenance is handled by a separate job, manual process, or another program not included in this artifact bundle.

**Q2 — How are Unknown dimension members used at load time?**  
The `dim_product` seed at `product_key = -1` exists for defaulting unresolvable product references [target_schema.sql, dim_product comment]. The BRD states that unresolvable references should default to Unknown members rather than failing the load [BRD §5]. No code in `wbbldr.py` performs a product dimension lookup or applies the Unknown default. Not specified in available artifacts how or whether the Unknown product member is currently used.

**Q3 — Does the segment field apply a controlled Unknown default for unexpected business_category values?**  
BRD §3.1 states "the warehouse must handle unexpected values gracefully, defaulting to a defined 'Unknown' segment label rather than failing the load." The ETL maps `business_category` directly to `segment` with no normalisation step [wbbldr.py, `upsert_dim_customer`]. Not specified in available artifacts whether a downstream process applies this defaulting, or whether unexpected values are currently passing through verbatim.

**Q4 — Are surrogate keys stable across Python environments?**  
Surrogate keys are generated using Python's built-in `hash()` function [wbbldr.py, surrogate key functions]. Python's `hash()` is randomised by default for string inputs (PYTHONHASHSEED) but is deterministic for integers. Since the inputs are tuples containing an integer natural key (customer_id, application_id, product_id), the hash output should be stable across runs on the same platform. Not specified in available artifacts whether this has been formally assessed, or what the recovery procedure is if keys were to diverge.

**Q5 — What does COMMIT_INTERVAL do in the load?**  
The load step is configured with `COMMIT_INTERVAL: "5000"` [job_config.yaml, load step params]. This parameter is not referenced anywhere in `wbbldr.py`. The load currently issues a single commit after all dimension and fact rows are processed [wbbldr.py, `load` function — single `conn.commit()` after the full batch]. Not specified in available artifacts whether this parameter was intended for a batched-commit implementation that was not built, or is a configuration placeholder for future use.

**Q6 — What does ERROR_THRESHOLD govern?**  
The load step is configured with `ERROR_THRESHOLD: "50"` [job_config.yaml, load step params]. This parameter is not referenced in `wbbldr.py`. Not specified in available artifacts whether this was intended to cap the number of per-row errors before the load aborts, or is unused.

**Q7 — How is the approved_date_key gap resolved going forward?**  
The `approved_dt` column was added to the source schema on 2026-01-08 with a backfill for pre-existing approved records [source_schema.sql, onboarding_application note]. The `approved_date_key` is now populated on the fact where `approved_dt` is available [wbbldr.py, `load_fact`]. The BRD's intent — weekly volume reporting by approval date — has not been re-enabled. Not specified in available artifacts whether a sprint has been planned to update the reporting view to join on `approved_date_key`, or whether the view will remain submission-date-based.

**Q8 — What is the complete scope of wbbnotify?**  
The job references program `wbbnotify` with parameters for Slack channel, status, downstream trigger, and on-call paging. No `wbbnotify.py` file exists in the available artifact bundle. Its implementation is not documented beyond the job_config.yaml parameter specification. Not specified in available artifacts how `TRIGGER_DOWNSTREAM` initiates the `wbb-reporting-refresh` job.

**Q9 — How is `first_product_type` on `dim_customer` populated?**  
The column `first_product_type` was added to `dim_customer` on 2026-01-20 [target_schema.sql, dim_customer DDL comment]. The nightly ETL sets it to NULL for all upserts and explicitly defers population to "a separate job" [wbbldr.py, `upsert_dim_customer`, comment]. Not specified in available artifacts what that job is, its schedule, or whether it is currently implemented.

**Q10 — What is the data retention mechanism?**  
BRD §7 states "Application facts are retained for seven years for regulatory compliance." No partition scheme, archival process, or deletion policy appears in the target schema DDL or ETL code. Not specified in available artifacts how the seven-year retention requirement is enforced.

---

*End of specification.*
