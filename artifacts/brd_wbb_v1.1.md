# Business Requirements Document

## WBB Analytics Warehouse (WBBAW)

| | |
|---|---|
| **Document ID** | WBB-BRD-AW-001 |
| **Version** | 1.1 |
| **Status** | Approved for Build |
| **Author** | P. Nguyen, Senior Business Analyst, WBB Data Services |
| **Date Issued** | 10 November 2025 |
| **Last Reviewed** | 15 January 2026 |
| **Sponsor** | Head of WBB Customer Growth |

---

## Document Control

| Version | Date | Author | Change Summary |
|---|---|---|---|
| 0.1 | 20 Oct 2025 | P. Nguyen | Initial draft following stakeholder workshops |
| 0.8 | 3 Nov 2025 | P. Nguyen | Incorporated feedback from Data Services and Operations |
| 1.0 | 10 Nov 2025 | P. Nguyen | Approved for build at Architecture Review Board |
| 1.1 | 15 Jan 2026 | P. Nguyen | Minor clarifications to §2.3; added §6 (Reporting Requirements) |

---

## 1. Executive Summary

The WBB Analytics Warehouse (WBBAW) is a reporting data warehouse intended to give the WBB Customer Growth and Operations teams timely, consistent visibility into the performance of the WBB customer onboarding programme. The warehouse consolidates data from the WBB operational platform into an analytical model designed for trending, segmentation, and funnel analysis.

The WBB platform onboards small and medium businesses to a suite of business banking products. The onboarding journey spans application submission, identity and credit verification, approval or decline, and product activation. The operational platform is optimised for processing individual applications; it does not provide consolidated reporting across the application population. The WBBAW addresses this gap.

## 2. Scope

### 2.1 In Scope

- A target analytics warehouse populated nightly from the WBB operational platform.
- A star schema model supporting reporting on onboarding volume, outcomes, and funnel performance.
- A daily ETL pipeline running in the nightly batch window.
- Initial reporting for the Customer Growth team, the Operations team, and the Finance team.

### 2.2 Out of Scope

- Real-time or near-real-time reporting. The warehouse is a daily-refresh asset.
- Post-activation product usage reporting. This BRD covers onboarding analytics only.
- Customer-facing reporting. The WBBAW is for internal use only.

### 2.3 Exclusion Rules

The following records are excluded from all WBBAW fact and dimension tables:

- **Test accounts.** Internal test accounts created by the QA team must be excluded. Test accounts are identified by the `is_test` flag on the customer record.
- **Abandoned applications.** Applications where the customer began but did not complete the submission process are excluded. These represent incomplete data and inflate volume metrics.

## 3. Source System

The source system is the WBB operational platform database, which holds the canonical record of customers, applications, products, and their lifecycle events. The relevant entities are:

- **Customer.** The business entity applying for WBB services. Attributes include company name, business_segment, company size, and registration number.
- **Onboarding application.** The formal application record. Carries the application status, timestamps, and for declined applications, the decline reason.
- **Banking product.** The catalogue of products available on the WBB platform (chequing, savings, payroll, wire transfer, lending).
- **Customer product.** The record of which products have been activated for each approved customer.

The full operational schema is documented in `source_schema.sql`.

### 3.1 Known Source Data Quality Issues

- **Unvalidated business segment values.** The `business_segment` field is entered by the applicant at registration and is not validated against a controlled vocabulary. The warehouse must handle unexpected values gracefully, defaulting to a defined "Unknown" segment label rather than failing the load.
- **Incomplete decline reason coverage.** The decline reason lookup table was added in November 2025. Applications declined before that date may have decline reason codes not present in the lookup. The warehouse must handle missing lookups gracefully.

## 4. Target Analytical Model

The WBBAW is implemented as a star schema. The model centres on a single fact table capturing onboarding applications, supported by conformed dimensions.

### 4.1 Fact Tables

**`fact_application`** — one row per onboarding application. This is the central fact. Each row captures a single application submitted by a customer, with its outcome (approved, declined, or in progress) and timing.

The grain is *one row per application*. A customer who reapplies after a declined application produces a second fact row.

### 4.2 Dimensions

- **`dim_customer`** — one row per business customer, with attributes including company name, business segment, and company size.
- **`dim_product`** — one row per banking product, with attributes including product type and active status.
- **`dim_date`** — standard date dimension, one row per calendar date.

### 4.3 Slowly Changing Dimensions

Type 1 (overwrite) behaviour is used for all dimensions in the initial release. Historical attribute tracking is deferred to a future release.

## 5. Transformation Logic

The nightly ETL reads from the WBB operational platform and populates the WBBAW. The high-level flow is:

1. Extract applications from the operational database for the reporting date.
2. Apply the exclusion rules from §2.3.
3. Upsert the conformed dimensions with current source attribute values (Type 1).
4. Load `fact_application` with the resolved dimension keys and application attributes.

The transformation must:

- **Derive the approval and decline flags** from the application status. An `is_approved` boolean and an `is_declined` boolean are computed at load time.
- **Count applications by approval date.** Weekly volume metrics must reflect the date on which the application decision was made (approved or declined), not the date of initial submission. The submission date is retained on the fact for pipeline analysis.
- **Carry the decline reason** through to the warehouse for declined applications. The human-readable decline reason (from the decline reason lookup) must be available in the warehouse so that the Operations team can analyse decline patterns without querying the operational system. See user story WBB-AW-011.
- **Default unresolvable references** to designated Unknown dimension members rather than failing the load.

## 6. Reporting Requirements

The WBBAW must support the following reporting use cases at launch:

- **Weekly onboarding volume.** How many applications were submitted and approved each calendar week?
- **Approval rate by segment.** What proportion of applications are approved for each business segment?
- **Top decline reasons.** Among declined applications, what are the most common reasons, ranked?
- **Funnel drop-off.** At which stage of the onboarding journey do most abandoned applications exit?

## 7. Operational Requirements

- **Schedule.** The ETL runs nightly. The job must complete before the start of the business day to support morning reporting.
- **Restart.** The ETL must be restartable from the point of failure.
- **Data retention.** Application facts are retained for seven years for regulatory compliance.
- **Monitoring.** Job completion and failure notifications are delivered to the WBB Operations Slack channel (`#wbb-data-ops`).

## 8. Future Considerations

- **`fact_product_activation`** — a second fact table tracking individual product activations per customer, supporting product adoption analysis. Planned for v2.
- **Type 2 SCD** on `dim_customer` to support historical segment and size tracking. Planned for v2.
- **DEMO account exclusion.** DEMO accounts (used by the sales team for prospect demonstrations) are not currently excluded by the warehouse exclusion rules. Exclusion logic to be added in v2 (WBB-AW-019).

---

*End of document.*
