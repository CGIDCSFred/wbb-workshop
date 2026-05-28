"""
WBB Onboarding Simulator
========================

Generates a realistic stream of customer onboarding events into the WBB
operational database. Used during the workshop demo to show the "live"
operational system receiving new customers.

Run modes:
  python generate.py seed      -- Insert a batch of historical records
  python generate.py stream    -- Continuously insert new records (demo mode)
  python generate.py status    -- Print a live summary of current data
"""

import os
import sys
import time
import random
import string
from datetime import datetime, timedelta

import psycopg2

DSN = os.environ.get('WBB_SOURCE_DSN', 'postgresql://wbb_app:wbb_pass@localhost:5432/wbb')

COMPANY_PREFIXES = [
    'Apex', 'Blue', 'Cedar', 'Delta', 'Ember', 'Falcon', 'Grand', 'Harbor',
    'Iron', 'Jade', 'Kestrel', 'Linden', 'Maple', 'Nova', 'Orbit', 'Peak',
    'Quinn', 'Ridge', 'Summit', 'Terra', 'Union', 'Vale', 'Waverly', 'Zenith',
    'Arrow', 'Brook', 'Cairn', 'Dove', 'Echo', 'Frost', 'Glen', 'Haven',
]

COMPANY_SUFFIXES = [
    'Solutions', 'Services', 'Group', 'Partners', 'Associates', 'Consulting',
    'Technologies', 'Industries', 'Ventures', 'Logistics', 'Construction',
    'Hospitality', 'Healthcare', 'Media', 'Design', 'Engineering',
]

BUSINESS_CATEGORIES = [
    'RETAIL', 'RETAIL', 'RETAIL',
    'PROFESSIONAL_SERVICES', 'PROFESSIONAL_SERVICES',
    'CONSTRUCTION', 'CONSTRUCTION',
    'HOSPITALITY',
    'TECHNOLOGY', 'TECHNOLOGY',
    'HEALTHCARE',
    'MANUFACTURING',
    'LOGISTICS',
    'MEDIA',
    'FOOD_AND_BEVERAGE',
]

COMPANY_SIZES = ['MICRO', 'MICRO', 'SMALL', 'SMALL', 'SMALL', 'MEDIUM', 'MEDIUM', 'LARGE']

PRODUCT_ASSIGNMENTS = {
    'MICRO':  ['CHQ001'],
    'SMALL':  ['CHQ001', 'PAY001'],
    'MEDIUM': ['CHQ001', 'SAV001', 'PAY001', 'WIR001'],
    'LARGE':  ['CHQ001', 'SAV001', 'PAY001', 'WIR001', 'WIR002'],
}

DECLINE_CODES = ['CR001', 'CR002', 'ID001', 'ID002', 'ID003', 'FR001', 'OT001', 'OT002']

# Outcome probabilities
P_APPROVE  = 0.72
P_DECLINE  = 0.20
P_ABANDON  = 0.08

REVIEW_LAG_DAYS = (1, 5)   # business days to review


def random_company_name():
    return f'{random.choice(COMPANY_PREFIXES)} {random.choice(COMPANY_SUFFIXES)}'


def random_registration():
    return ''.join(random.choices(string.digits, k=9))


def random_contact():
    first = random.choice(['James', 'Maria', 'Priya', 'David', 'Sophie', 'Chen', 'Omar', 'Aisha'])
    last  = random.choice(['Smith', 'Osei', 'Patel', 'Walsh', 'Kim', 'Nguyen', 'Brown', 'Ali'])
    return f'{first} {last}', f'{first.lower()}.{last.lower()}@example.com'


def submit_application(cur, submitted_at=None):
    """Insert a customer + application. Returns (customer_id, application_id)."""
    if submitted_at is None:
        submitted_at = datetime.utcnow()

    name = random_company_name()
    category = random.choice(BUSINESS_CATEGORIES)
    size = random.choice(COMPANY_SIZES)
    contact_name, contact_email = random_contact()
    is_test = False
    customer_type = 'DEMO' if random.random() < 0.05 else 'STANDARD'

    cur.execute(
        """
        INSERT INTO wbb.customer
            (company_name, business_category, company_size, registration_number,
             contact_name, contact_email, is_test, customer_type, created_dt)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING customer_id
        """,
        (name, category, size, random_registration(),
         contact_name, contact_email, is_test, customer_type, submitted_at),
    )
    customer_id = cur.fetchone()[0]

    cur.execute(
        """
        INSERT INTO wbb.onboarding_application
            (customer_id, submitted_dt, status)
        VALUES (%s, %s, 'SUBMITTED')
        RETURNING application_id
        """,
        (customer_id, submitted_at),
    )
    application_id = cur.fetchone()[0]
    return customer_id, application_id


