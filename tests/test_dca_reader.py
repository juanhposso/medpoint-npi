"""
tests/test_dca_reader.py
─────────────────────────
Tests for the Postgres-backed dca_reader.py (Phase 3G).

Strategy: mock _get_connection() so no real DB is needed.
RealDictCursor rows are plain dicts with lowercase keys — that's what
_row_to_dca_result() expects, so our fake rows match that format exactly.

All assertions are identical to the pandas version — the DCAResult
contract is unchanged. Only the mocking strategy changed.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import date

from workers.dca_reader import query_by_license, query_by_name


# ─── Fake rows ────────────────────────────────────────────────────────────────
# These mirror what psycopg2 RealDictCursor returns — plain dicts,
# lowercase keys matching column names, Python date objects for dates.

SMITH_ROW = {
    'license_number':      '12345',
    'last_name':           'SMITH',
    'first_name':          'JOHN',
    'middle_name':         'A',
    'license_type':        'Physician and Surgeon',
    'license_status':      'Current',
    'original_issue_date': date(2010, 1, 15),
    'expiration_date':     date(2028, 1, 31),
}

DOE_ROW = {
    'license_number':      '99999',
    'last_name':           'DOE',
    'first_name':          'JANE',
    'middle_name':         None,   # ← NULL in Postgres, tests NaN handling parity
    'license_type':        'Physician and Surgeon',
    'license_status':      'Expired',
    'original_issue_date': date(2005, 3, 1),
    'expiration_date':     date(2022, 1, 31),
}

SMITH_ROW_2 = {
    'license_number':      '54321',
    'last_name':           'SMITH',
    'first_name':          'JOHN',
    'middle_name':         'B',
    'license_type':        'Physician and Surgeon',
    'license_status':      'Current',
    'original_issue_date': date(2015, 5, 20),
    'expiration_date':     date(2025, 5, 31),
}


# ─── Mock builder ─────────────────────────────────────────────────────────────

def make_mock_conn(fetchone=None, fetchall=None):
    """
    Build a mock connection whose cursor returns the given fake rows.
    Mirrors the _cursor() context manager:
        conn.cursor(cursor_factory=...) → cursor
        cursor.fetchone() / cursor.fetchall()
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall or []

    # cursor is used as a context manager: `with conn.cursor(...) as cur`
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    return mock_conn


# ══════════════════════════════════════════════════════════════════════════════
# query_by_license
# ══════════════════════════════════════════════════════════════════════════════

def test_query_by_license_valid():
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchone=SMITH_ROW)):
        result = query_by_license('12345')

    assert result is not None
    assert result.license_number == '12345'
    assert result.last_name == 'SMITH'
    assert result.first_name == 'JOHN'
    assert result.middle_name == 'A'
    assert result.license_type == 'Physician and Surgeon'
    assert result.license_status == 'Current'
    assert result.original_issue_date == date(2010, 1, 15)
    assert result.expiration_date == date(2028, 1, 31)
    assert result.is_valid is True


def test_query_by_license_invalid():
    # License number not found — fetchone returns None
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchone=None)):
        result = query_by_license('00000')

    assert result is None


def test_query_by_license_expired():
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchone=DOE_ROW)):
        result = query_by_license('99999')

    assert result is not None
    assert result.license_number == '99999'
    assert result.last_name == 'DOE'
    assert result.first_name == 'JANE'
    assert result.middle_name is None   # ← NULL from Postgres → None in Python
    assert result.license_type == 'Physician and Surgeon'
    assert result.license_status == 'Expired'
    assert result.original_issue_date == date(2005, 3, 1)
    assert result.expiration_date == date(2022, 1, 31)
    assert result.is_valid is False


def test_query_by_license_non_numeric():
    # No DB call should be made — int('ABCDE') raises ValueError before querying
    with patch('workers.dca_reader._get_connection') as mock_conn:
        result = query_by_license('ABCDE')

    assert result is None
    mock_conn.assert_not_called()   # confirms we short-circuit before hitting DB


def test_query_by_license_leading_zeros():
    # '00012345' normalises to '12345' via str(int(license_number))
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchone=SMITH_ROW)):
        result = query_by_license('00012345')

    assert result is not None
    assert result.license_number == '12345'


# ══════════════════════════════════════════════════════════════════════════════
# query_by_name
# ══════════════════════════════════════════════════════════════════════════════

def test_query_by_name_valid():
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchall=[DOE_ROW])):
        results = query_by_name('DOE', 'JANE')

    assert len(results) == 1
    result = results[0]
    assert result.license_number == '99999'
    assert result.last_name == 'DOE'
    assert result.first_name == 'JANE'
    assert result.middle_name is None
    assert result.license_type == 'Physician and Surgeon'
    assert result.license_status == 'Expired'
    assert result.original_issue_date == date(2005, 3, 1)
    assert result.expiration_date == date(2022, 1, 31)
    assert result.is_valid is False


def test_query_by_name_case_insensitive():
    # SQL uses UPPER() on both sides — lowercase input still matches
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchall=[SMITH_ROW])):
        results = query_by_name('smith', 'john')

    assert len(results) == 1
    result = results[0]
    assert result.license_number == '12345'
    assert result.last_name == 'SMITH'
    assert result.first_name == 'JOHN'
    assert result.middle_name == 'A'
    assert result.license_type == 'Physician and Surgeon'
    assert result.license_status == 'Current'
    assert result.original_issue_date == date(2010, 1, 15)
    assert result.expiration_date == date(2028, 1, 31)
    assert result.is_valid is True


def test_query_by_name_no_match():
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchall=[])):
        results = query_by_name('NONEXISTENT', 'NAME')

    assert len(results) == 0


def test_query_by_name_multiple_matches():
    with patch('workers.dca_reader._get_connection', return_value=make_mock_conn(fetchall=[SMITH_ROW, SMITH_ROW_2])):
        results = query_by_name('SMITH', 'JOHN')

    assert len(results) == 2
    license_numbers = {result.license_number for result in results}
    assert license_numbers == {'12345', '54321'}