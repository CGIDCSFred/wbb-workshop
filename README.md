# WBB Workshop — Leave-Behind Package

**Prepared by:** Frederick Ferguson, CGI  
**For:** TD Business Banking  
**Purpose:** Enable TD staff to run the spec-driven reverse engineering demo independently

---

## What this demonstrates

This workshop shows a complete, working version of the spec-driven reverse engineering method. It is built around a fictional web banking onboarding platform (WBB) and its analytics warehouse (WBBAW), designed to echo the structure of real modernisation work without using any TD data or IP.

The demo follows eight steps:

| Step | What happens | What it proves |
|------|-------------|----------------|
| 1 | Show a running application with its artifacts | The system exists and works |
| 2 | Reverse-engineer a forensic spec from the artifacts | Contradictions in the system surface automatically |
| 3 | Regenerate equivalent artifacts from the spec alone | The spec is sufficient — no code needed |
| 4 | Compare the original and regenerated artifacts | The method is repeatable |
| 5 | Deploy the regenerated code as a running application | Two independent systems, same source data |
| 6 | Compare the two running applications | Same query, same result — equivalence is proven |
| 7 | Extend the spec with a new feature | The spec is a launchpad, not just a record |
| 8 | Deploy the new feature to both and compare | New capability, traceable to a single spec amendment |

Steps 4–8 are the proof. They close the loop from "this looks reasonable" to "this is demonstrably equivalent and extensible."

---

## Prerequisites

**Machine requirements:** Windows 11 (corporate or personal)

**Software — install once before the session:**

### 1. WSL2 (Windows Subsystem for Linux 2)
Open PowerShell as Administrator and run:
```powershell
wsl --install
```
Reboot when prompted. This is required by Rancher Desktop.

### 2. Rancher Desktop
Download from **rancherdesktop.io** (free, open source, Apache 2.0 licence).

During first launch you will see a welcome screen. Set **Container Engine** to **dockerd (moby)** — not containerd. Everything else can remain as default.

After Rancher Desktop finishes initialising (watch the progress bar at the bottom of the window), open a new PowerShell window and confirm:
```powershell
docker version
docker compose version
```
Both should return version information without errors.

### Corporate network note (CGI / TD networks)
SSL inspection proxies on corporate networks intercept PyPI traffic. All Dockerfiles in this repository already include `--trusted-host pypi.org --trusted-host files.pythonhosted.org` on every pip install command. If you see SSL certificate errors during the first build, this flag is the fix. If it persists, contact your network team.

---

## First-time setup (run once)

From the `wbb-workshop` directory in PowerShell:

```powershell
# Step 1 — Start the databases and dashboard
# On first run this builds all Docker images (~3 minutes depending on network)
docker compose up source-db warehouse-db regen-warehouse-db dashboard -d

# Step 2 — Wait ~15 seconds for PostgreSQL to initialise, then confirm:
docker compose ps
# All three database containers should show "healthy"

# Step 3 — Seed 30 days of historical onboarding data
docker compose run --rm generator python generate.py seed 30

# Step 4 — Start the live onboarding stream
docker compose up generator -d

# Step 5 — Open the dashboard
# http://localhost:8080
```

The dashboard should show the live feed populating on the left side. The right side (warehouse panels) will be empty until you press **⚡ Run ETL** in the browser.

---

## The dashboard

Open **http://localhost:8080** and leave it visible on the projector throughout the session.

The dashboard has three sections:

### Top section — SOURCE DB (Operational, live)
Pulls from the WBB operational database. Refreshes every 5 seconds.
- **Live Application Feed** — new customer applications appearing in real time, with company name, segment, size, and outcome (SUBMITTED → IN_REVIEW → APPROVED / DECLINED)
- **Application Funnel** — live counts at each stage of the onboarding pipeline

### Middle section — ANALYTICS WAREHOUSE (After ETL)
Pulls from the WBBAW analytics warehouse. Only updates when you press ⚡ Run ETL.
- **Weekly Onboarding Volume** — bar chart, last 8 weeks, submitted vs approved vs declined
- **Approval Rate by Segment** — horizontal bars showing approval rate per business segment

### Bottom section — PROOF
The equivalence demonstration. Populated after you press ⚡ Run ETL.
- **Equivalence Check** — the same query run against both the original and regenerated warehouses, compared row by row. Shows ✓ EQUIVALENT or ✗ DIFFERS.
- **New Feature** — deploy `vw_avg_days_to_approval_by_segment` to both warehouses and compare results.