def resolve_application(cur, application_id, customer_id, company_size, submitted_at):
    """Advance an application to APPROVED, DECLINED, or ABANDONED."""
    outcome = random.random()
    lag_days = random.randint(*REVIEW_LAG_DAYS)
    reviewed_at = submitted_at + timedelta(days=lag_days)

    if outcome < P_APPROVE:
        approved_at = reviewed_at
        cur.execute(
            """
            UPDATE wbb.onboarding_application
            SET status = 'APPROVED',
                reviewed_dt = %s,
                approved_dt = %s,
                reviewed_by = 'AUTO_REVIEW'
            WHERE application_id = %s
            """,
            (reviewed_at, approved_at, application_id),
        )
        # Activate products
        products = PRODUCT_ASSIGNMENTS.get(company_size, ['CHQ001'])
        for code in products:
            cur.execute(
                "SELECT product_id FROM wbb.banking_product WHERE product_code = %s",
                (code,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    INSERT INTO wbb.customer_product
                        (customer_id, product_id, application_id, activated_dt, activated_by)
                    VALUES (%s, %s, %s, %s, 'AUTO_ACTIVATE')
                    ON CONFLICT DO NOTHING
                    """,
                    (customer_id, row[0], application_id,
                     approved_at + timedelta(hours=random.randint(1, 4))),
                )
        return 'APPROVED'

    elif outcome < P_APPROVE + P_DECLINE:
        decline_code = random.choice(DECLINE_CODES)
        cur.execute(
            """
            UPDATE wbb.onboarding_application
            SET status = 'DECLINED',
                reviewed_dt = %s,
                reviewed_by = 'AUTO_REVIEW',
                decline_reason_code = %s
            WHERE application_id = %s
            """,
            (reviewed_at, decline_code, application_id),
        )
        return 'DECLINED'

    else:
        cur.execute(
            """
            UPDATE wbb.onboarding_application
            SET status = 'ABANDONED'
            WHERE application_id = %s
            """,
            (application_id,),
        )
        return 'ABANDONED'


def seed(days_back=30):
    """Insert a batch of historical records spread over the past N days."""
    print(f'Seeding {days_back} days of historical data...')
    conn = psycopg2.connect(DSN)
    total = 0
    try:
        for day_offset in range(days_back, 0, -1):
            date = datetime.utcnow().replace(hour=0, minute=0, second=0) - timedelta(days=day_offset)
            n = random.randint(8, 25)
            with conn.cursor() as cur:
                for _ in range(n):
                    submitted_at = date + timedelta(
                        hours=random.randint(8, 18),
                        minutes=random.randint(0, 59),
                    )
                    size = random.choice(COMPANY_SIZES)
                    cid, aid = submit_application(cur, submitted_at)
                    resolve_application(cur, aid, cid, size, submitted_at)
                    total += 1
            conn.commit()
            print(f'  Day -{day_offset:2d}: inserted {n} applications', flush=True)
    finally:
        conn.close()
    print(f'Seed complete. {total} applications inserted.')


def stream(interval_seconds=8):
    """Continuously insert new applications. For live demo use."""
    print(f'Streaming new onboarding events every ~{interval_seconds}s. Ctrl+C to stop.\n')
    conn = psycopg2.connect(DSN)
    count = 0
    try:
        while True:
            with conn.cursor() as cur:
                size = random.choice(COMPANY_SIZES)
                cid, aid = submit_application(cur)
                outcome = resolve_application(cur, aid, cid, size, datetime.utcnow())
                conn.commit()
                count += 1
                ts = datetime.utcnow().strftime('%H:%M:%S')
                print(f'[{ts}] #{count:4d}  application_id={aid:5d}  outcome={outcome}', flush=True)

            jitter = interval_seconds * (0.5 + random.random())
            time.sleep(jitter)

    except KeyboardInterrupt:
        print(f'\nStopped after {count} events.')
    finally:
        conn.close()


def demo(tick_seconds=2):
    """
    Pipeline-aware streaming mode for live demos.

    Each tick does three things:
      1. Submit a new application (status = SUBMITTED)
      2. Advance the oldest SUBMITTED to IN_REVIEW
      3. Resolve the oldest IN_REVIEW to APPROVED / DECLINED / ABANDONED

    This keeps the funnel populated with visible counts at every stage
    and makes the live feed show applications moving through states.
    """
    print(f'Demo mode: pipeline streaming every ~{tick_seconds}s. Ctrl+C to stop.\n')
    conn = psycopg2.connect(DSN)
    submitted_count = 0
    try:
        while True:
            now = datetime.utcnow()
            with conn.cursor() as cur:

                # 1. Submit a new application
                size = random.choice(COMPANY_SIZES)
                cid, aid = submit_application(cur, submitted_at=now)
                submitted_count += 1

                # 2. Advance oldest SUBMITTED → IN_REVIEW
                # Exclude the application just submitted so it waits at least one tick.
                cur.execute("""
                    UPDATE wbb.onboarding_application
                    SET status = 'IN_REVIEW'
                    WHERE application_id = (
                        SELECT a.application_id
                        FROM wbb.onboarding_application a
                        JOIN wbb.customer c ON c.customer_id = a.customer_id
                        WHERE a.status = 'SUBMITTED'
                          AND c.is_test = FALSE
                          AND a.application_id != %s
                        ORDER BY a.submitted_dt
                        LIMIT 1
                    )
                    RETURNING application_id
                """, (aid,))
                advanced = cur.fetchone()

                # 3. Resolve oldest IN_REVIEW → APPROVED / DECLINED / ABANDONED
                cur.execute("""
                    SELECT a.application_id, a.customer_id, c.company_size, a.submitted_dt
                    FROM wbb.onboarding_application a
                    JOIN wbb.customer c ON c.customer_id = a.customer_id
                    WHERE a.status = 'IN_REVIEW' AND c.is_test = FALSE
                    ORDER BY a.submitted_dt
                    LIMIT 1
                """)
                row = cur.fetchone()
                outcome = None
                if row:
                    r_aid, r_cid, r_size, r_submitted = row
                    outcome = resolve_application(cur, r_aid, r_cid, r_size or 'SMALL', r_submitted)

                conn.commit()

            ts = now.strftime('%H:%M:%S')
            adv_str = f'  advanced={advanced[0]}' if advanced else ''
            out_str = f'  resolved={outcome}' if outcome else ''
            print(f'[{ts}] submitted={aid}{adv_str}{out_str}', flush=True)

            time.sleep(tick_seconds + random.uniform(-0.3, 0.3))

    except KeyboardInterrupt:
        print(f'\nStopped after {submitted_count} submissions.')
    finally:
        conn.close()


def status():
    """Print a live summary of the current data state."""
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                                          AS total_applications,
                    SUM(CASE WHEN status = 'APPROVED'  THEN 1 END)   AS approved,
                    SUM(CASE WHEN status = 'DECLINED'  THEN 1 END)   AS declined,
                    SUM(CASE WHEN status = 'ABANDONED' THEN 1 END)   AS abandoned,
                    SUM(CASE WHEN status IN ('SUBMITTED','IN_REVIEW') THEN 1 END) AS in_progress
                FROM wbb.onboarding_application a
                JOIN wbb.customer c ON c.customer_id = a.customer_id
                WHERE c.is_test = FALSE
            """)
            row = cur.fetchone()
            print(f'\n=== WBB Operational DB — Current State ===')
            print(f'  Total applications : {row[0]}')
            print(f'  Approved           : {row[1]}')
            print(f'  Declined           : {row[2]}')
            print(f'  Abandoned          : {row[3]}')
            print(f'  In progress        : {row[4]}')

            cur.execute("""
                SELECT business_category, COUNT(*) AS n
                FROM wbb.customer
                WHERE is_test = FALSE
                GROUP BY business_category
                ORDER BY n DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            print(f'\n  Top segments:')
            for r in rows:
                print(f'    {r[0]:<30s} {r[1]}')
            print()
    finally:
        conn.close()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if cmd == 'seed':
        seed(days_back=int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif cmd == 'stream':
        stream(interval_seconds=int(sys.argv[2]) if len(sys.argv) > 2 else 8)
    elif cmd == 'demo':
        demo(tick_seconds=int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    elif cmd == 'status':
        status()
    else:
        print(f'Unknown command: {cmd}')
        print('Usage: generate.py [seed [days] | demo [tick_secs] | stream [interval] | status]')
        sys.exit(1)
