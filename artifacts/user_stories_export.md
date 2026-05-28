# WBB Analytics Warehouse — User Stories

**Source:** Jira export from project `WBB-AW`, Analytics Warehouse epic
**Export date:** 28 January 2026
**Filter:** Stories closed between 1 November 2025 and 28 January 2026
**Exported by:** P. Nguyen

---

## WBB-AW-005

| | |
|---|---|
| **Type** | Story |
| **Status** | Done |
| **Sprint** | Sprint 3 (closed 5 Dec 2025) |
| **Story Points** | 8 |
| **Assignee** | D. Osei |
| **Reporter** | P. Nguyen |
| **Components** | etl |

**Title:** Build nightly ETL extract from WBB operational database

**Acceptance Criteria:**
- [x] Extract reads all `onboarding_application` rows submitted on the run date
- [x] Extract joins to `customer`, `banking_product`, and `decline_reason` for context
- [x] Exclusion rules from BRD §2.3 are applied at extract time
- [x] Job is restartable without producing duplicate fact rows

**Comments:**

> **D. Osei, 3 Dec 2025:** Extract logic working end-to-end. One note — BRD §2.3 says exclude test accounts using the `is_test` flag, but there's also a `customer_type` field with a 'DEMO' value. Raised with P. Nguyen whether DEMO accounts should also be excluded.

> **P. Nguyen, 4 Dec 2025:** DEMO exclusion is out of scope for v1. The is_test filter covers the QA test accounts which are the ones that matter for now. Will add DEMO exclusion to the v2 backlog.

> **D. Osei, 5 Dec 2025:** OK. Filtering on is_test = FALSE only. Closing.

---

## WBB-AW-006

| | |
|---|---|
| **Type** | Story |
| **Status** | Done |
| **Sprint** | Sprint 3 (closed 5 Dec 2025) |
| **Story Points** | 3 |
| **Assignee** | D. Osei |
| **Reporter** | P. Nguyen |
| **Components** | etl |

**Title:** Load conformed dimensions with Type 1 overwrite

**Acceptance Criteria:**
- [x] `dim_customer` loader upserts on `customer_id`
- [x] `dim_product` loader upserts on `product_id`
- [x] `etl_last_updated_dt` is set on every upserted row
- [x] No history is preserved (Type 1 only; Type 2 deferred per BRD §4.3)

**Comments:**

> **D. Osei, 4 Dec 2025:** Dimension loaders complete. One naming note — BRD §3 calls the business classification field `business_segment`, but the source schema uses `business_category`. Mapping source `business_category` to warehouse column `segment` per warehouse naming conventions. Flagged to P. Nguyen for BRD update.

> **P. Nguyen, 5 Dec 2025:** Confirmed. BRD will be updated in the next revision to align on `segment`. Fine to proceed.

---

## WBB-AW-007

| | |
|---|---|
| **Type** | Story |
| **Status** | Done |
| **Sprint** | Sprint 4 (closed 19 Dec 2025) |
| **Story Points** | 5 |
| **Assignee** | D. Osei |
| **Reporter** | P. Nguyen |
| **Components** | etl, warehouse-schema |

**Title:** Implement star schema and fact_application load

**Acceptance Criteria:**
- [x] `fact_application` loads with correct grain (one row per application)
- [x] `submitted_date_key` and `approved_date_key` are both populated where available
- [x] Fact load is idempotent on `application_id`
- [x] `is_approved` and `is_declined` flags are derived correctly from status

**Comments:**

> **D. Osei, 17 Dec 2025:** Fact load working. Note on date keys — `approved_dt` was not in the source schema when I built this (it was added to the source on 2026-01-08). I've wired up `submitted_date_key` as the primary date for now. The `vw_weekly_onboarding_volume` view counts by submitted date, which is what BRD §5 says should be approved date. Will need to revisit once approved_dt is backfilled in the source.

> **P. Nguyen, 18 Dec 2025:** Noted. Let's get v1 shipped and revisit this in sprint 5. Please add a comment in the schema.

> **D. Osei, 19 Dec 2025:** Comment added to fact_application DDL. Closing.

---

## WBB-AW-008

