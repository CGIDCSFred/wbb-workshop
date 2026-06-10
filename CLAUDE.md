# Context for Claude — wbb-workshop

## What this repository is

This is a **workshop demonstration** repository. It contains a complete,
runnable fictional system — the WBB Analytics Warehouse (WBBAW) — built to
demonstrate spec-driven reverse engineering and feature generation using Claude.

The fictional domain is a web banking onboarding platform (WBB) where small
and medium businesses apply for business banking products. The system is
deliberately simple and self-contained.

The demo now runs as a **single Streamlit application** (`streamlit_app.py`) —
no Docker required. This is the canonical demo path. See "Running the demo"
below.

## What's here

- `streamlit_app.py` — the 10-tab Streamlit demo application; the entry point
  for the workshop. Runs entirely in-process against a local SQLite file
  (`wbb_demo.db`), which it seeds with 30 days of synthetic onboarding data on
  first run.
- `requirements_streamlit.txt` — Python deps for the app (`streamlit`,
  `pandas`, `anthropic`)
- `.streamlit/` — Streamlit config (TD-blue theme) and `secrets.toml`
  (Anthropic API key; not committed)
- `artifacts/` — the complete artifact bundle: BRD, source schema, warehouse
  schema, user stories, job config, working ETL code, and the WBB ServiceNow
  incident set (`servicenow_tickets_wbb.json`)
- `prompts/` — the three workshop prompts (reverse engineering, regeneration,
  new report)
- `demo/fallback/` — pre-generated outputs used when live generation is slow or
  fails: the forensic spec (`wbbaw_spec_v1.md`), regenerated artifacts
  (`regenerated/`), the new-feature doc (`new_report.md`), the enriched-spec
  Section 8 (`wbbaw_spec_section8.md`), and the FAQ (`wbbaw_faq.md`)
- `spec/` — populated during the live demo (reverse-engineering output, Tab 3)
- `regenerated/` — populated during the live demo (regeneration output, Tab 4)
- `README.md` — the canonical run guide for the Streamlit demo

**Legacy (superseded — do not use for the workshop):** `docker-compose.yml`,
`generator/`, `dashboard/`, `scripts/`, the ETL `Dockerfile`s, and the
docker-based instructions in `demo/storyboard.md`, `SETUP.md`, and
`NEXT_STEPS.md` describe the earlier docker-compose stack. The Streamlit app
has replaced this path. Treat these as historical unless Frederick says
otherwise; they are out of step with the current demo.

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

`artifacts/servicenow_tickets_wbb.json` is also calibrated: four of its seven
incidents are pinned to the four discrepancies above (D1–D4). It is part of the
artifact bundle and must not be modified — treat it like the other artifacts.

## Running the demo environment

```bash
# Install deps
pip install -r requirements_streamlit.txt   # streamlit, pandas, anthropic

# Provide the Anthropic API key (not committed)
# .streamlit/secrets.toml:
#   ANTHROPIC_API_KEY = "sk-ant-..."

# Run the app
python -m streamlit run streamlit_app.py     # http://localhost:8501
```

On first run the app seeds 30 days of synthetic onboarding data into
`wbb_demo.db` automatically.

**Live-generation dependency / guardrails:**
- Tabs 3 (Spec), 4 (Regenerated), and 10 (L3 Chatbot) call the Anthropic API
  live and need a valid `ANTHROPIC_API_KEY`.
- Tabs 3, 4, 6, 8, and 9 fall back to `demo/fallback/` automatically if live
  generation is slow or fails.
- **Tab 10 (chatbot) has no fallback.** If the API key or network is
  unavailable, the chatbot will not work — this is the one unprotected point in
  the run. Confirm the key works before the session.

## What Frederick will do during the workshop

The demo runs as six acts across the app's ten tabs (full talk track in
`README.md`):

1. **Act 1 — Live system (Tabs 1–2).** Show onboarding running in-process and
   flip through the six artifacts.
2. **Act 2 — Reverse engineering (Tab 3).** Generate the forensic spec live
   from all eight artifacts; walk Section 6 (the four discrepancies).
3. **Act 3 — Regeneration (Tab 4).** Regenerate schema + ETL from the spec
   alone — original artifacts not consulted.
4. **Act 4 — The proof (Tab 5).** Run both ETLs against the same data; show the
   equivalence check and the side-by-side diff.
5. **Act 5 — New feature (Tab 6).** Add avg-days-to-approval from the spec; show
   the live report.
6. **Act 6 — Production knowledge (Tabs 7–10).** The L3-support arc and the
   conceptual expansion of the demo: 7 ServiceNow incidents (4 mapped to
   D1–D4), the enriched spec (Section 8 fuses operational history into the
   spec), an FAQ generated from it, and a spec-bounded L3 chatbot that answers
   KNOWN PATTERN / KNOWN GAP / UNKNOWN-ESCALATE.

The same discipline still applies: do not consult the original artifacts during
regeneration (Tab 4) — the spec must be sufficient on its own.
