# REBUILD.md — Reconstructing the WBB Spec-Driven Demo

**Audience:** a Claude instance running inside TD's environment, asked to rebuild
this demo from scratch.
**Goal:** reproduce the *WBB Spec-Driven Development Demo* — a single Streamlit
app that demonstrates forensic reverse engineering, regeneration from a spec,
proof of equivalence, spec-driven extension, spec-derived validation, runtime
version-drift forensics, and a spec-bounded L3 support chatbot — adapting it to
TD IT constraints (no Docker, restricted network, possibly no live LLM API).

This document is itself a *specification* — it is sufficient to rebuild a
semantically equivalent demo. Implementation details (naming, layout) are yours
to choose; what must transfer is the meaning, the data model, the five planted
inconsistencies, and the behaviour of each tab.

---

## 0. How to use this document

1. Read **§1 (TD constraints)** first and decide the run mode: **offline-first**
   (no live API — recommended for TD) or **live** (Anthropic API available).
2. Build in the order given in **§13 (Build sequence)**.
3. Author the artifacts in **§6** so the five inconsistencies in **§5** are
   reproduced *exactly* — they are the centrepiece; do not "fix" them.
4. Bake in the implementation notes in **§12** — they are real bugs already paid
   for; don't rediscover them.
5. Verify against **§14 (Acceptance checklist)**.

Work iteratively and ask the operator (the TD presenter) when a constraint is
ambiguous — e.g. whether an Anthropic API key is available, whether PyPI is
reachable, and what the corporate proxy/cert situation is.

---

## 1. TD environment constraints & adaptations

Assume a locked-down corporate Windows machine. Confirm each with the operator.

| Constraint | Adaptation |
|---|---|
| **No Docker / container runtime** | The demo already needs none. It runs as one Streamlit process over a local SQLite file. Any `docker-compose.yml` is only ever *generated as text* (an illustrative regeneration artifact), never executed — see §11. |
| **Restricted PyPI access** | Try `pip install -r requirements.txt` first; corporate networks often proxy PyPI through an internal mirror (Artifactory/Nexus). If blocked, ask the operator for the internal index URL (`pip install -i <url> ...`) or a wheels directory. Keep the dependency set tiny: `streamlit`, `pandas`, and (only if running live) `anthropic`. |
| **Corporate TLS inspection (Zscaler etc.)** | Python's bundled CA set won't include the corporate root, so HTTPS (pip, the Anthropic SDK) can fail with `CERTIFICATE_VERIFY_FAILED`. Fix: add `pip-system-certs` to requirements (makes Python trust the OS/Windows cert store), or set `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` to the corporate CA bundle. The browser/`curl` already trust it; Python just needs pointing at the same store. |
| **No Anthropic API key, or LLM API egress blocked** | Run **offline-first** (§11): pre-generate the spec, regeneration, FAQ, operational-history, new-report, and spec-derived test content as static files at *build* time, and ship a *scripted* chatbot. The running demo then needs **no network at all**. Treat live generation as an optional enhancement only if a key + egress exist. |
| **No admin rights** | Install with `pip install --user`, run from a user-writable folder, bind Streamlit to localhost. No services, no system changes. |
| **Python present** | Target Python 3.9+. Launch with `python -m streamlit run app.py` (the `python -m` form guarantees the same interpreter the deps were installed into). |

> If a corporate Claude/LLM gateway is available instead of the public Anthropic
> API, the live tabs can target that gateway — but offline-first is the safest
> default for a live audience.

---

## 2. What you are building

A fictional **web-banking onboarding platform (WBB)** where SMBs apply for
business-banking products, and its **analytics warehouse (WBBAW)**. The demo
walks an end-to-end arc and proves a thesis: *a forensic specification,
reverse-engineered from a system's own artifacts, is auditable, sufficient to
regenerate the system, durable enough to serve as an L3 support knowledge base,
and able to generate the tests that pin its own claims.*

The arc: **live system → forensic spec → regeneration from spec alone → proof of
equivalence → new feature from spec → production-support knowledge → validation
& version-drift forensics.**

It is delivered as a **12-tab** Streamlit app run as a **7-act** presentation
(§10, §15).

The domain is entirely synthetic — no TD data or IP. It is *structurally* like a
real modernisation (legacy ETL → warehouse, drifted docs, a platform refresh
that breaks a load-bearing runtime assumption) so the method transfers, without
copying anything real.

---

## 3. Tech stack & project layout

- **Python 3.9+**, **Streamlit** (UI), **pandas** (tables/charts), **sqlite3**
  (stdlib — the database). Optional **anthropic** SDK for live generation.
- **One database file** (`wbb_demo.db`), SQLite with `PRAGMA journal_mode=WAL`,
  seeded on first run. No external services.

Suggested layout:

