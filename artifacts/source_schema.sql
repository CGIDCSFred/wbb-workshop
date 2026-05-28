-- ============================================================================
-- WebBiz Banking (WBB) Operational Database
-- Source schema for WBB Analytics Warehouse (WBBAW)
-- ----------------------------------------------------------------------------
-- Schema name:    wbb
-- Owner:          WBB Platform Engineering
-- Target DBMS:    PostgreSQL 14+
-- Created:        2025-10-15 (initial deployment)
-- Last modified:  2026-01-08 (added onboarding_application.approved_dt)
-- ----------------------------------------------------------------------------
-- This is the operational source database for the WBB customer onboarding
-- platform. It records the full lifecycle of a business customer from initial
-- application through product activation.
--
-- This schema is read by the WBBAW ETL pipeline. The WBBAW does not write
-- back to this schema.
--
-- Note: this schema has grown organically. Some column naming is inconsistent
-- across tables (e.g. business_category vs. segment in downstream usage).
-- Do not rename without a coordinated release.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS wbb;
SET search_path TO wbb;


-- ----------------------------------------------------------------------------
-- Table: customer
-- ----------------------------------------------------------------------------
-- The business entity applying for WBB banking services. A customer may
-- submit one or more applications over time (e.g. after a previous
-- application was declined).
--
-- Note: business_category is a free-text classification entered by the
-- applicant at registration. Values are not validated against a controlled
-- vocabulary. Common values include 'RETAIL', 'PROFESSIONAL_SERVICES',
-- 'CONSTRUCTION', 'HOSPITALITY', 'TECHNOLOGY', 'HEALTHCARE', but others
-- exist. Downstream consumers must handle unexpected values gracefully.
--
-- Note: is_test marks internal test accounts created by the QA team.
-- These must be excluded from all operational and analytical reporting.
-- A separate population of DEMO accounts exists — see customer_type below.
-- ----------------------------------------------------------------------------
CREATE TABLE customer (
    customer_id          SERIAL          PRIMARY KEY,
    company_name         VARCHAR(255)    NOT NULL,
    business_category    VARCHAR(100),                   -- free-text; see note above
    company_size         VARCHAR(10),                    -- MICRO / SMALL / MEDIUM / LARGE
    registration_number  VARCHAR(50),                    -- company registration / BN
    contact_name         VARCHAR(255),
    contact_email        VARCHAR(255),
    is_test              BOOLEAN         NOT NULL DEFAULT FALSE,
    customer_type        VARCHAR(20)     NOT NULL DEFAULT 'STANDARD',
    -- 'STANDARD' / 'EMPLOYEE' / 'TEST' / 'DEMO'
    -- DEMO accounts are used by the sales team for prospect demonstrations.
    -- is_test = TRUE is always set for customer_type = 'TEST'. DEMO accounts
    -- have is_test = FALSE because they produce realistic-looking data.
    created_dt           TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_customer_category ON customer (business_category);
CREATE INDEX ix_customer_size ON customer (company_size);
CREATE INDEX ix_customer_type ON customer (customer_type);


-- ----------------------------------------------------------------------------
-- Table: onboarding_application
-- ----------------------------------------------------------------------------
-- An application submitted by a customer to onboard to WBB services.
-- A customer may have multiple applications (one active at a time; prior
-- applications are retained for audit).
--
-- Status lifecycle: SUBMITTED → IN_REVIEW → APPROVED or DECLINED
-- Early exit:       SUBMITTED → ABANDONED (customer did not complete)
--
-- Note: approved_dt was added 2026-01-08. Prior approved applications have
-- approved_dt populated by a backfill run on that date (set to reviewed_dt
-- for records with status = 'APPROVED' where approved_dt was null).
-- ----------------------------------------------------------------------------
CREATE TABLE onboarding_application (
    application_id       SERIAL          PRIMARY KEY,
    customer_id          INT             NOT NULL REFERENCES customer (customer_id),
    submitted_dt         TIMESTAMP       NOT NULL DEFAULT NOW(),
    status               VARCHAR(20)     NOT NULL DEFAULT 'SUBMITTED',
    -- SUBMITTED / IN_REVIEW / APPROVED / DECLINED / ABANDONED
    reviewed_dt          TIMESTAMP,                      -- set when status moves to APPROVED or DECLINED
    approved_dt          TIMESTAMP,                      -- set when status = APPROVED (added 2026-01-08)
    reviewed_by          VARCHAR(100),
    decline_reason_code  VARCHAR(20)
    -- FK to decline_reason added below after that table is created
    -- null for non-declined applications
);

CREATE INDEX ix_application_customer ON onboarding_application (customer_id);
CREATE INDEX ix_application_status ON onboarding_application (status);
CREATE INDEX ix_application_submitted ON onboarding_application (submitted_dt);
CREATE INDEX ix_application_approved ON onboarding_application (approved_dt);


-- ----------------------------------------------------------------------------
-- Table: banking_product
-- ----------------------------------------------------------------------------
-- Reference table of banking products available on the WBB platform.
-- Products are assigned to customers after their application is approved.
-- ----------------------------------------------------------------------------
CREATE TABLE banking_product (
    product_id           SERIAL          PRIMARY KEY,
    product_code         VARCHAR(20)     NOT NULL UNIQUE,
    product_name         VARCHAR(100)    NOT NULL,
    product_type         VARCHAR(50)     NOT NULL,       -- 'ACCOUNT' / 'PAYROLL' / 'WIRE' / 'LENDING'
    is_active            BOOLEAN         NOT NULL DEFAULT TRUE
);

CREATE INDEX ix_product_type ON banking_product (product_type);


-- ----------------------------------------------------------------------------
-- Table: customer_product
-- ----------------------------------------------------------------------------
-- Records which banking products have been activated for each customer.
-- A customer may hold multiple products. A product may be held by many
-- customers.
--
-- An approved application results in one or more product activations.
-- The application_id foreign key links each activation back to the
-- originating application.
-- ----------------------------------------------------------------------------
CREATE TABLE customer_product (
    customer_id          INT             NOT NULL REFERENCES customer (customer_id),
    product_id           INT             NOT NULL REFERENCES banking_product (product_id),
    application_id       INT             NOT NULL REFERENCES onboarding_application (application_id),
    activated_dt         TIMESTAMP       NOT NULL DEFAULT NOW(),
    activated_by         VARCHAR(100),
    PRIMARY KEY (customer_id, product_id)
);

CREATE INDEX ix_customer_product_app ON customer_product (application_id);
CREATE INDEX ix_customer_product_dt ON customer_product (activated_dt);


-- ----------------------------------------------------------------------------
-- Table: decline_reason
-- ----------------------------------------------------------------------------
-- Reference data for decline_reason_code values on onboarding_application.
-- Added November 2025 to standardise decline tracking across the platform.
--
-- Note: older applications declined before November 2025 may have
-- decline_reason_code values not present in this table. Downstream
-- consumers must handle missing lookups gracefully.
-- ----------------------------------------------------------------------------
CREATE TABLE decline_reason (
    reason_code          VARCHAR(20)     PRIMARY KEY,
    reason_description   VARCHAR(255)    NOT NULL,
    category             VARCHAR(50)     NOT NULL
    -- 'CREDIT_RISK' / 'INCOMPLETE_DOCS' / 'FRAUD_INDICATOR' / 'DUPLICATE' / 'OTHER'
);

-- Seed values as of January 2026.
INSERT INTO decline_reason (reason_code, reason_description, category) VALUES
    ('CR001', 'Insufficient credit history',                      'CREDIT_RISK'),
    ('CR002', 'Adverse credit file',                              'CREDIT_RISK'),
    ('CR003', 'Debt-to-income ratio exceeds threshold',           'CREDIT_RISK'),
    ('ID001', 'Identity documents incomplete or unreadable',      'INCOMPLETE_DOCS'),
    ('ID002', 'Business registration documentation missing',      'INCOMPLETE_DOCS'),
    ('ID003', 'Director identification not provided',             'INCOMPLETE_DOCS'),
    ('FR001', 'Application flagged by fraud screening',           'FRAUD_INDICATOR'),
    ('FR002', 'Associated party on sanctions list',               'FRAUD_INDICATOR'),
    ('DU001', 'Duplicate application detected',                   'DUPLICATE'),
    ('OT001', 'Does not meet eligibility criteria',               'OTHER'),
    ('OT002', 'Business type not supported in current markets',   'OTHER');


-- ----------------------------------------------------------------------------
-- Reference seed data: banking_product
-- ----------------------------------------------------------------------------
INSERT INTO banking_product (product_code, product_name, product_type, is_active) VALUES
    ('CHQ001', 'Business Chequing Account',       'ACCOUNT',  TRUE),
    ('SAV001', 'Business Savings Account',        'ACCOUNT',  TRUE),
    ('PAY001', 'Payroll Services',                'PAYROLL',  TRUE),
    ('WIR001', 'Domestic Wire Transfer',          'WIRE',     TRUE),
    ('WIR002', 'International Wire Transfer',     'WIRE',     TRUE),
    ('LND001', 'Business Line of Credit',         'LENDING',  TRUE),
    ('LND002', 'Term Loan',                       'LENDING',  TRUE);


-- ----------------------------------------------------------------------------
-- Deferred FK: onboarding_application → decline_reason
-- Added here because decline_reason is defined after onboarding_application.
-- ----------------------------------------------------------------------------
ALTER TABLE onboarding_application
    ADD CONSTRAINT fk_application_decline_reason
    FOREIGN KEY (decline_reason_code) REFERENCES decline_reason (reason_code);


-- ----------------------------------------------------------------------------
-- End of schema.
-- ----------------------------------------------------------------------------
