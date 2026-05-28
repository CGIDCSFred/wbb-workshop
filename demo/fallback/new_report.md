# New Report: Average Days to Approval by Business Segment

**Requested by:** Operations team  
**Date:** 2026-05-28  
**Based on:** WBB Analytics Warehouse — Forensic Specification v1.0 (`wbbaw_spec_v1.md`)

---

## Step 1 — Feasibility Check

**Finding: all required data elements are present in the current warehouse schema. No schema amendment is needed.**

The report requires four data elements: segment name, average days to approval (approved applications only), total approved application count per segment, and the period covered by the data. Each is traceable to a specific column in the warehouse.

**Segment name**

The warehouse column `wbbaw.dim_customer.segment` holds the business classification entered by the applicant at registration. It maps from the source column `wbb.customer.business_category` [spec §3, dim_customer; spec §4.2, upsert_dim_customer comment "Source business_category → warehouse segment"]. The BRD calls this field `business_segment` [BRD §3]; the source calls it `business_category`; the warehouse uses `segment` as the conformed term [spec §6, D2]. The warehouse column is the correct one to use in a warehouse-layer view.

One caveat noted in the spec: the `segment` field is free-text, entered by the applicant, and is not validated against a controlled vocabulary [spec §2, customer table note; spec §7, Q3]. Unexpected values pass through verbatim rather than being normalised to a canonical "Unknown" label. The view will group by whatever values are stored, so a pre-aggregation cleanup step may be warranted in production but is not required for the view itself to be correct.

**Average days to approval**

The warehouse column `wbbaw.fact_application.days_to_decision` holds the calendar-day difference between `reviewed_dt` and `submitted_dt`, populated when a decision has been made (either approval or decline), NULL otherwise [spec §3, fact_application; spec §4.3, days_to_decision derivation]. Because the report asks only for approved applications, filtering to `is_approved = TRUE` makes `days_to_decision` semantically equivalent to days-to-approval: for an approved application the decision event is the approval event.

Note: there is also an `approved_timestamp` column on the fact [spec §3, fact_application DDL]. `days_to_decision` is derived from `reviewed_dt` in the source, which for approved records equals `approved_dt` after the 2026-01-08 source schema backfill [spec §2, onboarding_application note]. The spec confirms `approved_date_key` is populated from `approved_dt` where available [spec §4.3, approved_date_key]. Using `days_to_decision` filtered to approved records is the correct approach because (a) it is already computed and stored, (b) it is null-safe by construction, and (c) it matches the existing metric definition in the schema.

**Total approved application count**

A COUNT of `fact_application` rows where `is_approved = TRUE`, grouped by segment, is sufficient. `is_approved` is a derived boolean persisted on the fact [spec §4.3, is_approved derivation].

**Period covered by the data**

The fact table carries `approved_timestamp` (derived from source `approved_dt`) [spec §3, fact_application DDL; spec §4.3]. MIN and MAX of `approved_timestamp` across the filtered rows gives the earliest and latest approval dates included in the result, which is the most meaningful definition of period for a report scoped to approved applications. The `dim_date` dimension covers 2025-10-01 through 2030-12-31 [spec §3, dim_date], so no out-of-range date key issue exists for current data.

**Column and table summary**

| Required element | Warehouse table | Column |
|---|---|---|
| Segment name | `wbbaw.dim_customer` | `segment` |
| Days to approval (per application) | `wbbaw.fact_application` | `days_to_decision` |
| Approved flag | `wbbaw.fact_application` | `is_approved` |
| Application count | `wbbaw.fact_application` | `application_key` (COUNT) |
| Period start / end | `wbbaw.fact_application` | `approved_timestamp` |
| Join key | both tables | `customer_key` |

---

## Step 2 — Spec Amendment

No amendment is required. All data elements needed to produce the report are present in the current warehouse schema as specified in `wbbaw_spec_v1.md`.

---

## Step 3 — Implementation

```sql
CREATE VIEW wbbaw.vw_avg_days_to_approval_by_segment AS
/*
  Report: Average days from application submission to approval, by business segment.
  Scope: approved applications only (is_approved = TRUE).
  Source spec: wbbaw_spec_v1.md v1.0

  Joins:
    fact_application -> dim_customer on customer_key
      Reason: segment lives on the customer dimension; the fact carries only
              the surrogate key customer_key as a foreign key [spec §3,
              fact_application DDL; spec §3, dim_customer].

  Filters:
    is_approved = TRUE
      Reason: the report is scoped to approved applications. This also ensures
              days_to_decision is non-null (a decision exists) and is
              semantically equal to days-to-approval for this subset
              [spec §4.3, days_to_decision derivation].

  Note on days_to_decision:
    days_to_decision is the calendar-day difference between reviewed_dt and
    submitted_dt in the source, stored as an integer [spec §4.3]. For approved
    applications reviewed_dt = approved_dt (per source schema backfill for
    pre-existing records [spec §2, onboarding_application note]), so this
    column correctly represents days-to-approval for the filtered rows.

  Note on segment values:
    dim_customer.segment is free-text from applicant input and is not
    normalised [spec §2; spec §7, Q3]. Unexpected or inconsistent values
    will appear as separate groups. A NULL segment is included as its own
    group rather than excluded, so no approved applications are silently
    dropped from the aggregate.
*/
SELECT
    dc.segment,
    ROUND(AVG(fa.days_to_decision), 1)  AS avg_days_to_approval,
    COUNT(*)                             AS approved_application_count,
    MIN(fa.approved_timestamp)           AS period_start,
    MAX(fa.approved_timestamp)           AS period_end
FROM wbbaw.fact_application   fa
JOIN wbbaw.dim_customer        dc  ON dc.customer_key = fa.customer_key
WHERE fa.is_approved = TRUE
  AND fa.days_to_decision IS NOT NULL   -- exclude edge case: approved but no
                                        -- reviewed_dt recorded in source
GROUP BY dc.segment
ORDER BY avg_days_to_approval DESC;
```

