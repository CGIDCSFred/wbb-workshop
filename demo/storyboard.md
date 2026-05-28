# Workshop Demo Storyboard

## Setup (before the room arrives)

Run once in a terminal and leave running:

```powershell
# Start everything (first run: builds images, inits schemas, seeds dim_date)
docker compose up source-db warehouse-db dashboard -d

# Seed 30 days of historical data (once only — skip if already done)
docker compose run --rm generator python generate.py seed 30

# Load the warehouse with the seed data
docker compose --profile etl run --rm -e ETL_MODE=FULL etl

# Start the live onboarding stream
docker compose up generator
```

Open your browser to **http://localhost:8080** — the dashboard should show:
- Left: live feed of applications, funnel counts
- Right: weekly volume chart and approval rate by segment

Leave the browser visible on the projector throughout the demo.

Open VS Code with the `wbb-workshop` folder. Have these files ready to tab to:
- `artifacts/brd_wbb_v1.1.md`
- `artifacts/etl/wbbxtr.py`
- `artifacts/etl/wbbldr.py`
- `spec/wbbaw_spec_v1.md` (will be created during demo)
- `prompts/01_reverse_engineering.md`
- `prompts/02_regeneration.md`
- `prompts/03_new_report.md`

---

## Act 1 — "Here's the system" (~5 min)

**You talk:** "WBB is a fictional web banking platform — small businesses apply
online for banking services. The operational database records everything:
applications submitted, reviewed, approved, declined. Here it is running live."

**Show:** the dashboard at http://localhost:8080. Point out:
- Top left: the live feed ticking every few seconds — new companies onboarding
- Bottom left: the funnel counts updating in real time
- Top right: weekly volume chart — this is the warehouse view
- Bottom right: approval rate by segment — also from the warehouse

**You talk:** "Notice the two sides of this dashboard. Left side pulls from the
operational database — it updates every 5 seconds as new applications come in.
Right side pulls from the analytics warehouse. That only updates when the ETL
runs. Right now they're in sync. By tomorrow morning, the left side will have
grown and the right side will be behind — until the nightly ETL catches up."

**You talk:** "The ETL was built over five sprints. Here are the artifacts the
team produced — a BRD, user stories, the schema DDL, and the ETL code."

**Switch to VS Code.** Briefly show:
- `brd_wbb_v1.1.md` — flick to §2.3 (exclusion rules) and §5 (transformation logic)
- `wbbxtr.py` — show the EXTRACT_QUERY, point out the joins, the exclusion filters
- `wbbldr.py` — show the load_fact function

**You talk:** "Looks reasonable. But is it consistent? Does the code actually do
what the BRD says? That's not obvious to read. Let's find out."

---

## Act 2 — "The reverse-engineering pass" (~6 min)

**You talk:** "I'm going to give Claude all eight artifacts and ask it to
reconstruct the system forensically — provenance for every claim, discrepancies
preserved not resolved, gaps named not filled. Watch the output."

**In Claude Code (or Claude.ai):**
Open `prompts/01_reverse_engineering.md`. Attach all eight artifact files.
Paste the prompt. Submit.

**While Claude runs (~90 seconds), you talk:**
"The five rules in the prompt are what make this different from just asking
for a summary. Provenance means every claim traces back to a specific file and
line. Surfacing discrepancies means contradictions between artifacts are
preserved — not smoothed away. This is forensic reconstruction, not spec
authoring."

**When output appears:** Save to `spec/wbbaw_spec_v1.md`.

**You talk:** "Let me show you what it found." Navigate to:

- **Section 6 — Discrepancies Found.** Walk through each one. The audience
  should be surprised — these are not obvious from reading the BRD.

  - *Discrepancy 1 (date columns):* BRD §5 says count by approval date. The ETL
    loads submitted date as the primary date key. The weekly volume report is
    counting the wrong date. The data exists to fix it — it's a one-line change
    — but it hasn't been made.

  - *Discrepancy 2 (column rename):* BRD calls it `business_segment`. Source
    calls it `business_category`. Warehouse calls it `segment`. Three names,
    one concept. A future reader searching the codebase for `business_segment`
    will find nothing.

  - *Discrepancy 3 (done but not implemented):* WBB-AW-011 is marked Done.
    The acceptance criteria say `fact_application` carries a human-readable
    decline reason. The extract carries `decline_description` through staging.
    The load step never writes it. The warehouse schema has no such column.
    Story closed, feature not delivered.

  - *Discrepancy 4 (orphaned reference):* job_config.yaml step `audit` runs
    `wbbaudit`. No `wbbaudit.py` exists anywhere.

