# Context for Claude — wbb-workshop

## What this repository is

This is a **workshop demonstration** repository. It contains a complete,
runnable fictional system — the WBB Analytics Warehouse (WBBAW) — built to
demonstrate spec-driven reverse engineering and feature generation using Claude.

The fictional domain is a web banking onboarding platform (WBB) where small
and medium businesses apply for business banking products. The system is
deliberately simple and self-contained.

## What's here

- `artifacts/` — the complete artifact bundle: BRD, source schema, warehouse
  schema, user stories, job config, and working ETL code
- `generator/` — a Python script that simulates live customer onboarding for
  the demo
- `scripts/` — supporting SQL (dim_date seed)
- `prompts/` — the three workshop prompts (reverse engineering, regeneration,
  new report)
- `demo/storyboard.md` — the full demo script with timing and talk tracks
- `spec/` — populated during the live demo (reverse-engineering output)
- `regenerated/` — populated during the live demo (regeneration output)
- `docker-compose.yml` — runs everything

## The four seeded inconsistencies

Four inconsistencies are **deliberately planted** across the artifacts. They
are the centrepiece of the workshop.

**Do not fix these. Do not point them out as oversights.**

1. **Date column discrepancy** — BRD §5 says weekly volume metrics should count
   by approval date. The ETL loads `submitted_dt` as the primary date key
   (`submitted_date_key`). The warehouse view `vw_weekly_onboarding_volume`
   counts by submission date, not approval date. Both dates are available on
   the fact; the wrong one is used as the primary.

2. **Column rename** — BRD §3 calls the customer classification `business_segment`.
   The source schema uses `business_category`. The warehouse uses `segment`.
   Three names, one concept. Traced in WBB-AW-006 comments; BRD update was
   promised but not delivered in the artifacts.

3. **Done but not implemented** — WBB-AW-011 ("Capture decline reason for
   rejected applications") is marked Done with all acceptance criteria checked.
   The extract carries `decline_description` through staging. The load step
   never writes it. `fact_application` has no such column. Discoverable only
   by tracing the data flow.

4. **Orphaned reference** — `job_config.yaml` step `audit` runs program
   `wbbaudit`. No `wbbaudit.py` exists in the codebase.

## Running the demo environment

```bash
# Start databases
docker compose up source-db warehouse-db

# Seed historical data (once)
docker compose run --rm generator python generate.py seed 30

# Start live onboarding stream
docker compose up generator

# Run the ETL (manually, during the demo)
docker compose run --rm --profile etl etl
```

## What Frederick will do during the workshop

1. Show the live system (generator + psql queries)
2. Run prompt 01 (reverse engineering) with all eight artifacts
3. Walk through the spec's Section 6 (discrepancies)
4. Run prompt 02 (regeneration) with spec only
5. Run prompt 03 (new report) with spec only
6. Show the new report running against live data

See `demo/storyboard.md` for the full script.