```
wbb-workshop/
  app.py                      # the 12-tab Streamlit app (the whole demo)
  requirements.txt            # streamlit, pandas, [anthropic], pip-system-certs
  .streamlit/
    config.toml               # theme (TD blue)
    secrets.toml              # ANTHROPIC_API_KEY (only if live) — never commit
  artifacts/                  # the inputs the reverse-engineering reads (TEN files)
    brd_wbb_v1.1.md
    source_schema.sql
    target_schema.sql
    user_stories_export.md
    job_config.yaml
    runtime_environment.md     # runtime/version history — REQUIRED to discover D5
    servicenow_tickets_wbb.json
    etl/ wbbxtr.py  wbbldr.py  wbb_common.py  requirements.txt
  prompts/
    01_reverse_engineering.md
    02_regeneration.md
    03_new_report.md
    04_generate_tests.md       # spec-derived tests + golden data (Tab 11)
  fallback/                   # pre-generated outputs (offline-first; see §11)
    wbbaw_spec_v1.md
    wbbaw_spec_section8.md
    wbbaw_faq.md
    new_report.md
    test_wbbaw_from_spec.py    # spec-derived pytest suite shown in Tab 11
    regenerated/ source_schema.sql  target_schema.sql  etl/extract.py ...
  spec/                       # live spec output (if live mode)
  regenerated/                # live regen output (if live mode)
```

`.gitignore` must exclude `.streamlit/secrets.toml` and `*.db`.

---

## 4. Domain model

### 4.1 Domain constants

```python
SEGMENTS = ["RETAIL","TECHNOLOGY","CONSTRUCTION","HOSPITALITY",
            "PROFESSIONAL_SERVICES","HEALTHCARE","MANUFACTURING","LOGISTICS"]
SIZES = ["MICRO","SMALL","MEDIUM","LARGE"]
# Approval probability by company size — gives realistic, size-correlated rates
APPROVAL_RATE = {"MICRO":0.32, "SMALL":0.48, "MEDIUM":0.61, "LARGE":0.74}
STATUSES = ["SUBMITTED","IN_REVIEW","APPROVED","DECLINED","ABANDONED"]
```

Company names are generated from prefixes (Apex, Summit, Pacific, Northern,
Capital, Heritage, Metro, Pioneer, …) × suffixes (Corp, Inc, Ltd, Group,
Solutions, Partners, Holdings, …). Decline reasons come from a small reference
set across categories CREDIT_RISK / DOCUMENTATION / COMPLIANCE / FRAUD /
CAPACITY / OTHER.

### 4.2 Source (operational) schema — SQLite

```sql
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    business_category TEXT NOT NULL,     -- NOTE: source name for the segment (see §5 D2)
    company_size TEXT NOT NULL,          -- MICRO/SMALL/MEDIUM/LARGE
    contact_email TEXT,
    is_test INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE onboarding_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status TEXT DEFAULT 'SUBMITTED',     -- one of STATUSES
    submitted_at TEXT DEFAULT (datetime('now')),
    decided_at TEXT,                     -- set when APPROVED/DECLINED (the approval date, see §5 D1)
    assigned_to TEXT
);
CREATE TABLE banking_products (id INTEGER PRIMARY KEY, product_name TEXT, product_code TEXT UNIQUE);
CREATE TABLE decline_reasons_ref (reason_code TEXT PRIMARY KEY, reason_text TEXT, category TEXT);
CREATE TABLE application_decline_reasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER, reason_code TEXT, reason_text TEXT, category TEXT
);
```

Both a submission date and a decision/approval date exist on every decided
application — this is what makes D1 (counting by the wrong one) reconstructible.

### 4.3 Warehouse schema — SQLite (two copies: `wh_*` original, `regen_*` regenerated)

```sql
CREATE TABLE wh_dim_customer (
    customer_key INTEGER PRIMARY KEY,
    customer_id  INTEGER UNIQUE,
    company_name TEXT,
    segment      TEXT,                   -- NOTE: warehouse name for the segment (see §5 D2)
    company_size TEXT,
    etl_at       TEXT
);
CREATE TABLE wh_fact_application (
    app_key             INTEGER PRIMARY KEY,
    application_id      INTEGER UNIQUE,
    customer_key        INTEGER,
    submitted_year_week TEXT,            -- NOTE: keyed on SUBMISSION date (see §5 D1)
    is_approved         INTEGER DEFAULT 0,
    is_declined         INTEGER DEFAULT 0,
    decision_days       REAL,
    etl_at              TEXT
    -- NOTE: there is deliberately NO decline_description column (see §5 D3)
);
-- regen_dim_customer / regen_fact_application: identical column shape, separate tables.
```

Seed ~30 days of history on first run: for each of the last 30 days, insert
6–18 applications with random segment/size, a realistic submitted→decided gap
(1–10 days), and status drawn so the approval rate tracks `APPROVAL_RATE[size]`.
Exclude `is_test=1` and `ABANDONED` from ETL.

---

## 5. The five seeded inconsistencies — the calibration (reproduce EXACTLY)

These are **deliberately planted** across the artifacts and are the whole point
of the demo. The reverse-engineering pass is designed to discover them. **Do not
fix them, do not annotate them as errors, do not let any artifact silently
resolve them.** Each must be reconstructible by tracing the artifacts.

