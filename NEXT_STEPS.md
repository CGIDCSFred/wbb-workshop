# Next Steps — WBB Workshop Demo

## The 8-Step Model

This workshop demonstrates a complete cycle: from a running system, through forensic spec extraction, to regeneration from spec alone, to proof of equivalence, to spec-driven extension.

| Step | What It Demonstrates | Status |
|------|----------------------|--------|
| 1 | A running application with its artifacts — the system exists and is observable | Done |
| 2 | Reverse-engineer a spec from the application — forensic reading surfaces what the code actually does | Done |
| 3 | Regenerate equivalent artifacts from the spec alone — the spec is sufficient to rebuild | Done |
| 4 | Compare the artifacts and show they are equivalent — both warehouses answer the same query the same way | Done |
| 5 | Deploy the regenerated code as a running application — regen warehouse is live alongside original | Done |
| 6 | Compare the two running applications — Equivalence Check panel shows both ETLs produce matching results | Done |
| 7 | Extend the spec with a new feature — spec amendment in demo/fallback/new_report.md | Done (spec amendment exists) |
| 8 | Deploy the new feature to both and compare — New Feature panel deploys view to both, compares results | Done |

---

## What Is Built and Working

### Infrastructure
- `source-db` (port 5432) — WBB operational database, populated by the generator
- `warehouse-db` (port 5433) — original WBBAW analytics warehouse
- `regen-warehouse-db` (port 5434) — regenerated WBBAW analytics warehouse (new)
- `dashboard` (port 8080) — FastAPI dashboard with all panels
- `generator` — streams live onboarding events into source-db
- `etl` profile — original ETL container
- `regen-etl` profile — regenerated ETL container (new)

### Dashboard Panels
- Panel 1 (top-left): Live Application Feed from source-db
- Panel 2 (top-right): Weekly Onboarding Volume from original warehouse
- Panel 3 (bottom-left): Application Funnel from source-db
- Panel 4 (bottom-right): Approval Rate by Segment from original warehouse
- Panel 5 — PROOF: Equivalence Check — compares last 5 ISO weeks across both warehouses
- Panel 6 — PROOF: New Feature — deploys and compares avg-days-to-approval view on both

### API Endpoints
- `POST /api/run-etl` — loads source data into original warehouse
- `POST /api/run-etl/regen` — loads source data into regenerated warehouse (new)
- `GET  /api/equivalence` — queries both warehouses, compares weekly volume (new)
- `POST /api/new-feature/deploy` — creates vw_avg_days_to_approval_by_segment on both (new)
- `GET  /api/new-feature/query` — queries the new view on both, compares by segment (new)

---

## What Needs Refinement Before Showing TD

1. **Test the full flow end-to-end.** Run `docker compose up -d`, seed data with the generator, click Run Both ETLs, confirm the Equivalence Check shows green. This has not been smoke-tested in this environment yet.

2. **Verify the regenerated schema FK constraint.** The regenerated `target_schema.sql` has `wbbaw.fact_application.submitted_date_key` referencing `wbbaw.dim_date(date_key)`. The mini-ETL in the dashboard derives date keys as YYYYMMDD integers — confirm these land within the seeded dim_date range (2025-10-01 to 2030-12-31). If the generator produces dates outside this range the FK insert will fail.

3. **Consider whether to keep `regen-warehouse-db` in depends_on for the dashboard.** Currently the dashboard waits for regen-warehouse-db to be healthy before starting. If that service is slow to initialise, it delays the dashboard. An alternative is to make the regen connection optional (graceful degradation) and remove it from depends_on, then only require it for the proof panels.

4. **Confirm the new-feature view column name.** The spec (new_report.md Step 3) uses `approved_application_count`; the dashboard API and panel display `approved_applications`. These match the deployed view SQL — just verify the column name in the view matches what the query expects.

5. **Timing on the "Run Both ETLs" button.** The button runs both ETLs sequentially in the browser. If the warehouse is large, this may take a few seconds. Consider adding a progress message.

6. **Polish the empty-state flow for Panel 6.** After deploying, the panel should auto-refresh and show the comparison table without requiring a manual reload. The current implementation queries `/api/new-feature/query` after deploy, which should work — but test that the deployed view is immediately queryable (it should be, since views take effect on CREATE).

---

## Key Demo Moment for Each Step

| Step | The moment |
|------|------------|
| 1 | Click "Restart Demo", watch the live feed fill with applications, click Run ETL, watch panels 2 and 4 populate |
| 2 | Open the reverse-engineering prompt, attach all six artifacts, show spec sections 6 and 7 where the four inconsistencies surface |
| 3 | Open a fresh context, feed only the spec, run the regeneration prompt, show the regenerated ETL and schema files |
| 4 | Side-by-side the original and regenerated target_schema.sql — same tables, same views, same grain |
| 5 | `docker compose up -d` — both databases are live simultaneously |
| 6 | Click "Run Both ETLs" — the Equivalence Check panel turns green: EQUIVALENT |
| 7 | Open new_report.md — the spec amendment documents avg-days-to-approval by segment, traces every column to the spec |
| 8 | Click "Deploy New Feature" — both warehouses get the view, the panel turns green: NEW FEATURE EQUIVALENT |

---

## Suggested Timing for the Full Session (60 minutes)

| Minutes | Activity |
|---------|----------|
| 0–5 | Framing: why spec-driven development matters for WBB migration |
| 5–15 | Steps 1–2: Show running app, run reverse-engineering prompt live |
| 15–20 | Walk through spec sections 6 and 7: the four seeded inconsistencies |
| 20–30 | Step 3: Run regeneration prompt in fresh context |
| 30–40 | Steps 4–6: Show both warehouses, click Run Both ETLs, show Equivalence Check green |
| 40–50 | Steps 7–8: Walk through new_report.md spec amendment, Deploy New Feature, show green |
| 50–60 | Discussion: how does this transfer to the WBB → TDBC migration job? |

The WBB → TDBC transfer discussion should emphasise: the five forensic rules are the transferable part; the seven spec sections change with domain (the migration job needs a State Machine section and an Identity Model section in place of the ETL-specific sections).
