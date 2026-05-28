# Prompt 02 — Regeneration Pass

## How to use this prompt

Open a **fresh Claude context with no memory of the artifacts**.
Attach only one file: `spec/wbbaw_spec_v1.md`

Do not attach the original artifacts. The regeneration claim is that the spec
alone is sufficient. If you look at the original code while regenerating, the
claim collapses.

Then paste the prompt below.

---

You are acting as a software engineer implementing a system from a specification
document. Your job is to build a working implementation. You have not seen the
original system and must not ask for it. The specification is your only input.

## Context

The specification describes an ETL pipeline that extracts customer onboarding
data from an operational database (WBB) and loads it into an analytics
warehouse. The spec was produced by forensic reverse-engineering of an existing
system. Your task is to implement a semantically equivalent system from that
spec alone.

## Your task

Build a complete, runnable implementation of the WBBAW ETL pipeline. The
implementation must:

- Produce the same business answers as the original when run against equivalent
  input data.
- Use the same grain, the same dimension structure, and the same transformation
  rules as described in the spec.
- Run in Python with PostgreSQL (psycopg2). Docker Compose for the environment.
- Be organised cleanly — a reader should be able to navigate from spec to code
  without confusion.

Implementation choices (naming, code structure, helper patterns) are yours to
make. What must match the spec is semantics, not syntax.

## What to produce

1. **`regenerated/source_schema.sql`** — the source database schema
2. **`regenerated/target_schema.sql`** — the warehouse schema
3. **`regenerated/etl/extract.py`** — the extract step
4. **`regenerated/etl/load.py`** — the load step
5. **`regenerated/etl/common.py`** — shared utilities
6. **`regenerated/docker-compose.yml`** — environment

## Important

- If the spec is unclear on a point, implement the most conservative
  interpretation and add a comment noting the ambiguity.
- Do not add features the spec does not describe.
- Do not "fix" things that look wrong in the spec — the spec may be documenting
  as-built behaviour, and your job is to replicate it.
