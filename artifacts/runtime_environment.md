# WBBAW Runtime Environment & Deployment History

| | |
|---|---|
| **Document ID** | WBB-OPS-AW-007 |
| **Component** | WBBAW-BATCH (nightly ETL deployment) |
| **Owner** | D. Osei, WBB Data Services / WBB Platform SRE |
| **Maintained in** | `wbb-platform` infrastructure repo, mirrored here for the analytics bundle |
| **Last updated** | 2026-04-29 (R. Mehta) — recorded the 28 Apr platform refresh |

---

## 1. Purpose

This document records the **runtime environment** the WBBAW nightly ETL executes
in, and the **history of changes** to that environment. The ETL code
(`wbbxtr`, `wbbldr`, `wbb_common`) is version-controlled in the analytics repo;
the *environment it runs in* — interpreter, libraries, base image, and runtime
configuration — is managed separately by Platform SRE and is captured here.

The pinned library set is in `etl/requirements.txt`. This document adds the
surrounding context: the base image, the runtime configuration, and the dated
log of upgrades.

## 2. Current deployment environment

As deployed to the nightly batch host (`wbbaw-batch-prod`) after the
2026-04-28 platform refresh:

| Component | Version | Notes |
|---|---|---|
| Base image | `wbb/python-batch:2026.04` | Standardised WBB batch base image |
| Python runtime | 3.12.3 | Upgraded from 3.10.13 on 2026-04-28 |
| psycopg2-binary | 2.9.9 | Upgraded from 2.9.5 on 2026-04-28 |
| PyYAML | 6.0.1 | Job-runner config parsing |
| OS | Debian 12 (bookworm) | Was Debian 11 (bullseye) prior to refresh |
| Job runner | wbb-jobd 4.2 | Reads `job_config.yaml` |

The source and target database servers (PostgreSQL 14+) are managed separately
and are out of scope for this document.

## 3. Runtime configuration

Environment variables injected at job launch. Database DSNs come from the
secrets manager (see `job_config.yaml`, `environment` block). Process-level
runtime flags are set by the base image:

| Variable | Value (current) | Value (pre-2026-04-28) | Set by |
|---|---|---|---|
| `WBB_SOURCE_DSN` | *(secrets manager)* | *(secrets manager)* | job runner |
| `WBB_TARGET_DSN` | *(secrets manager)* | *(secrets manager)* | job runner |
| `STAGE_PATH` | `/tmp/wbbaw_stage.jsonl` | `/tmp/wbbaw_stage.jsonl` | job_config.yaml |
| `LOG_LEVEL` | `INFO` | `INFO` | job_config.yaml |
| `PYTHONHASHSEED` | *(unset)* | `0` | base image |
| `TZ` | `UTC` | `UTC` | base image |

> **Note (Platform SRE, 2026-04-28):** the legacy bullseye base image set a
> number of fixed runtime overrides for reproducibility, including
> `PYTHONHASHSEED=0`. The standardised `wbb/python-batch:2026.04` image follows
> the corporate baseline and does not carry these legacy overrides. Jobs that
> require deterministic behaviour are expected to set their own flags
> explicitly.

## 4. Deployment & upgrade history

Chronological log of changes to the WBBAW ETL runtime environment. Code changes
are tracked in the analytics repo and user-story export; this log covers the
*environment* only.

| Date | Change | Driver | Change record |
|---|---|---|---|
| 2025-11-03 | Initial WBBAW batch deployment — Python 3.10.13, psycopg2-binary 2.9.5, Debian 11 base image, `PYTHONHASHSEED=0` | WBBAW v1 go-live | CHG-WBB-0008 |
| 2026-01-08 | No environment change — source schema added `approved_dt` (DB-side) | Source platform release | CHG-WBB-0019 |
| 2026-01-20 | No environment change — target schema + ETL code updated for `approved_dt` / `first_product_type` | Sprint 5 follow-up | CHG-WBB-0024 |
| 2026-02-03 | Audit-step bypass applied to production `job_config.yaml` | INC-WBB-0011 workaround | CHG-WBB-0029 |
| **2026-04-28** | **Platform refresh: base image standardised to `wbb/python-batch:2026.04`. Python 3.10.13 → 3.12.3, psycopg2-binary 2.9.5 → 2.9.9, Debian 11 → 12. Legacy runtime overrides not carried forward.** | **Mandatory CVE remediation cycle (bullseye EOL + interpreter CVEs)** | **CHG-WBB-0058** |

> **Note (R. Mehta, Platform SRE, 2026-04-28):** the refresh was a routine
> security-patch cycle. The application code was not changed — only the
> interpreter, libraries, and base image. Smoke test (extract produced a
> staging file; load connected to the warehouse) passed in the staging
> environment before promotion.

## 5. Reproducibility note

The ETL surrogate keys are generated in application code (`wbbldr.py`,
`customer_key` / `product_key` / `application_key`) rather than by the database.
Key stability across deployments is a function of the runtime, not the schema.
The dependency between the runtime environment and key stability is **not
documented in the BRD, the user stories, or the ETL code comments** — it is
visible only by reading the key-generation code against this environment
history.

---

*Maintained by WBB Platform SRE. Mirrored into the analytics artifact bundle so
that the reverse-engineering pass has the full operating context, not just the
application code.*
