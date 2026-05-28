# WBB Workshop — Setup and Demo Guide

A leave-behind for TD Business Banking. These instructions allow anyone on the team to run the workshop demonstration independently on a Windows 11 corporate machine.

---

## 1. What this is

The wbb-workshop is a runnable demonstration of spec-driven reverse engineering. It contains a fictional web banking onboarding platform (WBB), a nightly ETL pipeline that feeds an analytics warehouse (WBBAW), and a live dashboard that shows both sides of the system in real time. The demo has four acts: showing the live system, reverse-engineering the artifacts into a forensic specification using Claude, regenerating an equivalent implementation from that spec alone, and adding a new analytical report directly from the spec without touching the original code. The purpose is to show that a forensic spec is more useful than a conventional one — and that the method transfers directly to real modernisation work.

---

## 2. Prerequisites

- **Windows 11** (corporate or personal)
- **WSL2** — built into Windows. To install, open PowerShell as Administrator and run:
  ```powershell
  wsl --install
  ```
  Reboot when prompted. WSL2 is required by Rancher Desktop.
- **Rancher Desktop v1.22 or later** — free and open source. Download from [rancherdesktop.io](https://rancherdesktop.io).
  After installation, open Rancher Desktop, go to **Preferences > Container Engine**, and set the engine to **dockerd (moby)**. Do not use containerd — the compose commands in this guide require the Docker CLI, which Rancher Desktop installs alongside dockerd.
- No other software is required. Python, PostgreSQL, and all dependencies run inside Docker containers.

---

## 3. Corporate network note

On CGI and TD networks, SSL inspection proxies intercept outbound HTTPS traffic, including PyPI package downloads. All Dockerfiles in this repository already include the following flags on every `pip install` command:

```
--trusted-host pypi.org --trusted-host files.pythonhosted.org
```

These flags tell pip to proceed without verifying the certificate chain on those hosts, which is the standard workaround for SSL inspection proxies. If you see SSL certificate errors during `docker compose build`, this is the cause. The flags should resolve it. If they do not — for example, if your organisation's proxy uses a non-standard interception method — contact your network team about injecting a `pip.conf` with the corporate CA certificate into the Docker build context.

---

## 4. First-time setup

Run these commands once, from the `wbb-workshop` directory. They build the Docker images, initialise the database schemas, seed historical data, and load the analytics warehouse. On first run, the image builds will take 2-4 minutes depending on network speed; subsequent runs start in seconds.

```powershell
# Start the databases and dashboard (builds images on first run)
docker compose up source-db warehouse-db dashboard -d

# Wait approximately 15 seconds for PostgreSQL to finish initialising
# then confirm both databases are healthy:
docker compose ps
```

Both `wbb-source` and `wbb-warehouse` should show `healthy` before continuing.

```powershell
# Seed 30 days of historical onboarding applications (~450 records)
docker compose run --rm generator python generate.py seed 30

# Load all seeded data into the analytics warehouse (full historical load)
docker compose --profile etl run --rm -e ETL_MODE=FULL etl
```

The ETL will print progress to the terminal and exit with code 0 on success. After it completes, the warehouse contains 30 days of data and the dashboard is ready.

**Verify the setup worked** by opening [http://localhost:8080](http://localhost:8080). The right-hand panels (ANALYTICS WAREHOUSE) should show a weekly volume chart and an approval rate by segment. If they are empty, re-run the ETL command above.

---

## 5. Running the live demo

Open two terminal windows and leave both visible during the session.

**Terminal 1 — start the live onboarding stream:**
```powershell
docker compose up generator
```

The generator streams new customer applications into the source database at roughly one every 6 seconds (with random jitter). Leave this running throughout the demo.

**Terminal 2 — available for commands during Acts 3 and 4.**

**Open the dashboard in a browser:**
```
http://localhost:8080
```

Leave this visible on the projector throughout the session.

**What the dashboard shows:**

The dashboard has a two-column layout.

- **Left column — SOURCE DB (OPERATIONAL):** Pulls directly from the WBB operational database and refreshes every 5 seconds. Shows a live feed of recent applications with company names, segments, and outcomes; and a funnel count of applications by status (SUBMITTED, IN_REVIEW, APPROVED, DECLINED, ABANDONED).
- **Right column — ANALYTICS WAREHOUSE:** Pulls from the WBBAW warehouse and does not change until the ETL runs. Shows a weekly onboarding volume chart (applications submitted and approved by ISO week) and an approval rate by segment table.

The gap between the two sides is deliberate and visible — as the generator runs, the left side grows and the right side stays static. This makes the ETL's role tangible for the audience.

---

## 6. The four demo acts

### Act 1 — Show the live system (~5 min)

The dashboard is running and the generator is streaming. Point out the two sides and explain the operational/warehouse split. Explain that left side updates live; right side only updates when the nightly ETL runs.

Switch to VS Code with the `wbb-workshop` folder open. Briefly show:
- `artifacts/brd_wbb_v1.1.md` — flick to §2.3 (exclusion rules) and §5 (transformation logic)
- `artifacts/etl/wbbxtr.py` — the extract query, joins, exclusion filters
- `artifacts/etl/wbbldr.py` — the `load_fact` function

The prompt to the audience: "Looks reasonable. But is it consistent? Does the code actually do what the BRD says?"

---

### Act 2 — Reverse-engineering pass (~6 min)

Open a new Claude conversation (claude.ai or Claude Code in a fresh session). Attach all eight artifact files from the `artifacts/` directory:

```
artifacts/brd_wbb_v1.1.md
artifacts/source_schema.sql
artifacts/target_schema.sql
artifacts/user_stories_export.md
artifacts/job_config.yaml
artifacts/etl/wbbxtr.py
artifacts/etl/wbbldr.py
artifacts/etl/wbb_common.py
```

Open `prompts/01_reverse_engineering.md` and paste its contents as the prompt. Submit.

While Claude runs (approximately 90 seconds), explain the five rules in the prompt: provenance for every claim, discrepancies preserved not resolved, gaps named not filled, no invented detail, prose throughout. These rules are what make the output a forensic specification rather than a summary.

When output appears, save it to `spec/wbbaw_spec_v1.md`.

Navigate to **Section 6 — Discrepancies Found**. This is the centre of the demonstration. Walk through each finding:

- **Discrepancy 1 (date column drift):** BRD §5 specifies that weekly volume counts should be by approval date. The ETL loads submitted date as the primary date key. The `vw_weekly_onboarding_volume` view is counting by the wrong date. The data to fix it exists — `approved_dt` is on the fact table — but the ETL was built before that column was added to the source schema and was never updated.
- **Discrepancy 2 (three-name field):** The BRD calls it `business_segment`. The source schema uses `business_category`. The warehouse uses `segment`. Three names, one concept. A future developer searching the codebase for `business_segment` will find nothing.
- **Discrepancy 3 (done but not implemented):** User story WBB-AW-011 ("Capture decline reason") is marked Done with all acceptance criteria checked. The extract carries `decline_description` through to staging. The load step never writes it. The warehouse fact table has no such column. Story closed; feature not delivered.
- **Discrepancy 4 (orphaned reference):** `job_config.yaml` step `audit` runs program `wbbaudit`. No `wbbaudit.py` exists anywhere in the codebase. The audit step would fail at runtime.

The point: four inconsistencies in a system built over five sprints by a small team. None are visible from a conventional reading of the BRD. They emerge from reading the code as evidence.

---

### Act 3 — Regeneration from spec alone (~5 min)

Open a **fresh** Claude conversation with no memory of the artifacts. Attach only `spec/wbbaw_spec_v1.md`. Open `prompts/02_regeneration.md` and paste its contents as the prompt. Submit.

While Claude runs (approximately 2 minutes), explain the constraint: the regeneration claim is only honest if the regenerator has seen nothing but the spec. If you look at the original ETL code during regeneration, the claim collapses.

When output appears, save the files to `regenerated/`.

To demonstrate equivalence, run a quick query against the original warehouse in a psql session:

```powershell
docker exec -it wbb-warehouse psql -U wbbaw_app -d wbbaw
```

```sql
SELECT iso_year_week, applications_submitted, applications_approved
FROM wbbaw.vw_weekly_onboarding_volume
ORDER BY iso_year_week DESC
LIMIT 5;
```

The regenerated implementation may look different — different function names, different structure. That is expected. Semantics transfer, not syntax. The spec is the source of truth.

---

### Act 4 — New report from spec alone (~5 min)

Open another **fresh** Claude conversation. Attach only `spec/wbbaw_spec_v1.md`. Open `prompts/03_new_report.md` and paste its contents as the prompt. Submit.

The business question: average days to approval by business segment. The prompt asks Claude to check feasibility first, then write the SQL.

Claude should find that `days_to_decision` is already on `fact_application` and `segment` is on `dim_customer` — no schema change is needed. The result is a single SQL view.

Run the view against the warehouse:

```powershell
docker exec -it wbb-warehouse psql -U wbbaw_app -d wbbaw
```

```sql
-- Paste the CREATE VIEW statement from Claude's output here, then:
SELECT * FROM wbbaw.vw_avg_days_to_approval_by_segment
ORDER BY avg_days_to_approval;
```

The view returns data immediately. From business question to running report, in the time it took to run one prompt, without any developer digging through the ETL code.

---

## 7. Fallback / safety net

If live Claude generation takes too long or produces poor output during any act, pre-generated fallback files are ready in `demo/fallback/`:

| Act | Fallback file | Copy to |
|-----|--------------|---------|
| Act 2 | `demo/fallback/wbbaw_spec_v1.md` | `spec/wbbaw_spec_v1.md` |
| Act 3 | `demo/fallback/regenerated/` (entire directory) | `regenerated/` |
| Act 4 | `demo/fallback/new_report.md` | show in editor; paste SQL from it |

The fallback spec contains all four inconsistencies correctly identified. Copy the relevant file to the expected location before the affected act begins — there is no need to announce the switch.

---

## 8. Resetting the environment

```powershell
# Stop all running containers (preserves all data)
docker compose down

# Restart without wiping data (use this between rehearsal and the real session)
docker compose up source-db warehouse-db dashboard -d
docker compose up generator

# Full reset — wipes all database volumes (data is gone)
# Re-run the Section 4 first-time setup commands after this
docker compose down -v
```

After a full reset, repeat the Section 4 setup commands (seed + ETL full load) before the session.

---

## 9. The four seeded inconsistencies

These are deliberately planted in the artifacts. They must not be fixed. They are the centrepiece of Act 2 — surfacing them is what proves the method works. If Claude or a reviewer flags them as errors, push back: they are intentional, and their presence is documented here.

1. **Date column drift** — BRD §5 says weekly volume counts should use the approval date. The ETL uses `submitted_dt` as the primary date key (`submitted_date_key` on `fact_application`). `vw_weekly_onboarding_volume` counts by submission date, not approval date. The `approved_date_key` column exists on the fact table but is not used for volume metrics.

2. **Three-name field** — The BRD calls the concept `business_segment`. The source schema (`wbb.customer`) uses `business_category`. The warehouse (`wbbaw.dim_customer`) uses `segment`. Three names, one concept, no cross-reference in the code.

3. **Done but not implemented** — User story WBB-AW-011 ("Capture decline reason for unsuccessful onboardings") is marked Done with all acceptance criteria checked. The extract step (`wbbxtr.py`) joins `decline_reason` and carries `decline_description` through to the staging file. The load step (`wbbldr.py`) never writes it to the fact table. `fact_application` has no `decline_description` column. No comment in the code marks this absence — it must be found by tracing the data flow.

4. **Orphaned reference** — `artifacts/job_config.yaml` step `audit` specifies `program: wbbaudit`. No file named `wbbaudit.py` (or any variant) exists anywhere in the repository. The step would fail at runtime with a program-not-found error.

---

## 10. Key file map

| Path | What it is |
|------|-----------|
| `docker-compose.yml` | Defines all services: source-db, warehouse-db, generator, dashboard, etl |
| `artifacts/brd_wbb_v1.1.md` | Business Requirements Document for the WBB Analytics Warehouse, v1.1 |
| `artifacts/source_schema.sql` | DDL for the WBB operational database (`wbb` schema, PostgreSQL) |
| `artifacts/target_schema.sql` | DDL for the WBBAW analytics warehouse (`wbbaw` schema), including views and dim_date seed |
| `artifacts/user_stories_export.md` | All user stories for the WBBAW project, with acceptance criteria and status |
| `artifacts/job_config.yaml` | YAML job configuration for the nightly WBBAW ETL (contains the orphaned `wbbaudit` reference) |
| `artifacts/etl/wbbxtr.py` | Extract step: reads from source DB, applies exclusion rules, writes staging JSONL file |
| `artifacts/etl/wbbldr.py` | Load step: reads staging file, upserts dimensions, loads `fact_application` |
| `artifacts/etl/wbb_common.py` | Shared utilities used by both extract and load steps |
| `artifacts/etl/Dockerfile` | Docker image for the ETL; includes `--trusted-host` flags for corporate proxy compatibility |
| `generator/generate.py` | Onboarding simulator: `seed` mode populates history, `stream` mode runs the live demo feed |
| `dashboard/main.py` | FastAPI application serving the live dashboard at port 8080 |
| `prompts/01_reverse_engineering.md` | The reverse-engineering prompt — paste this into Claude with all 8 artifacts attached (Act 2) |
| `prompts/02_regeneration.md` | The regeneration prompt — paste into a fresh Claude session with only the spec attached (Act 3) |
| `prompts/03_new_report.md` | The new-report prompt — paste into a fresh Claude session with only the spec attached (Act 4) |
| `spec/` | Output directory for the live-generated spec (Act 2 output saved here) |
| `regenerated/` | Output directory for the live-generated regenerated implementation (Act 3 output saved here) |
| `demo/storyboard.md` | Presenter's script with talking points for all four acts |
| `demo/fallback/wbbaw_spec_v1.md` | Pre-generated spec with all four inconsistencies found — fallback for Act 2 |
| `demo/fallback/regenerated/` | Pre-generated regenerated implementation — fallback for Act 3 |
| `demo/fallback/new_report.md` | Pre-generated new report with SQL view — fallback for Act 4 |