| | |
|---|---|
| **Type** | Story |
| **Status** | Done |
| **Sprint** | Sprint 4 (closed 19 Dec 2025) |
| **Story Points** | 2 |
| **Assignee** | D. Osei |
| **Reporter** | P. Nguyen |
| **Components** | etl |

**Title:** Derive is_approved and is_declined flags from application status

**Acceptance Criteria:**
- [x] `is_approved = TRUE` when status = 'APPROVED'
- [x] `is_declined = TRUE` when status = 'DECLINED'
- [x] Both flags are FALSE for applications still in progress
- [x] Reports can filter or aggregate on these flags without parsing status strings

---

## WBB-AW-009

| | |
|---|---|
| **Type** | Story |
| **Status** | Done |
| **Sprint** | Sprint 4 (closed 22 Dec 2025) |
| **Story Points** | 2 |
| **Assignee** | K. Walsh |
| **Reporter** | P. Nguyen |
| **Components** | warehouse-schema, reporting |

**Title:** Add reporting views for weekly volume and approval rate by segment

**Acceptance Criteria:**
- [x] `vw_weekly_onboarding_volume` returns applications submitted and approved per ISO week
- [x] `vw_approval_rate_by_segment` returns approval rate per customer segment
- [x] Both views are documented in the schema header

**Comments:**

> **K. Walsh, 21 Dec 2025:** Both views created. Deferring top decline reasons and funnel drop-off views to the reporting layer per the scope decision from the architecture review.

---

## WBB-AW-011

| | |
|---|---|
| **Type** | Story |
| **Status** | Done |
| **Sprint** | Sprint 5 (closed 16 Jan 2026) |
| **Story Points** | 5 |
| **Assignee** | D. Osei |
| **Reporter** | P. Nguyen |
| **Components** | etl, warehouse-schema |

**Title:** Capture decline reason for rejected applications

**Description:**
As a WBB Operations analyst, I want to see the specific reason an application was declined, so that I can identify patterns in declines and prioritise process improvements without querying the operational system.

**Acceptance Criteria:**
- [x] `fact_application` carries a human-readable decline reason for declined applications
- [x] The decline reason is populated by the nightly ETL via the `decline_reason` lookup table
- [x] Reports can group, filter, and rank applications by decline reason
- [x] Approved and in-progress applications have a null decline reason

**Comments:**

> **D. Osei, 13 Jan 2026:** Started on this. The source `onboarding_application` table only has `decline_reason_code`, not a human-readable description. Need to join to `decline_reason` lookup. Doing that in the extract.

> **D. Osei, 15 Jan 2026:** Extract updated to join decline_reason and carry through `reason_description` as `decline_description`. Closing.

> **P. Nguyen, 16 Jan 2026:** Verified in staging environment. Closing sprint 5.

---

## WBB-AW-012

| | |
|---|---|
| **Type** | Spike |
| **Status** | Done |
| **Sprint** | Sprint 5 (closed 16 Jan 2026) |
| **Story Points** | 2 |
| **Assignee** | K. Walsh |
| **Reporter** | P. Nguyen |
| **Components** | operations |

**Title:** SPIKE: Design monitoring and alerting approach for WBBAW ETL

**Acceptance Criteria:**
- [x] Document the WBB job scheduling and alerting conventions
- [x] Recommend alerting approach for WBBAW (success, failure, SLA breach)
- [x] Identify required changes to job_config.yaml

**Comments:**

> **K. Walsh, 15 Jan 2026:** Recommendation: use the standard WBB job notification pattern. Add a post-load audit step (wbbaudit) to validate record counts before notifying downstream. Also add a Slack notification step at the end of the job. Implementation ticket WBB-AW-014 to be raised.

> **K. Walsh, 16 Jan 2026:** Closing spike. WBB-AW-014 raised for implementation.

---

## Notes on this export

Two stories were planned for the WBBAW v1 build that did not close before this export was generated:

- **WBB-AW-013** — Validate ETL against two weeks of historical data (in progress)
- **WBB-AW-014** — Implement post-load audit step and Slack notification (in progress)

The seven completed stories above represent the WBBAW v1 build as delivered.

---

*End of export.*