### Header buttons
| Button | What it does |
|--------|-------------|
| ⚡ Run ETL | Loads current source data into both the original and regenerated warehouses simultaneously |
| ↺ Restart Demo | Clears all source data and both warehouses. Use this to reset to zero before a session. |

---

## Running the demo

### Before the session starts
```powershell
# If the environment is already running from a previous session:
.\demo\restart.ps1 full    # wipes all data and re-seeds from scratch
# OR if continuing from where you left off:
.\demo\restart.ps1         # restarts all services without wiping data
```

Then open **http://localhost:8080** and confirm the live feed is active.

### Act 1 — Show the live system (~5 min)

The dashboard is your main screen. Walk the audience through the two sides:
- Left: operational database, updating live every few seconds
- Right: currently empty — "this is what the analytics warehouse looks like before the ETL runs"

Switch to VS Code and briefly show the artifacts:
- `artifacts/brd_wbb_v1.1.md` — the Business Requirements Document (§2.3 exclusion rules, §5 transformation logic)
- `artifacts/etl/wbbxtr.py` — the extract code
- `artifacts/etl/wbbldr.py` — the load code

The prompt to the audience: *"Looks reasonable. But does the code actually do what the BRD says? Let's find out."*

---

### Act 2 — Reverse-engineering pass (~6 min)

Open a **new Claude conversation** (claude.ai or Claude Code).

Attach all eight artifact files from the `artifacts/` directory:
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

**While Claude runs (~90 seconds), explain to the audience:**
The prompt gives Claude five rules: provenance for every claim, discrepancies preserved not resolved, gaps named not filled, no invented details, prose throughout. These rules are what make the output a forensic specification rather than a summary.

When output appears, save it to `spec/wbbaw_spec_v1.md`.

**Navigate to Section 6 — Discrepancies Found.** This is the centrepiece.

Walk through each finding:

1. **Date column drift** — BRD §5 says weekly volume should count by approval date. The ETL uses submission date as the primary date key. The `vw_weekly_onboarding_volume` view is counting the wrong date. The data to fix it exists on the fact table — the ETL was just never updated after `approved_dt` was added to the source schema.

2. **Three-name field** — The BRD calls it `business_segment`. The source schema uses `business_category`. The warehouse uses `segment`. Three names, one concept. A future developer searching the codebase for `business_segment` will find nothing.

3. **Done but not implemented** — User story WBB-AW-011 ("Capture decline reason") is marked Done with all acceptance criteria checked. The extract carries `decline_description` through to staging. The load step never writes it. The warehouse fact table has no such column. Story closed; feature not delivered. Discoverable only by tracing the data flow across three files.

4. **Orphaned reference** — `job_config.yaml` step `audit` runs program `wbbaudit`. No `wbbaudit.py` exists anywhere in the codebase. The audit step would fail at runtime.

*Four inconsistencies in a system built over five sprints by a small team. None visible from reading the BRD. They emerge from reading the code as evidence.*

---

### Act 3 — Regeneration from spec alone (~5 min)

Open a **fresh Claude conversation** — no memory of the artifacts.

Attach **only** `spec/wbbaw_spec_v1.md`. Nothing else.

Open `prompts/02_regeneration.md` and paste its contents as the prompt. Submit.

**While Claude runs (~2 min), explain:**
The regeneration claim is only honest if the regenerator has seen nothing but the spec. If you look at the original ETL code during regeneration, the claim collapses. The spec has to be sufficient on its own.

When output appears, save the files to `regenerated/`.

Then press **⚡ Run ETL** in the dashboard. Watch the middle section populate. The PROOF section at the bottom will now show the equivalence check.

**Point to the PROOF section:** Both warehouses — the original and the regenerated — show the same weekly counts for every week. ✓ EQUIVALENT.

---

### Act 4 — New feature from spec alone (~5 min)

Open another **fresh Claude conversation**. Attach only `spec/wbbaw_spec_v1.md`.

Open `prompts/03_new_report.md` and paste its contents as the prompt. Submit.

The business question: *"Average days from application submission to approval, broken down by business segment."*

Claude will check whether the data is already in the warehouse (it is — `days_to_decision` is on `fact_application`, `segment` is on `dim_customer`), then produce a `CREATE VIEW` statement.

Press **Deploy New Feature** in the dashboard PROOF section. Both warehouses get the new view. The panel shows both returning the same results by segment.