1. **D1 — Date column drift.** The BRD (§5) states weekly volume metrics are
   counted by **approval date**. The ETL loads **submission date** as the primary
   date key (`submitted_year_week` / `submitted_date_key`, derived from
   `submitted_at`/`submitted_dt`). The warehouse reporting view
   `vw_weekly_onboarding_volume` counts by submission date, not approval date.
   Both dates exist on the source; the wrong one is used as the primary.

2. **D2 — Three names, one concept.** The BRD (§3) calls the customer
   classification **`business_segment`**. The source schema uses
   **`business_category`**. The warehouse uses **`segment`**. The ETL maps them
   correctly; the rename is noted in user story **WBB-AW-006**'s comments as a
   deferred BRD update that was *promised but never delivered* in the artifacts.

3. **D3 — Done but not implemented.** User story **WBB-AW-011** ("Capture decline
   reason for rejected applications") is marked **Done** with all acceptance
   criteria checked. The extract (`wbbxtr.py`) performs the join and carries
   **`decline_description`** through to staging. The load (`wbbldr.py`) **never
   persists it**, and `fact_application` has **no column** to hold it. There is
   **no comment** marking the absence — it must be found by tracing the data
   flow.

4. **D4 — Orphaned reference.** `job_config.yaml` has a step `audit` that runs
   program **`wbbaudit`**. **No `wbbaudit.py` exists** anywhere in the codebase,
   and the word "audit" appears in no Python file. The nightly job references a
   program that does not exist.

5. **D5 — Runtime version drift.** The ETL computes surrogate keys in
   *application code* with Python's **salted built-in `hash()`** over a tuple
   containing a string — `wbbldr.py`:
   `customer_key = abs(hash(('cust', customer_id))) & ((1 << 63) - 1)` — which is
   stable **only while `PYTHONHASHSEED` is pinned**. The legacy Debian-11 base
   image pinned `PYTHONHASHSEED=0` (recorded in `runtime_environment.md` §3); the
   **2026-04-28** platform refresh (CHG-WBB-0058: Python 3.10.13→3.12.3,
   psycopg2 2.9.5→2.9.9, Debian 11→12, base image standardised) **dropped the
   legacy overrides with no application-code change** (`runtime_environment.md`
   §4). From the 2026-04-29 run onward, returning customers' `customer_key`
   diverged: the dimension upsert keeps the **old** key (`ON CONFLICT(customer_id)`)
   while the fact load writes the **new** one, so the fact→dim foreign key no
   longer resolves and the nightly load aborts with FK violations — reported as
   **`INC-WBB-0018`** (P1). Planted across **three** artifacts (`wbbldr.py` key
   code, `runtime_environment.md` §3/§4, and `INC-WBB-0018`); discoverable only
   by **correlating the version history with the incident timeline**.

   > **Crucial distinction.** D5 is an *environment/operational* discrepancy,
   > surfaced in Tab 12 by reading the artifacts — it is **not** a behaviour of
   > the running ETL *simulators* and does **not** affect the equivalence proof.
   > The simulators (§8) must stay deterministic (use `hashlib`, never `hash()`),
   > or Tab 5 breaks. The *fictional original* `wbbldr.py` is the only place that
   > uses the salted `hash()` — that is the plant, and it is never executed.
   > The forensic spec foreshadows D5 as an unassessed risk in its own
   > **§4.4 / Q4**; D5 is that open question resolved with operational evidence.

**Five of the eight** ServiceNow tickets (§6) map onto D1, D2, D3, D4, D5 — "the
spec predicted the tickets." The other three are unrelated open issues.

---

## 6. The artifacts to author

Author these so a reader (and the reverse-engineering prompt) can reconstruct
the system and discover D1–D5. Keep them realistic and internally *plausible*,
with the inconsistencies planted as described.

- **`brd_wbb_v1.1.md`** — Business Requirements Document. Includes §3 using
  `business_segment` (D2) and §5 specifying weekly volume **by approval date**
  (D1). Otherwise a normal BRD: scope, the onboarding→warehouse purpose, metrics,
  reporting views (`vw_weekly_onboarding_volume`).
- **`source_schema.sql`** — operational DDL using `business_category` (D2), the
  applications table with `submitted_at`/`submitted_dt` and a decision/approval
  date.
- **`target_schema.sql`** — warehouse DDL: `dim_customer` (with `segment`, D2),
  `fact_application` keyed on submission week (D1), **no decline column** (D3),
  and the reporting views.
- **`user_stories_export.md`** — sprint stories with status + acceptance
  criteria. WBB-AW-006 documents the segment rename as a deferred BRD update
  (D2). WBB-AW-011 is marked **Done** for "capture decline reason" (D3).
- **`job_config.yaml`** — the nightly batch: ordered steps (extract, load, …) with
  a step `audit` invoking `wbbaudit` (D4). Include realistic SYSIN-style params.
- **`etl/wbbxtr.py`** (extract) — reads source, maps `business_category`→segment,
  derives submission week, and **joins decline reasons / carries
  `decline_description` into staging** (D3 part 1). Targets Postgres/psycopg2
  (illustrative; never executed in the demo).
- **`etl/wbbldr.py`** (load) — writes the dimension and fact, keyed on submission
  week (D1), and **does not write `decline_description`** (D3 part 2). Computes
  surrogate keys with **salted built-in `hash()` over a string-bearing tuple**
  (D5 — `abs(hash(('cust', customer_id))) & ((1<<63)-1)`), with an innocent
  comment claiming "re-running for the same source data produces the same
  surrogate keys." **Keep this `hash()` exactly** — it is the D5 plant. (Do not
  confuse it with the in-app simulators of §8, which must use `hashlib`.)
