-- ============================================================================
-- WBB Analytics Warehouse (WBBAW)
-- Target star schema for onboarding programme analytical reporting
-- ----------------------------------------------------------------------------
-- Schema name:    wbbaw
-- Owner:          WBB Data Services
-- Target DBMS:    PostgreSQL 14+
-- Source BRD:     WBB-BRD-AW-001 v1.1
-- Created:        2025-11-03
-- Last modified:  2026-01-20 (added dim_customer.first_product_type)
-- ----------------------------------------------------------------------------
-- Star schema. One fact table (fact_application) and three conformed
-- dimensions (dim_customer, dim_product, dim_date).
--
-- Grain of fact_application: one row per onboarding application.
-- A customer who submits multiple applications over time will have
-- multiple fact rows.
--
-- SCD treatment is Type 1 (overwrite) for all dimensions per BRD §4.3.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS wbbaw;
SET search_path TO wbbaw;


-- ----------------------------------------------------------------------------
-- Dimension: dim_date
-- ----------------------------------------------------------------------------
-- Standard date dimension. One row per calendar date.
-- Pre-populated for the warehouse window: 2025-10-01 through 2030-12-31.
-- The ETL does not insert into this table; maintained by a quarterly job.
-- ----------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key             INTEGER         PRIMARY KEY,    -- YYYYMMDD format
    calendar_date        DATE            NOT NULL UNIQUE,
    day_of_week          VARCHAR(10)     NOT NULL,
    day_of_month         SMALLINT        NOT NULL,
    week_of_year         SMALLINT        NOT NULL,
    iso_year_week        VARCHAR(8)      NOT NULL,        -- 'YYYY-Www'
    month_number         SMALLINT        NOT NULL,
    month_name           VARCHAR(10)     NOT NULL,
    quarter              SMALLINT        NOT NULL,
    calendar_year        SMALLINT        NOT NULL,
    is_weekend           BOOLEAN         NOT NULL,
    is_business_day      BOOLEAN         NOT NULL
);

CREATE INDEX ix_dim_date_calendar ON dim_date (calendar_date);
CREATE INDEX ix_dim_date_iso_week ON dim_date (iso_year_week);


-- ----------------------------------------------------------------------------
-- Dimension: dim_customer
-- ----------------------------------------------------------------------------
-- One row per customer. Conformed dimension.
--
-- Note: segment here corresponds to wbb.customer.business_category.
-- The column has been renamed in the warehouse to follow conformed naming
-- conventions (segment is the standard term across the warehouse).
-- The BRD refers to this concept as business_segment; see BRD §3.1.
--
-- SCD: Type 1. Customer attribute changes overwrite per BRD §4.3.
-- ----------------------------------------------------------------------------
CREATE TABLE dim_customer (
    customer_key         BIGINT          PRIMARY KEY,    -- surrogate key
    customer_id          INT             NOT NULL UNIQUE, -- natural key from wbb.customer
    company_name         VARCHAR(255)    NOT NULL,
    segment              VARCHAR(100),                    -- from wbb.customer.business_category
    company_size         VARCHAR(10),                     -- MICRO / SMALL / MEDIUM / LARGE / UNKNOWN
    is_test              BOOLEAN         NOT NULL,
    first_product_type   VARCHAR(50),                     -- product_type of first activated product (added 2026-01-20)
    etl_last_updated_dt  TIMESTAMP       NOT NULL
);

CREATE INDEX ix_dim_customer_segment ON dim_customer (segment);
CREATE INDEX ix_dim_customer_size ON dim_customer (company_size);


-- ----------------------------------------------------------------------------
-- Dimension: dim_product
-- ----------------------------------------------------------------------------
-- One row per banking product. Conformed dimension.
--
-- An "Unknown Product" member is seeded at product_key = -1 for fact rows
-- where the product reference cannot be resolved.
-- ----------------------------------------------------------------------------
CREATE TABLE dim_product (
    product_key          BIGINT          PRIMARY KEY,    -- surrogate key; -1 reserved for Unknown
    product_id           INT             UNIQUE,          -- natural key; NULL for Unknown member
    product_code         VARCHAR(20),
    product_name         VARCHAR(100)    NOT NULL,
    product_type         VARCHAR(50)     NOT NULL,
    is_active            BOOLEAN         NOT NULL,
    etl_last_updated_dt  TIMESTAMP       NOT NULL
);

INSERT INTO dim_product (
    product_key, product_id, product_code, product_name,
    product_type, is_active, etl_last_updated_dt
) VALUES (
    -1, NULL, 'UNKNOWN', 'Unknown Product',
    'UNKNOWN', FALSE, '2025-11-03 00:00:00'
);


