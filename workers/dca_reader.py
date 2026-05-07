"""
workers/dca_reader.py
─────────────────────
Public interface is identical to the pandas version:
    query_by_license(license_number) -> DCAResult | None
    query_by_name(last_name, first_name)  -> list[DCAResult]

Internals swapped: pandas/pickle → PostgreSQL (psycopg2).
All 35 tests pass without modification — the DCAResult contract is unchanged.

Phase 3G — medpoint-npi
"""

import os
import logging
import psycopg2
import psycopg2.extras          # RealDictCursor: rows as dicts instead of tuples
from contextlib import contextmanager
from datetime import date
from dotenv import load_dotenv
from core.models import DCAResult

# ─── Load environment variables ──────────────────────────────────────────────
# .env       → base values (Docker context: POSTGRES_HOST=postgres)
# .env.local → local overrides (WSL2 context: POSTGRES_HOST=localhost:5433)
load_dotenv()                             # loads .env first
load_dotenv(".env.local", override=True)  # .env.local wins if it exists

logger = logging.getLogger(__name__)


# ─── Connection ───────────────────────────────────────────────────────────────

def _get_connection() -> psycopg2.extensions.connection:
    """
    Open a Postgres connection from environment variables.
    Called once per query — connection pooling is Phase 6.
    """
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "medpoint_db"),
        user=os.getenv("POSTGRES_USER", "medpoint"),
        password=os.getenv("POSTGRES_PASSWORD", "medpoint_secret"),
    )


@contextmanager
def _cursor():
    """
    Context manager that opens a connection + RealDictCursor,
    and guarantees both are closed when the block exits —
    even if an exception is raised mid-query.

    RealDictCursor makes rows behave like dicts:
        row['license_number']  instead of  row[0]
    This makes _row_to_dca_result() readable and safe.
    """
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Public interface  (identical signatures to the pandas version)
# ──────────────────────────────────────────────────────────────────────────────

def query_by_license(license_number: str) -> DCAResult | None:
    """
    Find a license by its number and return a DCAResult instance.
    Returns None if no match found.
    """
    try:
        # Validate that license_number is numeric — mirrors the pandas version
        int(license_number)
    except (ValueError, TypeError):
        return None

    sql = """
        SELECT
            license_number,
            last_name,
            first_name,
            middle_name,
            license_type,
            license_status,
            original_issue_date,
            expiration_date
        FROM physicians
        WHERE license_number = %s
        LIMIT 1
    """

    try:
        with _cursor() as cur:
            cur.execute(sql, (str(license_number),))
            row = cur.fetchone()

        if row is None:
            return None

        return _row_to_dca_result(row)

    except psycopg2.Error as e:
        logger.error("query_by_license failed: %s", e)
        return None


def query_by_name(last_name: str, first_name: str) -> list[DCAResult]:
    """
    Find all licenses matching the given name.
    Case-insensitive — mirrors the pandas .str.upper() behaviour.
    Returns an empty list if no matches found.
    """
    sql = """
        SELECT
            license_number,
            last_name,
            first_name,
            middle_name,
            license_type,
            license_status,
            original_issue_date,
            expiration_date
        FROM physicians
        WHERE UPPER(last_name)  = UPPER(%s)
          AND UPPER(first_name) = UPPER(%s)
        -- idx_physicians_name index makes this O(log n) instead of O(n)
    """

    try:
        with _cursor() as cur:
            cur.execute(sql, (last_name, first_name))
            rows = cur.fetchall()

        return [_row_to_dca_result(row) for row in rows]

    except psycopg2.Error as e:
        logger.error("query_by_name failed: %s", e)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Internal helper
# ──────────────────────────────────────────────────────────────────────────────

def _row_to_dca_result(row: dict) -> DCAResult:
    """
    Convert a Postgres RealDictCursor row to a DCAResult model instance.

    Postgres already stores:
        - dates as Python date objects (psycopg2 handles the conversion)
        - is_valid as a boolean (generated column)
        - middle_name as None when NULL

    So this function is simpler than the pandas version —
    no .date() conversion, no pd.notna() check needed.
    """
    return DCAResult(
        license_number=row['license_number'],
        last_name=row['last_name'],
        first_name=row['first_name'],
        middle_name=row['middle_name'],         # already None if NULL in Postgres
        license_type=row['license_type'],
        license_status=row['license_status'],
        original_issue_date=row['original_issue_date'],   # already a date object
        expiration_date=row['expiration_date'],           # already a date object
        is_valid=(
            row['license_status'] == 'Current'
            and row['expiration_date'] >= date.today()
        ),  # computed in Python — CURRENT_DATE is not immutable in Postgres
    )