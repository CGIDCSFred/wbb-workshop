# WBB Workshop — Spec-Driven Development Demo

**Prepared by:** Frederick Ferguson, CGI  
**For:** TD Business Banking  
**Purpose:** Demonstrate the spec-driven reverse engineering method using a fictional WBB analytics warehouse

---

## What this demonstrates

A complete, working demonstration of spec-driven reverse engineering. Built around a fictional web banking onboarding platform (WBB) and its analytics warehouse (WBBAW), designed to echo the structure of real modernisation work without using any TD data or IP.

The demo runs as a single Streamlit application — no Docker required.

| Tab | What it shows | What it proves |
|-----|--------------|----------------|
| 1 Live System | Customer onboarding running in-process | The source system exists and works |
| 2 Artifacts | BRD, schemas, user stories, job config, ETL code | These are the raw inputs to reverse engineering |
| 3 Spec | Forensic reverse-engineering output — live generation streams side-by-side with a reference run | Contradictions surface automatically with provenance; findings are stable run-to-run |
| 4 Regenerated | Schema + ETL rebuilt from spec alone — live generation streams side-by-side with a reference run | The spec is sufficient — original code not consulted |
| 5 Proof | Side-by-side code diff + equivalence check | Different code, identical business outputs |
| 6 New Feature | Avg-days-to-approval added from spec as launchpad | The spec enables new work, not just retrospective analysis |
| 7 Production Tickets | 7 WBB ServiceNow incidents | Production knowledge connects back to the spec |
| 8 Enriched Spec | Spec + operational history | One document serves delivery and L3 support |
| 9 FAQ | Generated from enriched spec | Knowledge made accessible without reading the spec |
| 10 L3 Chatbot | Embedded Claude chatbot | Knowledge made interactive — bounded by the spec |

---

## Prerequisites

- Python 3.9+
- An Anthropic API key (for Tabs 3, 4, and 10 — live generation and chatbot)

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/CGIDCSFred/wbb-workshop.git
cd wbb-workshop

# 2. Install dependencies
pip install -r requirements_streamlit.txt

# 3. Add your Anthropic API key
# Create .streamlit/secrets.toml with:
#   ANTHROPIC_API_KEY = "sk-ant-your-key-here"