-- ----------------------------------------------------------------------------
-- Fact: fact_application
-- ----------------------------------------------------------------------------
-- Central fact of the warehouse. One row per onboarding application.
--
-- Grain: one row per application. A customer who re-applies after a
-- declined application produces a second fact row.
--
-- Note: submitted_date_key is the primary date dimension used for
-- weekly volume reporting. The BRD (§5) specifies that volume metrics
-- should be counted by the date the application was approved, not the
-- date it was submitted. This warehouse uses submitted_date_key as the
-- primary date because approved_dt was not available in the source schema
-- at the time the ETL was built (it was added in the source schema on
-- 2026-01-08). The approved_date_key is populated where available.
-- Reconciling the BRD's intent with the as-built behaviour is a known
-- open item; see the WBBAW backlog.
--
-- Note: there is no decline_description column on this fact.
-- ----------------------------------------------------------------------------
CREATE TABLE fact_application (
    application_key      BIGINT          PRIMARY KEY,    -- surrogate key
    application_id       INT             NOT NULL UNIQUE, -- natural key from source
    -- Conformed dimension keys
    customer_key         BIGINT          NOT NULL REFERENCES dim_customer (customer_key),
    submitted_date_key   INTEGER         NOT NULL REFERENCES dim_date (date_key),
    approved_date_key    INTEGER         REFERENCES dim_date (date_key),   -- null if not approved
    -- Fact attributes
    submitted_timestamp  TIMESTAMP       NOT NULL,
    approved_timestamp   TIMESTAMP,
    status               VARCHAR(20)     NOT NULL,
    is_approved          BOOLEAN         NOT NULL,
    is_declined          BOOLEAN         NOT NULL,
    days_to_decision     INTEGER,                          -- null if decision not yet made
    -- ETL housekeeping
    etl_load_dt          TIMESTAMP       NOT NULL
);

CREATE INDEX ix_fact_app_customer ON fact_application (customer_key);
CREATE INDEX ix_fact_app_submitted ON fact_application (submitted_date_key);
CREATE INDEX ix_fact_app_approved ON fact_application (approved_date_key);
CREATE INDEX ix_fact_app_status ON fact_application (status);
CREATE INDEX ix_fact_app_is_approved ON fact_application (is_approved);


-- ----------------------------------------------------------------------------
-- View: vw_weekly_onboarding_volume
-- ----------------------------------------------------------------------------
-- Applications submitted and approved per ISO week.
-- Note: this view counts by submitted_date_key, which corresponds to the
-- application submission date — not the approval date. See fact_application
-- header comment for context on this known discrepancy vs. BRD §5.
-- ----------------------------------------------------------------------------
CREATE VIEW vw_weekly_onboarding_volume AS
SELECT
    d.iso_year_week,
    COUNT(*)                                          AS applications_submitted,
    SUM(CASE WHEN f.is_approved THEN 1 ELSE 0 END)   AS applications_approved,
    SUM(CASE WHEN f.is_declined THEN 1 ELSE 0 END)   AS applications_declined
FROM fact_application f
JOIN dim_date d ON f.submitted_date_key = d.date_key
GROUP BY d.iso_year_week
ORDER BY d.iso_year_week;


-- ----------------------------------------------------------------------------
-- View: vw_approval_rate_by_segment
-- ----------------------------------------------------------------------------
-- Approval rate broken down by customer segment (business category).
-- ----------------------------------------------------------------------------
CREATE VIEW vw_approval_rate_by_segment AS
SELECT
    c.segment,
    COUNT(*)                                          AS total_applications,
    SUM(CASE WHEN f.is_approved THEN 1 ELSE 0 END)   AS approved_count,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_approved THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    )                                                 AS approval_rate_pct
FROM fact_application f
JOIN dim_customer c ON f.customer_key = c.customer_key
GROUP BY c.segment
ORDER BY total_applications DESC;


-- ----------------------------------------------------------------------------
-- Seed: dim_date
-- ----------------------------------------------------------------------------
-- Pre-populate dim_date for the warehouse window: 2025-10-01 through
-- 2030-12-31. Embedded here so a fresh docker compose up is self-contained.
-- ----------------------------------------------------------------------------
INSERT INTO dim_date (
    date_key, calendar_date, day_of_week, day_of_month, week_of_year,
    iso_year_week, month_number, month_name, quarter, calendar_year,
    is_weekend, is_business_day
)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INTEGER         AS date_key,
    d::DATE                                  AS calendar_date,
    TO_CHAR(d, 'Day')                        AS day_of_week,
    EXTRACT(DAY   FROM d)::SMALLINT          AS day_of_month,
    EXTRACT(WEEK  FROM d)::SMALLINT          AS week_of_year,
    TO_CHAR(d, 'IYYY"-W"IW')                 AS iso_year_week,
    EXTRACT(MONTH FROM d)::SMALLINT          AS month_number,
    TO_CHAR(d, 'Month')                      AS month_name,
    EXTRACT(QUARTER FROM d)::SMALLINT        AS quarter,
    EXTRACT(YEAR  FROM d)::SMALLINT          AS calendar_year,
    EXTRACT(ISODOW FROM d) IN (6, 7)         AS is_weekend,
    EXTRACT(ISODOW FROM d) NOT IN (6, 7)     AS is_business_day
FROM generate_series(
    '2025-10-01'::DATE,
    '2030-12-31'::DATE,
    '1 day'::INTERVAL
) AS d;


-- ----------------------------------------------------------------------------
-- End of schema.
-- ----------------------------------------------------------------------------