- **`etl/wbb_common.py`** — shared helpers (connection, surrogate keys, week
  derivation).
- **`etl/requirements.txt`** — pinned ETL runtime dependencies (psycopg2-binary,
  PyYAML, …). Part of the runtime evidence for D5.
- **`runtime_environment.md`** — the runtime/version history (doc ID e.g.
  WBB-OPS-AW-007, owned by Platform SRE). Records the current environment, a
  runtime-configuration table showing **`PYTHONHASHSEED=0` (legacy) → unset
  (current)**, and a dated **deployment & upgrade history** whose **2026-04-28**
  row is the platform refresh (CHG-WBB-0058) that dropped the legacy overrides
  with no code change. Add a reproducibility note that key stability is a
  function of the runtime, *not the schema*, and is undocumented in the BRD /
  stories / code comments. This is the artifact that makes D5 discoverable.
- **`servicenow_tickets_wbb.json`** — **8** WBB-domain incidents; **5 map to
  D1–D5** (e.g. "weekly dashboard counts by submission not approval" → D1; "which
  column is the segment?" → D2; "decline_description column missing" → D3;
  "nightly job fails at audit step — wbbaudit not found" → D4; **"nightly load
  fails with foreign-key violations on fact_application after the 2026-04-28
  platform refresh"** → D5, `INC-WBB-0018`, P1, with L3 work-notes that trace the
  onset to CHG-WBB-0058). The other 3 are unrelated open issues. Each mapped
  ticket carries a `spec_link` (e.g. `"Spec §6 D5, §4.4, §7 Q4"`).

> The artifacts are the *fictional original*. They describe a Postgres system and
> are **never run**. What actually executes in the demo are the in-app ETL
> *simulators* in §8.

---

## 7. The four prompts (verbatim)

Reproduce these as `prompts/01..04`. The five rules and seven sections of prompt
01 are fixed.

### `prompts/01_reverse_engineering.md`

> You are acting as a forensic analyst reverse-engineering an existing system
> from its project artifacts. Your job is to reconstruct what was built and what
> was intended, not to design a good system. Treat the artifacts as evidence,
> not as a brief.
>
> **Context.** The system is an ETL pipeline that extracts customer onboarding
> data from an operational web-banking platform (WBB) and loads it into an
> analytics warehouse. The artifacts (BRD, user stories, source/target schema
> DDL, ETL code, job config) are what the team produced over several sprints.
> They are not internally consistent. This is normal and expected.
>
> **Task.** Produce a specification that reconstructs the system from these
> artifacts, sufficient for a separate team — given only your spec — to build a
> system with equivalent semantics (same grain, conformed dimensions, business
> answers, transformation rules). Their implementation may differ in naming and
> structure; meaning must transfer.
>
> **Rules you must follow:**
> 1. **Provenance for every claim.** Every rule, mapping, column, constraint, and
>    behaviour cites the artifact it came from, e.g. `[BRD §2.3]`,
>    `[wbbxtr.py, EXTRACT_QUERY]`. No artifact support → don't include it.
> 2. **Surface discrepancies, do not resolve them.** When artifacts disagree,
>    record both positions, cite and quote both, add a short analyst note on the
>    likely as-built behaviour — but leave the discrepancy in the spec for human
>    resolution.
> 3. **Name gaps, do not fill them.** If an artifact doesn't tell you something
>    the spec needs (SLA, retention, failure mode, ownership), write "Not
>    specified in available artifacts" and add it to Open Questions. Do not
>    invent values.
> 4. **Prose, not JSON.** Full sentences and paragraphs. Tables OK for column
>    mappings and discrepancy summaries. No JSON/YAML/dense schemas.
> 5. **Stay forensic.** Reconstruct what exists, don't improve it. Document
>    apparent mistakes as-built with an observation; never silently correct.
>
> **Output structure — exactly these sections, in order:**
> 1. System Overview · 2. Source System · 3. Target System ·
> 4. Transformation Rules · 5. Operational Behaviour ·
> 6. Discrepancies Found · 7. Open Questions
>
> Save to `spec/wbbaw_spec_v1.md`.

> **Attach the ten artifacts:** the BRD, both schemas, the user stories, the job
> config, the three ETL files (`wbbxtr.py`, `wbbldr.py`, `wbb_common.py`), **the
> runtime environment doc (`runtime_environment.md`), and the dependency manifest
> (`etl/requirements.txt`)**. The runtime environment + dependency manifest are
> **not optional** — D5 is only reconstructible if the reverse-engineering can
> read the version history against the surrogate-key code. (The prompt file's own
> "how to use" header lists eight code/doc artifacts; the running demo attaches
> all ten, the two runtime artifacts included.)