# 4. Run the app
python -m streamlit run streamlit_app.py
```

Open **http://localhost:8501** in your browser. Use the `python -m streamlit …`
form (not a bare `streamlit run`) so the app uses the same interpreter the
dependencies were installed into.

The app seeds 30 days of synthetic onboarding data automatically on first run.

### Corporate networks (TLS inspection)

On a machine behind a TLS-inspecting proxy (e.g. Zscaler), the Anthropic SDK can
fail with `CERTIFICATE_VERIFY_FAILED` because Python's bundled CA set doesn't
include the corporate root cert. `requirements_streamlit.txt` includes
`pip-system-certs`, which makes Python trust the OS certificate store and
resolves this. If you still hit it, confirm the proxy client is healthy and its
root cert is installed in the OS trust store.

---

## Running the demo

### Act 1 — The live system (Tabs 1–2, ~3 min)

**Tab 1 — Live System**  
Show the onboarding platform running. Click "Add New Application" to show it's live. Point at the KPIs.

> *"This is the source system. Business banking customers applying for WBB products. The ETL pipeline reads from this database every night."*

**Tab 2 — Artifacts**  
Flip through the six artifacts: BRD, source schema, ETL extract. These are the standard delivery outputs.

> *"When we went to understand this system, here's what we had. Looks reasonable. But does the code actually do what the BRD says?"*

---

### Act 2 — Forensic reverse engineering (Tab 3, ~6 min)

**Tab 3 — Spec**  
Click **Generate Spec Live**. Claude reads all eight artifacts and streams the forensic specification.

While it runs (~90 seconds):

> *"The prompt gives Claude five rules: provenance for every claim, discrepancies preserved not resolved, gaps named not filled, no invented details, prose throughout. These rules are what make the output a forensic specification rather than a summary."*

When it finishes, scroll to **Section 6 — Discrepancies Found**. Walk through each finding:

1. **Date column drift** — BRD §5 says count by approval date. ETL uses submission date. The reporting view is counting the wrong date.
2. **Three-name field** — BRD: `business_segment`. Source: `business_category`. Warehouse: `segment`. Three names, one concept.
3. **Done but not implemented** — WBB-AW-011 ("Capture decline reason") marked Done. Extract carries `decline_description` to staging. Load never writes it. Warehouse has no column. Found only by tracing data flow.
4. **Orphaned reference** — `job_config.yaml` runs program `wbbaudit`. No `wbbaudit.py` exists. Pipeline fails at the audit step on every run.

> *"Four inconsistencies in a system built over five sprints by a small team. None visible from reading the BRD. They emerge from reading the code as evidence."*

---

### Act 3 — Regeneration from spec alone (Tab 4, ~5 min)

**Tab 4 — Regenerated**  
Click **Regenerate from Spec**. The original artifacts are not consulted — only the spec is sent to Claude.

While it runs:

> *"The regeneration claim is only honest if the regenerator has seen nothing but the spec. If you look at the original ETL code, the claim collapses. The spec has to be sufficient on its own."*

Show the output. The code looks different from the original — different variable names, different key formula. That's expected.

---

### Act 4 — The proof (Tab 5, ~4 min)

**Tab 5 — Proof**  
Click **Compare**. Both ETLs run against the same source data. The equivalence check runs automatically.

Point at the two charts — identical weekly volumes. Point at the green badge: **EQUIVALENT**.

Scroll down to the side-by-side code view.

> *"The code looks different. The outputs are identical. This is what we mean when we say the spec is canonical."*

Deliver the governance point:

> *"Run this quarterly. Every time someone changes the production system, regenerate from the spec and click Compare. If it passes, the spec is still valid. If it fails, you have a documented drift problem — not a mystery."*

---

### Act 5 — New feature from spec (Tab 6, ~3 min)

**Tab 6 — New Feature**  
Show the feature document (Step 1: feasibility check). All data elements are already in the warehouse. No schema change needed. Click **Live Report** to show the query running.

> *"The spec told us what was already there. We didn't have to read the code. We wrote the view against the spec's documented column names."*

---

### Act 6 — Production knowledge (Tabs 7–10, ~5 min)

**Tab 7 — Production Tickets**  
Show the seven incidents. Point out that four link directly to the seeded discrepancies — D1, D2, D3, D4.

> *"The spec predicted these tickets before they were raised."*

**Tab 8 — Enriched Spec**  
Show Section 8 — operational history joined to delivery knowledge in one document.

**Tab 9 — FAQ**  
Show the decline_description and column naming entries.

**Tab 10 — L3 Chatbot**  
Type: `The nightly job fails at the audit step — wbbaudit exits with program not found`  
→ **KNOWN PATTERN**, cites §8.2, gives resolution steps.

Type: `I'm trying to query fact_application for decline_description but the column doesn't exist`  
→ **KNOWN GAP**, cites §6 D3 and DEF-WBB-0048.

Type: `We're seeing a new error code PIIMASK-403 in the extract logs`  
→ **UNKNOWN — ESCALATE**

> *"The chatbot is bounded by the spec. It won't invent answers. The quality of the answers is determined by the quality of Section 8 — and Section 8 was written from evidence, not memory."*

---

## Fallback — if live generation fails

Pre-generated outputs are in `demo/fallback/`. If Tab 3 or Tab 4 generation is slow or fails, the tabs automatically show the fallback files — no action needed. A mid-stream network drop (e.g. a flaky corporate proxy) is caught: the tab shows a brief notice and leaves the pre-built version in place rather than surfacing an error. The Tab 10 chatbot likewise degrades to a friendly "try again" message instead of a traceback.

