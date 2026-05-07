"""
db/seed_dca.py
──────────────
One-time script that loads data/medical_board.xlsx into the physicians table.

Usage (from project root):
    python db/seed_dca.py

Requirements:
    - Postgres must be running and reachable (docker-compose up postgres)
    - .env file must exist with POSTGRES_* variables
    - data/medical_board.xlsx must exist

Design decisions:
    - ON CONFLICT DO NOTHING  → safe to run multiple times (idempotent)
    - Batch inserts (1 000 rows at a time) → avoids memory spikes on large files
    - is_valid is NOT inserted → Postgres generates it automatically
    - Same column selection and dtype casting as dca_reader.py → data consistency
"""

import os
import sys
import pandas as pd
import psycopg2
import psycopg2.extras       # for execute_values (batch insert)
from dotenv import load_dotenv
from datetime import date

# ─── Load environment variables ──────────────────────────────────────────────
# .env       → base values (Docker context: POSTGRES_HOST=postgres)
# .env.local → local overrides (host context: POSTGRES_HOST=localhost)

load_dotenv()                             # loads .env first
load_dotenv(".env.local", override=True)  # .env.local wins if it exists
 

# ─── Config ──────────────────────────────────────────────────────────────────
EXCEL_PATH = "./data/medical_board.xlsx"

COLUMNS = [
    'License Number',
    'Org/Last Name',
    'First Name',
    'Middle Name',
    'License Type',
    'License Status',
    'Original Issue Date',
    'Expiration Date',
]

DTYPES = {
    'License Number':   'int32',
    'Org/Last Name':    'str',
    'First Name':       'str',
    'Middle Name':      'str',
    'License Type':     'str',
    'License Status':   'str',
}

BATCH_SIZE = 1_000   # rows per INSERT — balances speed vs memory


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_connection() -> psycopg2.extensions.connection:
    """Build a Postgres connection from .env variables."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        # When running from WSL2 host, Postgres is on 5433 (mapped port).
        # When running inside Docker, it's on 5432.
        # .env sets POSTGRES_HOST=postgres (Docker) but host runner uses localhost.
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "medpoint_db"),
        user=os.getenv("POSTGRES_USER", "medpoint"),
        password=os.getenv("POSTGRES_PASSWORD", "medpoint_secret"),
    )


def _safe_str(value, nullable: bool = False):
    """Handle float NaN from pandas in string columns."""
    if pd.isna(value):
        return None if nullable else ""
    return str(value).strip()


def _safe_date(value):
    """Convert pandas Timestamp to Python date. Skips NaT rows."""
    if pd.isna(value):
        raise ValueError(f"Missing date value: {value}")
    if hasattr(value, 'date'):
        return value.date()
    return value


def clean_row(row: pd.Series) -> tuple:
    """
    Convert a DataFrame row to a tuple ready for Postgres insertion.
    Order must match the INSERT column list below exactly.
    is_valid is excluded — computed in Python by dca_reader.py.
    """
    return (
        str(row['License Number']),                    # license_number
        _safe_str(row['Org/Last Name']),               # last_name
        _safe_str(row['First Name']),                  # first_name
        _safe_str(row['Middle Name'], nullable=True),  # middle_name -> None if empty
        _safe_str(row['License Type']),                # license_type
        _safe_str(row['License Status']),              # license_status
        _safe_date(row['Original Issue Date']),        # original_issue_date
        _safe_date(row['Expiration Date']),            # expiration_date
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:

    # ── 1. Validate Excel file exists ────────────────────────────────────────
    if not os.path.exists(EXCEL_PATH):
        print(f"[ERROR] Excel file not found: {EXCEL_PATH}")
        print("        Make sure you are running this script from the project root.")
        sys.exit(1)

    # ── 2. Read Excel — same logic as dca_reader.py for consistency ──────────
    print(f"[1/4] Reading {EXCEL_PATH} ...")
    df = pd.read_excel(
        EXCEL_PATH,
        engine="openpyxl",
        dtype=DTYPES,
        usecols=COLUMNS,
    )
    print(f"      {len(df):,} rows loaded from Excel")

    # ── 3. Connect to Postgres ───────────────────────────────────────────────
    print("[2/4] Connecting to Postgres ...")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print(f"      Connected to {os.getenv('POSTGRES_DB')} "
              f"on {os.getenv('POSTGRES_HOST', 'localhost')}")
    except psycopg2.OperationalError as e:
        print(f"[ERROR] Could not connect to Postgres: {e}")
        print("        Is docker-compose up postgres running?")
        sys.exit(1)

    # ── 4. Batch insert ──────────────────────────────────────────────────────
    print(f"[3/4] Inserting rows in batches of {BATCH_SIZE:,} ...")

    INSERT_SQL = """
        INSERT INTO physicians (
            license_number,
            last_name,
            first_name,
            middle_name,
            license_type,
            license_status,
            original_issue_date,
            expiration_date
        )
        VALUES %s
        ON CONFLICT (license_number) DO NOTHING
        -- ↑ Idempotent: running the script twice won't duplicate rows.
        --   If you want to update existing rows on re-run, change to:
        --   ON CONFLICT (license_number) DO UPDATE SET ...
    """

    total_inserted = 0
    batch = []

    for i, (_, row) in enumerate(df.iterrows()):
        try:
            batch.append(clean_row(row))
        except Exception as e:
            # Log bad rows but don't abort the entire load
            print(f"      [WARN] Skipping row {i} — {e}")
            continue

        if len(batch) == BATCH_SIZE:
            psycopg2.extras.execute_values(cursor, INSERT_SQL, batch)
            conn.commit()
            total_inserted += len(batch)
            print(f"      {total_inserted:,} rows inserted so far ...")
            batch = []

    # Insert any remaining rows that didn't fill a full batch
    if batch:
        psycopg2.extras.execute_values(cursor, INSERT_SQL, batch)
        conn.commit()
        total_inserted += len(batch)

    # ── 5. Report ────────────────────────────────────────────────────────────
    print(f"[4/4] Done.")
    print(f"      {total_inserted:,} rows inserted into physicians table")
    print(f"      {len(df) - total_inserted:,} rows skipped (duplicates or bad data)")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()