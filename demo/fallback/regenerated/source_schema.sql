-- source_schema.sql
-- WBB operational source database schema (wbb schema, PostgreSQL 14+)
-- Regenerated from spec alone — wbbaw_spec_v1.md
-- Owned by WBB Platform Engineering; initially deployed 2025-10-15.
--
-- NOTE: business_category is free-text entered by the applicant and is not
-- validated against a controlled vocabulary. Downstream consumers must handle
-- unexpected values gracefully.
--
-- NOTE: Some column naming is inconsistent across tables
-- (e.g. business_category vs. segment in downstream usage).
-- Do not rename without a coordinated release.

CREATE SCHEMA IF NOT EXISTS wbb;

-- ---------------------------------------------------------------------------
-- wbb.customer
-- One row per business entity applying for WBB services.
--
-- customer_type = 'DEMO' rows have is_test = FALSE by design (sales demo
-- accounts). They are NOT excluded by the v1 ETL; exclusion is a v2 backlog
-- item (WBB-AW-019).
-- ---------------------------------------------------------------------------
CREATE TABLE wbb.customer (
    customer_id       SERIAL          PRIMARY KEY,
    company_name      VARCHAR(200)    NOT NULL,
    business_category VARCHAR(100),           -- free-text; may carry unexpected values
    company_size      VARCHAR(10)     NOT NULL CHECK (company_size IN ('MICRO','SMALL','MEDIUM','LARGE')),
    is_test           BOOLEAN         NOT NULL DEFAULT FALSE,
    customer_type     VARCHAR(20)     NOT NULL DEFAULT 'STANDARD'
                                              CHECK (customer_type IN ('STANDARD','EMPLOYEE','TEST','DEMO'))
);

-- ---------------------------------------------------------------------------
-- wbb.decline_reason
-- Reference table mapping decline reason codes to descriptions.
-- Added November 2025.
-- Applications declined before November 2025 may carry reason_code values
-- not present in this table; downstream consumers must handle missing lookups
-- gracefully.
-- ---------------------------------------------------------------------------
CREATE TABLE wbb.decline_reason (
    reason_code        VARCHAR(10)     PRIMARY KEY,
    reason_description VARCHAR(255)    NOT NULL,
    category           VARCHAR(50)     NOT NULL
);

INSERT INTO wbb.decline_reason (reason_code, reason_description, category) VALUES
    ('CR001', 'Insufficient credit history',          'CREDIT_RISK'),
    ('CR002', 'Poor credit score',                    'CREDIT_RISK'),
    ('CR003', 'High debt-to-income ratio',            'CREDIT_RISK'),
    ('ID001', 'Missing incorporation documents',      'INCOMPLETE_DOCS'),
    ('ID002', 'Missing director identification',      'INCOMPLETE_DOCS'),
    ('ID003', 'Incomplete financial statements',      'INCOMPLETE_DOCS'),
    ('FR001', 'Suspected identity fraud',             'FRAUD_INDICATOR'),
    ('FR002', 'Suspicious transaction pattern',       'FRAUD_INDICATOR'),
    ('DU001', 'Duplicate application',                'DUPLICATE'),
    ('OT001', 'Does not meet eligibility criteria',   'OTHER'),
    ('OT002', 'Applicant withdrew',                   'OTHER');

-- ---------------------------------------------------------------------------
-- wbb.onboarding_application
-- One row per application. status transitions:
--   SUBMITTED → IN_REVIEW → APPROVED | DECLINED | ABANDONED
--
-- approved_dt was added to the schema 2026-01-08; a backfill run set
-- approved_dt = reviewed_dt for pre-existing APPROVED records.
-- ---------------------------------------------------------------------------
CREATE TABLE wbb.onboarding_application (
    application_id      SERIAL          PRIMARY KEY,
    customer_id         INTEGER         NOT NULL REFERENCES wbb.customer (customer_id),
    submitted_dt        TIMESTAMP       NOT NULL,
    status              VARCHAR(20)     NOT NULL
                                        CHECK (status IN ('SUBMITTED','IN_REVIEW','APPROVED','DECLINED','ABANDONED')),
    reviewed_dt         TIMESTAMP,                  -- populated when status → APPROVED or DECLINED
    approved_dt         TIMESTAMP,                  -- populated when status = APPROVED; added 2026-01-08
    decline_reason_code VARCHAR(10)     REFERENCES wbb.decline_reason (reason_code)
                                        -- null for non-declined applications
);

-- ---------------------------------------------------------------------------
-- wbb.banking_product
-- Reference table of banking products offered on the WBB platform.
-- ---------------------------------------------------------------------------
CREATE TABLE wbb.banking_product (
    product_id   SERIAL          PRIMARY KEY,
    product_code VARCHAR(10)     NOT NULL UNIQUE,
    product_name VARCHAR(100)    NOT NULL,
    product_type VARCHAR(20)     NOT NULL CHECK (product_type IN ('ACCOUNT','PAYROLL','WIRE','LENDING')),
    is_active    BOOLEAN         NOT NULL DEFAULT TRUE
);

INSERT INTO wbb.banking_product (product_code, product_name, product_type, is_active) VALUES
    ('CHQ001', 'Business Chequing',          'ACCOUNT',  TRUE),
    ('SAV001', 'Business Savings',           'ACCOUNT',  TRUE),
    ('PAY001', 'Payroll Services',           'PAYROLL',  TRUE),
    ('WIR001', 'Domestic Wire',              'WIRE',     TRUE),
    ('WIR002', 'International Wire',         'WIRE',     TRUE),
    ('LND001', 'Business Line of Credit',    'LENDING',  TRUE),
    ('LND002', 'Commercial Term Loan',       'LENDING',  TRUE);

-- ---------------------------------------------------------------------------
-- wbb.customer_product
-- Records which products have been activated for each customer, with a
-- foreign key back to the originating application.
-- NOTE: The ETL extract does not currently join to this table; the warehouse
-- does not currently populate the product dimension from activations.
-- ---------------------------------------------------------------------------
CREATE TABLE wbb.customer_product (
    customer_product_id SERIAL      PRIMARY KEY,
    customer_id         INTEGER     NOT NULL REFERENCES wbb.customer (customer_id),
    product_id          INTEGER     NOT NULL REFERENCES wbb.banking_product (product_id),
    application_id      INTEGER     REFERENCES wbb.onboarding_application (application_id),
    activated_dt        TIMESTAMP   NOT NULL DEFAULT NOW()
);