| Tab | Fallback location |
|-----|------------------|
| 3 Spec | `demo/fallback/wbbaw_spec_v1.md` |
| 4 Regenerated | `demo/fallback/regenerated/` |
| 6 New Feature | `demo/fallback/new_report.md` |
| 8 Enriched Spec | `demo/fallback/wbbaw_spec_section8.md` |
| 9 FAQ | `demo/fallback/wbbaw_faq.md` |

---

## The four seeded inconsistencies

These are deliberately planted. Do not fix them — they are the centrepiece of Act 2.

1. **Date column drift** — BRD §5 specifies that weekly volume counts by approval date. The ETL uses `submitted_dt` as the primary date key. `vw_weekly_onboarding_volume` counts by submission date, not approval date.

2. **Three-name field** — BRD: `business_segment`. Source schema: `business_category`. Warehouse: `segment`. Mapped correctly in the ETL, never reconciled in the BRD.

3. **Done but not implemented** — WBB-AW-011 ("Capture decline reason") is marked Done. The extract carries `decline_description` through staging. `wbbldr.py` never writes it. `fact_application` has no such column. No comment marks the absence — must be found by data flow tracing.

4. **Orphaned reference** — `job_config.yaml` step `audit` runs `wbbaudit`. No `wbbaudit.py` exists anywhere in the codebase.

---

## Key file map

| Path | What it is |
|------|-----------|
| `streamlit_app.py` | The 10-tab demo application |
| `requirements_streamlit.txt` | Python dependencies (`streamlit`, `pandas`, `anthropic`) |
| `.streamlit/config.toml` | Streamlit theme (TD blue) |
| `.streamlit/secrets.toml` | API key — **not committed to git** |
| `artifacts/brd_wbb_v1.1.md` | Business Requirements Document v1.1 |
| `artifacts/source_schema.sql` | WBB operational database DDL |
| `artifacts/target_schema.sql` | WBBAW warehouse DDL |
| `artifacts/user_stories_export.md` | User stories with acceptance criteria and status |
| `artifacts/job_config.yaml` | Nightly ETL job configuration |
| `artifacts/etl/wbbxtr.py` | Extract step |
| `artifacts/etl/wbbldr.py` | Load step |
| `artifacts/etl/wbb_common.py` | Shared utilities |
| `artifacts/servicenow_tickets_wbb.json` | 7 WBB-domain ServiceNow incidents |
| `prompts/01_reverse_engineering.md` | Reverse-engineering prompt |
| `prompts/02_regeneration.md` | Regeneration prompt |
| `prompts/03_new_report.md` | New feature prompt |
| `demo/fallback/wbbaw_spec_v1.md` | Pre-built forensic spec (fallback for Tab 3) |
| `demo/fallback/regenerated/` | Pre-built regenerated artifacts (fallback for Tab 4) |
| `demo/fallback/new_report.md` | Pre-built new feature document (fallback for Tab 6) |
| `demo/fallback/wbbaw_spec_section8.md` | Operational history section (Tab 8) |
| `demo/fallback/wbbaw_faq.md` | FAQ generated from enriched spec (Tab 9) |
| `spec/` | Live spec output saved here (Tab 3) |
| `regenerated/` | Live regeneration output saved here (Tab 4) |

---

## Applying this to real TD work

The WBB domain is fictional. The method transfers directly.

To apply this to a real TD programme stream:
1. Gather the existing artifacts — BRD, user stories, schema DDL, ETL code, job config
2. Use `prompts/01_reverse_engineering.md` as the template (the five rules do not change; the section structure may need adjusting for different system types)
3. The spec that comes out is auditable in a way an authored spec is not — every claim has a source, every contradiction is preserved
4. Use that spec to onboard new team members, validate the system before cutover, or extend the system safely
5. Enrich the spec with production ticket history to build an L3 support knowledge base

---

*Prepared by Frederick Ferguson, CGI — June 2026*
