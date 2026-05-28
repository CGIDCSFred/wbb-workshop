# Prompt 03 — New Report from Spec Alone

## How to use this prompt

This is the centrepiece of the workshop. It demonstrates that a spec is not
just a record of the past — it is a launchpad for new features.

Open a fresh Claude context. Attach only:
- `spec/wbbaw_spec_v1.md`

Do NOT attach the original artifacts or the regenerated code.

Then paste the prompt below.

---

You have a specification for an existing analytics warehouse (WBBAW). A
stakeholder has requested a new report that the current warehouse does not yet
support. Your task is to:

1. Determine whether the warehouse, as described in the spec, already holds the
   data needed to answer the new report.
2. If it does: write the SQL view (or query) that answers it, citing exactly
   which columns and tables from the spec you are drawing on.
3. If it does not: identify precisely what is missing — which fact columns,
   dimension attributes, or source joins are needed — and write the spec
   amendment required to add them, followed by the SQL.

## The new report request

> **"Average days from application submission to approval, broken down by
> business segment."**
>
> The Operations team wants to understand whether certain business segments
> (e.g. CONSTRUCTION, HEALTHCARE) take significantly longer to approve than
> others. They want to see: the segment name, the average days to approval
> (for approved applications only), the total number of approved applications
> in the segment, and the period covered by the data.

## What to produce

**Step 1 — Feasibility check.**
Does the current warehouse contain everything needed? List each data element
required and where it comes from in the spec.

**Step 2 — Spec amendment (if needed).**
If anything is missing, write a numbered amendment to the spec in the same
style as the existing spec sections. The amendment must follow the spec's
rules: provenance for every claim, gaps named not filled.

**Step 3 — Implementation.**
Write the SQL view `vw_avg_days_to_approval_by_segment`. The view should be
addable to the warehouse with a single `CREATE VIEW` statement and no schema
changes. Show your reasoning.

**Step 4 — Verification query.**
Write a short query a reviewer could run to sanity-check the view output
against raw data.