### `prompts/02_regeneration.md`

> Open a **fresh context with no memory of the artifacts. Attach only
> `spec/wbbaw_spec_v1.md`.** Do not look at the original code — the regeneration
> claim is that the spec alone is sufficient.
>
> You are a software engineer implementing a system from a specification. You
> have not seen the original system and must not ask for it. Build a complete,
> runnable implementation of the WBBAW ETL that produces the **same business
> answers** as the original on equivalent input, with the **same grain,
> dimension structure, and transformation rules** as the spec. Naming and code
> structure are yours; **semantics must match, syntax need not.**
>
> Produce: `regenerated/source_schema.sql`, `regenerated/target_schema.sql`,
> `regenerated/etl/extract.py`, `regenerated/etl/load.py`,
> `regenerated/etl/common.py`. *(In a no-Docker TD environment, omit the
> `docker-compose.yml` deliverable — it is never executed here.)*
>
> If the spec is unclear, implement the most conservative interpretation and
> comment the ambiguity. Do not add features the spec doesn't describe. **Do not
> "fix" things that look wrong** — the spec may be documenting as-built
> behaviour; replicate it.

### `prompts/03_new_report.md`

> Open a fresh context. Attach only `spec/wbbaw_spec_v1.md` (not the artifacts or
> regenerated code).
>
> A stakeholder requests: **"Average days from application submission to
> approval, broken down by business segment"** (approved applications only;
> show segment, avg days, count, and period covered). Operations wants to know
> whether some segments take longer to approve.
>
> Produce: **(1)** a feasibility check — does the warehouse already hold what's
> needed, citing the spec's columns/tables; **(2)** a spec amendment if anything
> is missing (in the spec's style, with provenance, gaps named); **(3)** the SQL
> view `vw_avg_days_to_approval_by_segment`, addable with one `CREATE VIEW` and
> no schema change, with reasoning; **(4)** a verification query a reviewer could
> run to sanity-check it.

### `prompts/04_generate_tests.md`

> Open a fresh context. Attach only `spec/wbbaw_spec_v1.md` — no artifacts, no
> code. Tests and golden data must be derived from the spec alone. The spec
> defines what "correct" means; this prompt turns it into an executable
> regression suite, closing the governance loop (regenerate → prove with
> spec-derived tests on spec-derived data).
>
> **Rules (inherited from the spec's discipline):**
> 1. **Every test cites the spec** (e.g. `# [Spec §6 D1]`).
> 2. **Characterization, not aspiration.** Section 6 documents *as-built*
>    behaviour; assert the system behaves as-built, quirks included. A test that
>    asserts the "intended" behaviour instead of the documented one is wrong.
> 3. **Open Questions become skipped tests** (`@pytest.mark.skip(reason="Spec §7: …")`)
>    so the gap is visible as missing coverage.
> 4. **Golden data is designed, not random** — cover the boundaries the spec
>    implies, with the spec-dictated outcome.
>
> **Produce:** (1) a pytest suite grouped into *Transformation rules* (grain,
> approval/decline flags, exclusions, decision-day computation, surrogate-key
> uniqueness), *Characterization (as-built)* — one test per Section-6 discrepancy
> (fact keyed on submission not approval = D1; segment renamed source→warehouse =
> D2; decline reason **not** persisted = D3; job references a non-existent program
> = D4) — and *Equivalence* (original vs regenerated produce identical weekly
> volume / approval-by-segment on the same input). (2) A small **golden dataset**
> covering a normal approval, a decline-with-reason, an undecided application, an
> abandoned application (excluded), a test customer (excluded), and a **week-boundary
> case** (submitted one ISO week, decided the next — pins the submission-date
> keying, D1). (3) A short "how to run" note making the point that a failing
> characterization test means someone changed the as-built behaviour (drift), not
> that the test is wrong.

---

## 8. The two ETL simulators (what actually runs)

In `app.py`, write two functions that read the *same* source tables and load the
two warehouses. They must be written **differently** (different variable names,
query style, and surrogate-key formula) to model independently-authored code,
yet produce **identical business outputs**.

Both, per application (excluding `is_test=1` and `ABANDONED`):
- Upsert one `dim_customer` row per customer (segment ← source `business_category`).
- Upsert one `fact_application` row: `submitted_year_week` from **submission**
  date (D1), `is_approved`/`is_declined` from status, `decision_days` =
  `decided_at − submitted_at` in days.
- **Neither persists a decline description** (D3) — there is no column.

### ⚠️ Simulator surrogate keys MUST be deterministic across processes

Do **not** use Python's built-in `hash()` **in the simulators** — it is
randomized per process (`PYTHONHASHSEED`). If the dim is loaded in one process
and the fact in another (any app restart), keys diverge and the fact→dim join
silently breaks, making the equivalence proof show false non-equivalence. Use
`hashlib`:

```python
import hashlib
def surr_key_orig(prefix, id_):   # original ETL simulator
    return int(hashlib.sha256(f"orig|{prefix}|{id_}".encode()).hexdigest(), 16) % (2**63)
def surr_key_regen(prefix, id_):  # regenerated ETL simulator — different VALUES, same guarantee
    return int(hashlib.md5(f"{prefix}:{id_}".encode()).hexdigest(), 16) % (2**63)
```

Different formulas → different key *values* (demonstrating independent code),
both deterministic → the join always holds.

> **Do not "fix" the artifact `wbbldr.py` to match this.** The *fictional
> original* (§6) deliberately uses the salted built-in `hash()` — that is the D5
> plant, and it is never executed. The `hashlib` rule here applies **only** to
> the in-app simulators. Two layers, opposite requirements, both intentional:
> the simulators stay green (proof), the artifact carries the bug (forensics).

---

## 9. Business queries & the equivalence proof

Implement two parameterised queries that run against either warehouse:
- **Weekly volume** — count and approved-count by `submitted_year_week`.
- **Approval rate by segment** — `segment, total, approved, approval_rate_pct`
  (join fact→dim).

The **equivalence check** runs both ETLs against the current source, then
compares the outputs. If weekly volumes **and** approval counts match across the
two warehouses → show a green **EQUIVALENT** badge; otherwise a red **DIVERGENT**
notice. (Note: compute the badge on weekly volume + approval counts; with
deterministic keys the segment tables will also match — verify both, so the
badge and the visible segment tables never contradict each other.)

These same two queries are the **Equivalence** group of the spec-derived test
suite (§7, prompt 04) and are re-used by the Validation tab (§10, Tab 11).

---

## 10. The twelve tabs

| # | Tab | Behaviour |
|---|-----|-----------|
| 1 | **Live System** | KPIs (total/approved/declined/pending, approval rate), "Add New Application" button, recent-applications table, a status bar chart for the last 30 days. Reads/writes the source DB live. |
| 2 | **Artifacts** | Render the artifact bundle (BRD, schemas, user stories, job config, ETL files, **runtime environment doc, requirements**) for browsing. |
| 3 | **Spec** | Show the forensic spec. **Live mode:** "Generate Spec Live" streams prompt 01 + the **ten** artifacts, side-by-side with the pre-built reference (equal columns; capture reference text *before* overwriting; no rerun so both stay for comparison). **Offline mode:** show `fallback/wbbaw_spec_v1.md`. Always show the "5 discrepancies" callout. |
| 4 | **Regenerated** | Same side-by-side pattern for prompt 02 (spec only). Also expose the curated regenerated artifacts (clean schema + extract). |
| 5 | **Proof** | "Compare" runs both ETLs, shows weekly-volume charts/tables side by side, the **EQUIVALENT** badge (§9), the approval-by-segment tables, and a side-by-side code diff (original vs regenerated). |
| 6 | **New Feature** | Show the new-report feasibility doc (prompt 03 output); "Live Report" runs `vw_avg_days_to_approval_by_segment` against the warehouse. |
| 7 | **Production Tickets** | Render the **8** ServiceNow incidents; highlight the **5** mapped to D1–D5. |
| 8 | **Enriched Spec** | Spec + an operational-history "Section 8" (ticket patterns folded into the spec). |
| 9 | **FAQ** | FAQ generated from the enriched spec (decline_description gap, segment naming, audit-step failure, version-drift FK failures, etc.). |
| 10 | **L3 Chatbot** | Spec-bounded assistant. **Live mode:** Anthropic call with a system prompt = enriched spec + Section 8, instructed to answer ONLY from the spec and classify each ticket as **KNOWN PATTERN** / **KNOWN GAP** / **UNKNOWN — ESCALATE**, citing spec sections. **Offline mode:** a scripted classifier that pattern-matches the known demo tickets to canned responses (see §11). |
| 11 | **Validation** | "Run validation suite" loads both warehouses and evaluates spec-derived checks (transformation rules + **characterization rows that assert D1–D4 as-built** — a future "fix" turns the suite red). Shows a designed **golden dataset** (incl. a week-boundary case pinning D1) and the reference pytest module (`fallback/test_wbbaw_from_spec.py`, from prompt 04). Runs deterministically — **no API**. |
| 12 | **Version Drift** | Surfaces **D5**. A single chronological axis interleaves the runtime/version events (from `runtime_environment.md` §4) with the incidents, showing the **2026-04-28** refresh immediately followed by **INC-WBB-0018 the next day**. Walks the D5 provenance chain (code → environment → history → incident) and ties it to the spec's §4.4 / Q4. Fully **offline/deterministic** — no API. |

UI: TD-blue theme, wide layout. Tabs 1, 2, 5–9, **11, 12** are fully offline; 3,
4, 10 use the API only in live mode.

---

## 11. Offline-first generation strategy (recommended for TD)

The robust default when an API key/egress is uncertain: **generate at build
time, serve static at run time.**

1. **At build time** (you, the building Claude, with the operator): produce the
   spec, the regenerated artifacts, the new-report doc, the Section 8
   operational history, the FAQ, and the **spec-derived test suite + golden
   data** — by running the prompts in §7 yourself — and save them as files under
   `fallback/`. These become the demo's content.
2. **At run time**, every tab reads those static files. The app needs **no
   network**: Tabs 3/4/6/8/9 display the pre-built content; the proof (Tab 5),
   validation (Tab 11), and version-drift (Tab 12) tabs run purely on local
   SQLite and the static artifacts.
3. **Tab 10 chatbot without an API:** ship a scripted classifier. Hard-code the
   handful of demo tickets to their classifications and cite the relevant spec
   section:
   - "audit step / wbbaudit not found" → **KNOWN PATTERN** (cite §8 / D4)
   - "decline_description column missing" → **KNOWN GAP** (cite §6 / D3)
   - "weekly volume by submission not approval" → **KNOWN PATTERN/GAP** (D1)
   - "which column is the segment" → answer from D2
   - "FK violations on fact_application after the platform refresh" → **KNOWN
     PATTERN** (cite §6 D5 / §4.4 / INC-WBB-0018)
   - anything unrecognised → **UNKNOWN — ESCALATE**
4. **If a key + egress *are* available**, wire the live path *in addition* (a
   "Generate Live" button), but keep the static fallback so a network blip never
   breaks the demo. Wrap every streaming call in try/except and degrade to the
   fallback with a friendly notice (§12).

This sidesteps TD API-access uncertainty entirely while preserving the full
narrative. Note Tabs 11 and 12 carry **no** live-API path at all — they are
deterministic by design, which makes the closing acts the safest in the run.

---

## 12. Hard-won implementation notes (bake these in)

These were paid for the hard way — incorporate them from the start.

1. **Deterministic simulator surrogate keys** (§8). Never built-in `hash()` *in
   the simulators*. This is the one bug that silently breaks the equivalence
   proof. **But** the *artifact* `wbbldr.py` must keep its salted `hash()` — that
   is D5 (§5). Don't unify them: simulators use `hashlib`, the never-run artifact
   uses `hash()`.
2. **Graceful network failure.** Wrap any live streaming call in try/except:
   on a mid-stream drop, show a one-line "interrupted — showing pre-built
   version" notice and leave the fallback in place; **write the live output file
   only on a clean finish** so a partial run never overwrites good content. The
   chatbot likewise shows a friendly "try again" message, never a traceback, and
   never persists an error turn into history.
3. **`max_tokens` sizing.** The spec finishes around ~12–14k output tokens; set
   the ceiling to ~16k so it completes (`end_turn`, not truncated). The
   regeneration is verbose (full multi-file rebuild) and can exceed any
   reasonable cap — bound it and accept a tail cutoff, or (better) pre-generate
   it at build time. Don't chase it with ever-higher caps (slower, still
   truncates).
4. **Side-by-side generation layout.** Render live generation in an equal-width
   column next to the reference — *not* inside the narrow button column, or it
   gets visually squeezed. Capture the reference text *before* the live run
   overwrites the file; don't `st.rerun()` after, so both panels stay for
   comparison.
5. **Corporate certs.** `pip-system-certs` (or `truststore`) so Python trusts the
   OS cert store; otherwise the SDK 400s with `CERTIFICATE_VERIFY_FAILED` behind
   TLS inspection.
6. **Launch** with `python -m streamlit run app.py` (not bare `streamlit run`),
   so it uses the interpreter the deps were installed into.
7. **Equivalence badge consistency.** Compute the badge from weekly volume +
   approval counts, but also render the segment tables — with deterministic keys
   both match, so the green badge and the visible tables agree (avoid the trap
   where the badge is green while a dim-join bug makes the segment tables differ).
8. **Version-drift tab is offline & deterministic.** Hardcode the runtime-event
   timeline (from `runtime_environment.md` §4) in the app so Tab 12 renders with
   no API and no parsing fragility; read the incidents from the tickets JSON and
   sort both onto one date axis. The D5 signal is the **next-day adjacency**
   (refresh on 2026-04-28, INC-WBB-0018 opened 2026-04-29), not raw incident
   volume — make the caption say so.
9. **Arrow/serialization in tables.** When rendering mixed-type rows
   (timeline/golden data) via `st.dataframe`, keep column dtypes consistent
   (stringify dates you've already formatted) to avoid pandas/Arrow conversion
   warnings.

---

## 13. Build sequence

1. Confirm constraints with the operator (§1): API key? PyPI/proxy? cert store?
2. Scaffold the project (§3); write `requirements.txt`; resolve the cert/proxy
   issue so `pip install` works.
3. Build the **data layer**: schema (§4), seeding, the two ETL simulators (§8),
   the queries + equivalence check (§9). Get Tab 5 green first — it's the
   linchpin and the hardest to get right (deterministic keys).
4. Author the **artifacts** (§6) with D1–D5 planted exactly (§5) — including
   `runtime_environment.md`, `etl/requirements.txt`, and the salted-`hash()`
   `wbbldr.py` and `INC-WBB-0018` that together carry D5.
5. Write the **prompts** (§7), all four.
6. **Generate the content** for offline-first mode (§11) and save to `fallback/`
   — spec, regenerated, new-report, Section 8, FAQ, **and the spec-derived test
   suite + golden data**.
7. Build the **12 tabs** (§10) reading the static content; add live paths to
   Tabs 3/4/10 if a key exists (with graceful fallback, §12). Tabs 11 and 12 are
   offline/deterministic.
8. Theme it (TD blue), wire the 7-act flow.
9. Run the **acceptance checklist** (§14).

---

## 14. Acceptance checklist

- [ ] App launches with `python -m streamlit run app.py`; no network required in
      offline mode.
- [ ] First run seeds ~30 days of data; Tab 1 KPIs and chart render.
- [ ] **Tab 5 → Compare shows a green EQUIVALENT badge**, *and* the
      approval-by-segment tables match across both warehouses (restart the app
      and re-Compare — still green; this catches the simulator `hash()` bug).
- [ ] The spec (Tab 3) reconstructs **D1–D4** with provenance citations in the
      7-section structure, and foreshadows **D5** as an open question (§4.4 / Q4),
      ending cleanly.
- [ ] Tab 4 shows regenerated code that is *syntactically different* but
      semantically equivalent.
- [ ] Tab 6 runs the avg-days-to-approval view from the spec.
- [ ] Tabs 7–9 render tickets / enriched spec / FAQ; **5 of 8** tickets map to
      D1–D5.
- [ ] Tab 10 classifies the demo tickets correctly (live or scripted), including
      the D5 FK-violation ticket, and never shows a traceback.
- [ ] **Tab 11** runs the spec-derived suite; the characterization rows pass
      *because* the system is as-built (D1–D4) and would turn red on a "fix";
      golden data incl. the week-boundary case renders.
- [ ] **Tab 12** interleaves runtime events and incidents on one axis, shows the
      2026-04-28 → INC-WBB-0018 next-day adjacency, and walks the D5 provenance
      chain — with **no API**.
- [ ] No live tab crashes when the network/API is unavailable — it degrades to
      the fallback with a friendly notice.
- [ ] The **five** inconsistencies are **present and unfixed** in the artifacts
      (incl. the salted `hash()` in the *artifact* `wbbldr.py`).

---

## 15. The seven-act talk track

- **Act 1 — Live system (Tabs 1–2, ~3 min).** "This is the source system —
  SMBs onboarding to WBB. Every night an ETL feeds an analytics warehouse. Here
  are the delivery artifacts — including the runtime environment. They look
  complete — but does the code do what the BRD says?"
- **Act 2 — Forensic reverse engineering (Tab 3, ~6 min).** Generate (or show)
  the spec; walk **Section 6 — Discrepancies**: D1 date drift, D2 three-name
  field, D3 done-but-not-built, D4 orphaned `wbbaudit`. "Four inconsistencies
  built over five sprints, none visible from the BRD — they emerge from reading
  the code as evidence, each with a citation. And the spec flags a fifth as an
  open question (§4.4 / Q4): is key stability tied to the runtime? Hold that."
- **Act 3 — Regeneration (Tab 4, ~4 min).** "We hand Claude only the spec and ask
  it to rebuild. Different code — that's expected. The claim is the spec is
  sufficient."
- **Act 4 — The proof (Tab 5, ~4 min).** Compare → matching charts → green
  **EQUIVALENT**. "Different code, identical answers. Run this quarterly:
  regenerate, compare. Passes → spec valid. Fails → documented drift, not a
  mystery."
- **Act 5 — New feature (Tab 6, ~3 min).** "Average days to approval, from the
  spec alone — no need to re-read the code. The spec is a launchpad, not just a
  record."
- **Act 6 — Production knowledge (Tabs 7–10, ~6 min).** Tickets (5 of 8 map to
  D1–D5 — "the spec predicted them") → enriched Section 8 → FAQ → the
  spec-bounded chatbot classifying KNOWN PATTERN / KNOWN GAP / UNKNOWN. "The
  chatbot is bounded by the spec; its quality is Section 8's quality — written
  from evidence, not memory."
- **Act 7 — Validation & version drift (Tabs 11–12, ~4 min).** Tab 11: the
  spec generates the tests that pin its own claims — the characterization rows
  pass *because* the system is as-built (D1–D4), so a future "fix" turns them red.
  "The drift gate, made executable." Tab 12 resolves the held thread: **D5**. The
  2026-04-28 platform refresh — a routine security patch, no code change —
  dropped `PYTHONHASHSEED=0`, destabilised the salted-`hash()` surrogate keys,
  and broke referential integrity the next day (INC-WBB-0018). "You only see it
  by putting the version history next to the incident timeline. Environment is
  evidence. For a migration team, this is the whole game: move the runtime, and
  the keys you depend on can silently change."
- **Close.** "The WBB domain is fictional; the method transfers directly to a
  real WBB→TDBC stream: gather artifacts (code *and* runtime), reverse-engineer a
  forensic spec where every claim has a source and every contradiction is
  preserved, prove it regenerates, generate the tests that pin it, then use it to
  onboard, validate before cutover, and run L3 support — one auditable document
  from delivery through production."

---

*Reconstruction brief for the WBB Spec-Driven Demo. Build offline-first unless a
live LLM API is confirmed available in the TD environment.*