**You talk:** "Four inconsistencies in a system built over five sprints by a
small, competent team. None of them were visible from a conventional reading
of the BRD. The spec found them because it reads the code as evidence."

---

## Act 3 — "Regeneration from spec alone" (~5 min)

**You talk:** "Here's the test of whether a spec like this is actually useful.
I'm going to open a fresh context — Claude has seen nothing of this system —
and give it only the spec. Nothing else. Can it build something that runs?"

**Open a new Claude context. Attach only `spec/wbbaw_spec_v1.md`.**
Open `prompts/02_regeneration.md`. Paste the prompt. Submit.

**While Claude runs (~2 min), you talk:**
"The regeneration claim is only honest if the regenerator has nothing but the
spec. No peeking at the original ETL. If the spec is sufficient, the regenerated
system will produce the same business answers against equivalent input data."

**When output appears:** Save files to `regenerated/`.

**Run a quick equivalence check in psql:**
```sql
-- Original warehouse
SELECT iso_year_week, applications_submitted, applications_approved
FROM wbbaw.vw_weekly_onboarding_volume
ORDER BY iso_year_week DESC LIMIT 5;
```

**You talk:** "The regenerated implementation may look different — different
function names, different structure. That's fine. Semantics transfer, not syntax.
The spec is the source of truth now."

---

## Act 4 — "Adding a new feature from spec alone" (~5 min)

**You talk:** "This is the goal of the whole exercise. A stakeholder walks in
and says: I want a new report. Average days to approval by business segment.
Normally this requires: find the right developer, dig through the code, figure
out if the data exists, build it. Watch what happens when you have a good spec."

**Open a fresh Claude context. Attach only `spec/wbbaw_spec_v1.md`.**
Open `prompts/03_new_report.md`. Paste the prompt. Submit.

**While Claude runs (~60 seconds), you talk:**
"The prompt asks Claude to first check feasibility — does the warehouse already
hold what's needed? Then write the spec amendment if anything is missing. Then
write the SQL. In that order."

**When output appears:**

Point out:
- Claude should find that `days_to_decision` is already on the fact table,
  and `segment` is on `dim_customer` — the data is there.
- No schema change is needed.
- The view is a one-page SQL query.

**Run the new view in psql (warehouse-db):**
```sql
-- Add the view
CREATE VIEW wbbaw.vw_avg_days_to_approval_by_segment AS
-- [paste Claude's output here]
;

-- Query it
SELECT * FROM wbbaw.vw_avg_days_to_approval_by_segment ORDER BY avg_days_to_approval;
```

**You talk:** "From business question to running report, in the time it took to
run one prompt. No developer needed to dig through the ETL code. The spec did
the navigating."

---

## Closing (~2 min)

**You talk:** "What you just saw was a demo. But the method is real and
transferable. The same approach works on any system where you have artifacts —
code, BRDs, user stories, job configs — and you need to understand what was
actually built, catch what was missed, and extend it safely.

The four inconsistencies we found today were deliberately planted. But in
practice, in a system built over months by multiple teams under deadline
pressure, you'd find more. And they'd be harder to see without a forensic
lens."

---

## Fallback plan

If the live Claude generation takes too long or produces poor output:
- Pre-generated spec is in `demo/fallback/wbbaw_spec_v1.md`
- Pre-generated regeneration output is in `demo/fallback/regenerated/`
- The new report SQL is in `demo/fallback/vw_avg_days_to_approval.sql`

Switch to fallback silently by copying files to the right locations before
the affected act.

---

## Quick reference — key psql queries

```sql
-- Source DB: live application counts
\c wbb
SELECT status, COUNT(*) FROM wbb.onboarding_application GROUP BY status;

-- Source DB: recent applications
SELECT a.application_id, c.company_name, c.business_category, a.status, a.submitted_dt
FROM wbb.onboarding_application a
JOIN wbb.customer c ON c.customer_id = a.customer_id
ORDER BY a.submitted_dt DESC LIMIT 10;

-- Warehouse: weekly volume
\c wbbaw
SELECT * FROM wbbaw.vw_weekly_onboarding_volume ORDER BY iso_year_week DESC LIMIT 8;

-- Warehouse: approval rate by segment
SELECT * FROM wbbaw.vw_approval_rate_by_segment;
```