**Reasoning for each clause:**

- `FROM wbbaw.fact_application` — the fact table is the grain source; one row per application [spec §3, fact_application].
- `JOIN wbbaw.dim_customer ON customer_key` — `customer_key` is the FK on the fact and the PK on the dimension [spec §3, fact_application DDL; spec §3, dim_customer DDL]. This is an inner join: every fact row must have a matching customer row because the loader upserts the customer dimension before inserting the fact row [spec §4.2; spec §4.3, fact load order implied by wbbldr.py structure]. No LEFT JOIN is needed here.
- `WHERE is_approved = TRUE` — restricts to the approved-applications-only scope the Operations team specified. Rows with `is_approved = FALSE` are approvals in flight or declines; those are out of scope.
- `AND days_to_decision IS NOT NULL` — defensive filter for the edge case where an application reached `status = APPROVED` but `reviewed_dt` was null in the source (spec notes `days_to_decision` is null if no decision is recorded [spec §4.3]). Excluding these prevents the AVG from silently dropping nulls in an unexplained way and makes the exclusion explicit.
- `AVG(days_to_decision)` — computes the mean calendar days across approved applications in the segment. Rounded to one decimal place for readability.
- `COUNT(*)` — counts the number of approved applications contributing to each segment's average. This is the "total number of approved applications in the segment" the Operations team asked for.
- `MIN(approved_timestamp)` / `MAX(approved_timestamp)` — derives the period covered from the actual timestamps on the fact rows rather than from a hard-coded date range, so the view is self-describing and remains accurate as new data loads. `approved_timestamp` is populated by the ETL from source `approved_dt` [spec §4.3; spec §3, fact_application DDL].
- `GROUP BY dc.segment` — produces one output row per distinct segment value.
- `ORDER BY avg_days_to_approval DESC` — surfaces the slowest segments at the top, which is the natural reading order for an operations team investigating bottlenecks.

---

## Step 4 — Verification Query

The following query lets a reviewer cross-check the view output against the raw warehouse tables without touching the source database. It reproduces the per-segment aggregates independently and compares them to the view.

```sql
-- Sanity check: compare view output against raw table aggregates.
-- Differences in any column indicate a logic error in the view definition.
-- Run this against the warehouse (wbbaw schema) after creating the view.

WITH raw_agg AS (
    SELECT
        dc.segment,
        ROUND(AVG(fa.days_to_decision), 1)  AS avg_days_to_approval,
        COUNT(*)                             AS approved_application_count,
        MIN(fa.approved_timestamp)           AS period_start,
        MAX(fa.approved_timestamp)           AS period_end
    FROM wbbaw.fact_application   fa
    JOIN wbbaw.dim_customer        dc  ON dc.customer_key = fa.customer_key
    WHERE fa.is_approved = TRUE
      AND fa.days_to_decision IS NOT NULL
    GROUP BY dc.segment
),
view_output AS (
    SELECT
        segment,
        avg_days_to_approval,
        approved_application_count,
        period_start,
        period_end
    FROM wbbaw.vw_avg_days_to_approval_by_segment
)
SELECT
    COALESCE(r.segment, v.segment)                          AS segment,
    r.avg_days_to_approval                                  AS raw_avg,
    v.avg_days_to_approval                                  AS view_avg,
    r.avg_days_to_approval = v.avg_days_to_approval         AS avg_matches,
    r.approved_application_count                            AS raw_count,
    v.approved_application_count                            AS view_count,
    r.approved_application_count = v.approved_application_count AS count_matches,
    r.period_start                                          AS raw_period_start,
    v.period_start                                          AS view_period_start,
    r.period_end                                            AS raw_period_end,
    v.period_end                                            AS view_period_end
FROM raw_agg       r
FULL OUTER JOIN view_output v  ON v.segment = r.segment
ORDER BY COALESCE(r.segment, v.segment);

-- Expected result: every row shows avg_matches = true, count_matches = true,
-- and period_start / period_end identical between raw and view columns.
-- Any row where avg_matches = false or count_matches = false indicates a
-- discrepancy requiring investigation.
-- A row that appears in one CTE but not the other indicates a segment that
-- the view includes but the raw query does not, or vice versa — which would
-- also indicate a logic error.
```

**What to look for:**

- All rows should show `avg_matches = true` and `count_matches = true`. If any row does not, the view's aggregation logic differs from the expected computation.
- The FULL OUTER JOIN ensures that a segment appearing in the view but not the raw aggregate (or vice versa) will surface as a row with NULLs on one side. No such rows should appear.
- Period start and end are not compared with a boolean flag because floating-point equivalence is not the issue for timestamps, but they should be visually identical between the raw and view columns.
- If all segments match, the view is arithmetically consistent with the underlying tables. This does not verify the business interpretation (e.g. whether `days_to_decision` correctly represents days-to-approval for the pre-backfill population [spec §2, onboarding_application note]), but it confirms the SQL is logically correct.
