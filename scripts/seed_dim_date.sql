-- Seed dim_date for 2025-10-01 through 2030-12-31
-- This runs once at warehouse DB initialisation.

SET search_path TO wbbaw;

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
