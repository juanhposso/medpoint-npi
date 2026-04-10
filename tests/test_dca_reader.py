import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from datetime import date

from workers.dca_reader import query_by_license, query_by_name


FAKE_DATA = pd.DataFrame([
    {
        'License Number': 12345,
        'Org/Last Name': 'SMITH',
        'First Name': 'JOHN',
        'Middle Name': 'A',
        'License Type': 'Physician and Surgeon',
        'License Status': 'Current',
        'Original Issue Date': pd.Timestamp('2010-01-15'),
        'Expiration Date': pd.Timestamp('2028-01-31'),
    },
    {
        'License Number': 99999,
        'Org/Last Name': 'DOE',
        'First Name': 'JANE',
        'Middle Name': np.nan,       # ← tests NaN handling
        'License Type': 'Physician and Surgeon',
        'License Status': 'Expired',
        'Original Issue Date': pd.Timestamp('2005-03-01'),
        'Expiration Date': pd.Timestamp('2022-01-31'),
    },
])


@pytest.fixture(autouse=True)
def mock_full_data():
    with patch('workers.dca_reader.full_data', FAKE_DATA):
        yield


# ══════════════════════════════════════════════════════════════════
# 1. Tests for query_by_license
# ══════════════════════════════════════════════════════════════════

def test_query_by_license_valid():
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
    result = query_by_license('00000')
    assert result is None

def test_query_by_license_expired():
    result = query_by_license('99999')
    assert result is not None
    assert result.license_number == '99999'
    assert result.last_name == 'DOE'
    assert result.first_name == 'JANE'
    assert result.middle_name is None  # ← tests NaN handling
    assert result.license_type == 'Physician and Surgeon'
    assert result.license_status == 'Expired'
    assert result.original_issue_date == date(2005, 3, 1)
    assert result.expiration_date == date(2022, 1, 31)
    assert result.is_valid is False

def test_query_by_license_non_numeric():
    result = query_by_license('ABCDE')
    assert result is None

def test_query_by_license_leading_zeros():
    result = query_by_license('00012345')
    assert result is not None
    assert result.license_number == '12345'


# ══════════════════════════════════════════════════════════════════
# 1. Tests for query_by_name
# ══════════════════════════════════════════════════════════════════

def test_query_by_name_valid():
    results = query_by_name('DOE', 'JANE')
    assert len(results) == 1
    result = results[0]
    assert result.license_number == '99999'
    assert result.last_name == 'DOE'
    assert result.first_name == 'JANE'
    assert result.middle_name is None  # ← tests NaN handling
    assert result.license_type == 'Physician and Surgeon'
    assert result.license_status == 'Expired'
    assert result.original_issue_date == date(2005, 3, 1)
    assert result.expiration_date == date(2022, 1, 31)
    assert result.is_valid is False

def test_query_by_name_case_insensitive():
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
    results = query_by_name('NONEXISTENT', 'NAME')
    assert len(results) == 0

def test_query_by_name_multiple_matches():
    # Add a duplicate entry to test multiple matches
    duplicate_data = pd.DataFrame([
        {
            'License Number': 54321,
            'Org/Last Name': 'SMITH',
            'First Name': 'JOHN',
            'Middle Name': 'B',
            'License Type': 'Physician and Surgeon',
            'License Status': 'Current',
            'Original Issue Date': pd.Timestamp('2015-05-20'),
            'Expiration Date': pd.Timestamp('2025-05-31'),
        }
    ])
    with patch('workers.dca_reader.full_data', pd.concat([FAKE_DATA, duplicate_data], ignore_index=True)):
        results = query_by_name('SMITH', 'JOHN')
        assert len(results) == 2
        license_numbers = {result.license_number for result in results}
        assert license_numbers == {'12345', '54321'}