-- target_schema.sql
-- WBB Analytics Warehouse schema (wbbaw schema, PostgreSQL 14+)
-- Regenerated from spec alone — wbbaw_spec_v1.md
-- Owned by WBB Data Services; read-only to the reporting layer.
--
-- Star schema with one fact table (fact_application) and three conformed
-- dimensions (dim_date, dim_customer, dim_product).
-- All dimensions use Type 1 (overwrite) SCD behaviour per BRD §4.3.

CREATE SCHEMA IF NOT EXISTS wbbaw;

-- ---------------------------------------------------------------------------
-- wbbaw.dim_date
-- Standard date dimension pre-populated 2025-10-01 through 2030-12-31.
-- NOT written by the nightly ETL; maintained by a separate quarterly job.
-- Surrogate key: integer in YYYYMMDD format.
-- ---------------------------------------------------------------------------
CREATE TABLE wbbaw.dim_date (
    date_key        INTEGER         PRIMARY KEY,    -- YYYYMMDD
    full_date       DATE            NOT NULL UNIQUE,
    year            SMALLINT        NOT NULL,
    quarter         SMALLINT        NOT NULL,
    month           SMALLINT        NOT NULL,
    day_of_month    SMALLINT        NOT NULL,
    day_of_week     SMALLINT        NOT NULL,       -- 0=Sunday … 6=Saturday
    iso_year_week   VARCHAR(8)      NOT NULL,       -- 'YYYY-Www'
    is_business_day BOOLEAN         NOT NULL
);

-- Seed dim_date for 2025-10-01 through 2030-12-31
INSERT INTO wbbaw.dim_date (
    date_key,
    full_date,
    year,
    quarter,
    month,
    day_of_month,
    day_of_week,
    iso_year_week,
    is_business_day
)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INTEGER                          AS date_key,
    d::DATE                                                  AS full_date,
    EXTRACT(YEAR  FROM d)::SMALLINT                          AS year,
    EXTRACT(QUARTER FROM d)::SMALLINT                        AS quarter,
    EXTRACT(MONTH FROM d)::SMALLINT                          AS month,
    EXTRACT(DAY   FROM d)::SMALLINT                          AS day_of_month,
    EXTRACT(DOW   FROM d)::SMALLINT                          AS day_of_week,
    TO_CHAR(d, 'IYYY"-W"IW')                                 AS iso_year_week,
    EXTRACT(DOW   FROM d) NOT IN (0, 6)                      AS is_business_day
FROM generate_series(
    '2025-10-01'::DATE,
    '2030-12-31'::DATE,
    '1 day'::INTERVAL
) AS d;

