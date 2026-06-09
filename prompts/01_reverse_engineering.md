# Prompt 01 — Reverse Engineering Pass

## How to use this prompt

Open a fresh Claude context. Attach the following eight artifacts:

- `artifacts/brd_wbb_v1.1.md`
- `artifacts/source_schema.sql`
- `artifacts/target_schema.sql`
- `artifacts/user_stories_export.md`
- `artifacts/job_config.yaml`
- `artifacts/etl/wbbxtr.py`
- `artifacts/etl/wbbldr.py`
- `artifacts/etl/wbb_common.py`

Then paste the prompt below.

---

You are acting as a forensic analyst reverse-engineering an existing system from
its project artifacts. Your job is to reconstruct what was built and what was
intended, not to design a good system. Treat the artifacts as evidence, not as
a brief.

## Context

The system under analysis is an ETL pipeline that extracts customer onboarding
data from an operational web banking platform (WBB) and loads it into an
analytics warehouse. The pipeline was built over several sprints. The artifacts
in front of you are what the team produced along the way — a Business
Requirements Document, a set of user stories, the source and target schema DDL,
the ETL code itself, and a job configuration file describing the production
batch schedule.

The artifacts are not internally consistent. This is normal and expected.

## Your task

Produce a specification document that reconstructs the system from these
artifacts. The specification must be sufficient for a separate engineering
team, given only your specification and no other context, to build a system
with equivalent semantics — same grain, same conformed dimensions, same
business answers, same transformation rules. Their implementation may differ
in naming and structure; that is fine. What must transfer is meaning.

## Rules you must follow

**1. Provenance for every claim.** Every rule, mapping, column, constraint, and
business behaviour you document must cite the artifact it came from. Use
inline references like `[BRD §2.3]` or `[wbbxtr.py, EXTRACT_QUERY]`. If a
claim is supported by multiple artifacts, cite all of them. If a claim has
no artifact support, do not include it.

**2. Surface discrepancies, do not resolve them.** When two artifacts disagree,
do not pick a winner. Record both positions in the Discrepancies section, cite
both sources, quote the conflicting text directly, and add a short analyst note
on which is likely the as-built behaviour and why — but leave the discrepancy
itself in the spec for human resolution.

**3. Name gaps, do not fill them.** If an artifact does not tell you something
the spec needs — an SLA, a retention period, a failure mode, an ownership
boundary — write "Not specified in available artifacts" and add the question
to the Open Questions section. Do not invent plausible values.

**4. Prose, not JSON.** The reader is a human analyst or engineer. Use full
sentences and paragraphs. Tables are acceptable for column mappings and
discrepancy summaries. No JSON, no YAML, no dense schemas.

**5. Stay forensic.** You are reconstructing what exists, not improving it. If
something in the artifacts looks like a mistake, document it as built and note
your observation. Do not silently correct.

## Output structure

Produce the specification with exactly these sections, in this order:

### 1. System Overview
### 2. Source System
### 3. Target System
### 4. Transformation Rules
### 5. Operational Behaviour
### 6. Discrepancies Found
### 7. Open Questions

Save the output to `spec/wbbaw_spec_v1.md`.