*From business question to running report, without a developer touching the original ETL code. The spec did the work.*

---

## Fallback — if live generation fails

Pre-generated outputs are in `demo/fallback/`. If Claude takes too long or produces poor output during any act, copy the relevant fallback file to the expected location before the act begins.

| Act | Fallback file | Copy to |
|-----|--------------|---------|
| Act 2 | `demo/fallback/wbbaw_spec_v1.md` | `spec/wbbaw_spec_v1.md` |
| Act 3 | `demo/fallback/regenerated/` (entire directory) | `regenerated/` |
| Act 4 | `demo/fallback/new_report.md` | show in editor; paste the SQL into the warehouse |

---

## Resetting between sessions

```powershell
# Restart everything, keep all data
.\demo\restart.ps1

# Restart dashboard only (if browser goes blank)
.\demo\restart.ps1 dashboard

# Restart generator only (if live feed stops)
.\demo\restart.ps1 generator

# Full wipe and re-seed (before a fresh demo session)
.\demo\restart.ps1 full
```

---

## The four seeded inconsistencies

These are deliberately planted and must not be fixed. They are the centrepiece of Act 2.

1. **Date column drift** — BRD §5 specifies that weekly volume counts by approval date. The ETL uses `submitted_dt` as the primary date key (`submitted_date_key` on `fact_application`). `vw_weekly_onboarding_volume` counts by submission date, not approval date.

2. **Three-name field** — BRD: `business_segment`. Source schema: `business_category`. Warehouse: `segment`. Mapped correctly in the ETL, never reconciled in the BRD.

3. **Done but not implemented** — WBB-AW-011 ("Capture decline reason") is marked Done. The extract carries `decline_description` through staging. `wbbldr.py` never writes it. `fact_application` has no such column. No comment marks the absence — must be found by data flow tracing.

4. **Orphaned reference** — `job_config.yaml` step `audit` runs `wbbaudit`. No `wbbaudit.py` exists.

---

## Key file map

| Path | What it is |
|------|-----------|
| `docker-compose.yml` | All services: source-db, warehouse-db, regen-warehouse-db, dashboard, generator, etl, regen-etl |
| `artifacts/brd_wbb_v1.1.md` | Business Requirements Document, v1.1 |
| `artifacts/source_schema.sql` | WBB operational database DDL |
| `artifacts/target_schema.sql` | WBBAW warehouse DDL (includes dim_date seed) |
| `artifacts/user_stories_export.md` | User stories with acceptance criteria and status |
| `artifacts/job_config.yaml` | Nightly ETL job configuration (contains orphaned `wbbaudit` reference) |
| `artifacts/etl/wbbxtr.py` | Extract step — reads source, applies exclusions, writes staging file |
| `artifacts/etl/wbbldr.py` | Load step — upserts dimensions, loads fact_application |
| `artifacts/etl/wbb_common.py` | Shared utilities |
| `generator/generate.py` | Onboarding simulator: `seed` populates history, `demo` runs live pipeline |
| `dashboard/main.py` | FastAPI dashboard backend |
| `dashboard/static/index.html` | Dashboard UI |
| `prompts/01_reverse_engineering.md` | Reverse-engineering prompt — use in Act 2 |
| `prompts/02_regeneration.md` | Regeneration prompt — use in Act 3 |
| `prompts/03_new_report.md` | New feature prompt — use in Act 4 |
| `spec/` | Act 2 output saved here |
| `regenerated/` | Act 3 output saved here |
| `demo/storyboard.md` | Full presenter script with timing and talk tracks |
| `demo/restart.ps1` | Restart helper script |
| `demo/fallback/` | Pre-generated outputs for all three acts |

---

## Applying this to real TD work

The WBB domain is fictional. The method transfers directly.

To apply this to a real TD programme stream:
1. Gather the existing artifacts — BRD, user stories, schema DDL, ETL code, job config
2. Use `prompts/01_reverse_engineering.md` as the template (the five rules do not change; the section structure may need adjusting for different system types)
3. The spec that comes out is auditable in a way an authored spec is not — every claim has a source, every contradiction is preserved
4. Use that spec to onboard new team members, validate the system before cutover, or extend the system safely

For migration jobs specifically, the seven-section structure in the reverse-engineering prompt (Source System, Target System, Transformation Rules, Operational Behaviour, Discrepancies, Open Questions) maps directly onto what an L3 engineer needs to understand a batch migration pipeline.

---

*Prepared by Frederick Ferguson, CGI — May 2026*