-- ---------------------------------------------------------------------------
-- wbbaw.dim_customer
-- One row per customer. Surrogate key derived deterministically from
-- hash(('cust', customer_id)). Type 1 (overwrite) SCD.
--
-- Column mapping:
--   source wbb.customer.business_category → warehouse segment
--   (BRD calls it business_segment; source uses business_category;
--    warehouse uses segment as the conformed standard name.)
--
-- first_product_type: added 2026-01-20; populated by a separate job, NOT
-- by the nightly ETL. The nightly load sets it to NULL on upsert.
-- ---------------------------------------------------------------------------
CREATE TABLE wbbaw.dim_customer (
    customer_key         BIGINT          PRIMARY KEY,
    customer_id          INTEGER         NOT NULL UNIQUE,   -- natural key; upsert conflict target
    company_name         VARCHAR(200)    NOT NULL,
    segment              VARCHAR(100),                      -- source: business_category
    company_size         VARCHAR(10),
    is_test              BOOLEAN,
    first_product_type   VARCHAR(20),                       -- populated by separate job; NULL during nightly load
    etl_first_loaded_dt  TIMESTAMP       NOT NULL DEFAULT NOW(),
    etl_last_updated_dt  TIMESTAMP       NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- wbbaw.dim_product
-- One row per banking product.
-- NOT refreshed by the nightly ETL; wbbldr.py contains no upsert for this
-- dimension. Only the Unknown sentinel is seeded at DDL time.
--
-- product_key = -1 is the "Unknown Product" sentinel used for defaulting
-- unresolvable product references (per BRD §5). NOTE: the ETL does not
-- currently perform a product lookup or route to this default; the mechanism
-- is present in the schema but not in the load code (see spec §4.5, Q1, Q2).
-- ---------------------------------------------------------------------------
CREATE TABLE wbbaw.dim_product (
    product_key    BIGINT          PRIMARY KEY,
    product_id     INTEGER         UNIQUE,                  -- null for the Unknown sentinel
    product_code   VARCHAR(10),
    product_name   VARCHAR(100)    NOT NULL,
    product_type   VARCHAR(20),
    is_active      BOOLEAN
);

-- Unknown sentinel
INSERT INTO wbbaw.dim_product (product_key, product_id, product_code, product_name, product_type, is_active)
VALUES (-1, NULL, NULL, 'Unknown Product', NULL, NULL);

-- Product reference data is loaded separately; the nightly ETL does not populate
-- this dimension. The Unknown sentinel above is sufficient for the demo.

-- ---------------------------------------------------------------------------
-- wbbaw.fact_application
-- Central fact; one row per application. Surrogate key: application_key.
-- Natural key: application_id (UNIQUE); upsert conflict target.
--
-- Primary date dimension: submitted_date_key (NOT approved_date_key).
-- BRD §5 specifies counting by approval date, but approved_dt was unavailable
-- in the source schema when the ETL was built; submitted_date_key is the
-- as-built primary date. approved_date_key is populated where available.
-- Reconciling BRD intent with as-built behaviour is a known open item.
-- (See spec Discrepancy D1.)
--
-- Note: there is no decline_description column on this fact.
-- The extract carries decline_description to staging but the load step
-- never persists it. (See spec Discrepancy D3.)
-- ---------------------------------------------------------------------------
CREATE TABLE wbbaw.fact_application (
    application_key     BIGINT          PRIMARY KEY,
    application_id      INTEGER         NOT NULL UNIQUE,    -- natural key; upsert conflict target
    customer_key        BIGINT          NOT NULL REFERENCES wbbaw.dim_customer (customer_key),
    -- Primary date: submission date (as-built; not approval date — see D1)
    submitted_date_key  INTEGER         NOT NULL REFERENCES wbbaw.dim_date (date_key),
    approved_date_key   INTEGER         REFERENCES wbbaw.dim_date (date_key),   -- null if not approved
    submitted_timestamp TIMESTAMP,
    approved_timestamp  TIMESTAMP,
    status              VARCHAR(20),
    is_approved         BOOLEAN,
    is_declined         BOOLEAN,
    days_to_decision    INTEGER,        -- calendar days reviewed_dt - submitted_dt; null if undecided
    etl_load_dt         TIMESTAMP       NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- wbbaw.vw_weekly_onboarding_volume
-- Counts applications submitted and approved per ISO week.
-- Joins on submitted_date_key (submission date, NOT approval date).
-- Note: BRD §5 specifies counting by approval date; this view counts by
-- submitted date — the as-built behaviour. See spec Discrepancy D1.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW wbbaw.vw_weekly_onboarding_volume AS
SELECT
    d.iso_year_week,
    COUNT(*)                                                    AS applications_submitted,
    SUM(CASE WHEN fa.is_approved THEN 1 ELSE 0 END)            AS applications_approved,
    SUM(CASE WHEN fa.is_declined THEN 1 ELSE 0 END)            AS applications_declined
FROM wbbaw.fact_application fa
JOIN wbbaw.dim_date d ON d.date_key = fa.submitted_date_key
GROUP BY d.iso_year_week
ORDER BY d.iso_year_week;

-- ---------------------------------------------------------------------------
-- wbbaw.vw_approval_rate_by_segment
-- Calculates approval rate per customer segment.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW wbbaw.vw_approval_rate_by_segment AS
SELECT
    dc.segment,
    COUNT(*)                                                    AS total_applications,
    SUM(CASE WHEN fa.is_approved THEN 1 ELSE 0 END)            AS approved_count,
    ROUND(
        100.0 * SUM(CASE WHEN fa.is_approved THEN 1 ELSE 0 END)
             / NULLIF(COUNT(*), 0),
        2
    )                                                           AS approval_rate_pct
FROM wbbaw.fact_application fa
JOIN wbbaw.dim_customer dc ON dc.customer_key = fa.customer_key
GROUP BY dc.segment
ORDER BY dc.segment;
