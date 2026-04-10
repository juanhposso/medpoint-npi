"""
tests/test_npi_fetcher.py
────────────────────────────────────────────────────────
Unit tests for the NPI fetcher and Pydantic models.
Run with:  pytest tests/ -v
"""

import pytest
import responses as rsps
from core.models import NPIRecord, NPIAddress, NPITaxonomy, NPINotFoundError, NPIAPIError, NPIValidationError
from workers.npi_fetcher import (
    fetch_npi,
    _pick_primary_taxonomy,
    _pick_address,
    _parse_result,
    NPI_API_BASE_URL,
)


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

VALID_NPI = "1234567890"

SAMPLE_API_RESPONSE = {
    "result_count": 1,
    "results": [
        {
            "number": VALID_NPI,
            "basic": {
                "first_name": "Juan",
                "last_name": "Hernandez",
                "credential": "M.D.",
                "gender": "M",
            },
            "taxonomies": [
                {
                    "code": "207Q00000X",
                    "desc": "Family Medicine",
                    "primary": True,
                    "state": "CA",
                    "license": "G12345",
                },
                {
                    "code": "207R00000X",
                    "desc": "Internal Medicine",
                    "primary": False,
                    "state": None,
                    "license": None,
                },
            ],
            "addresses": [
                {
                    "address_purpose": "LOCATION",
                    "address_1": "123 Main St",
                    "address_2": "Suite 400",
                    "city": "Los Angeles",
                    "state": "CA",
                    "postal_code": "90001-1234",
                    "telephone_number": "310-555-0100",
                    "fax_number": "310-555-0199",
                },
                {
                    "address_purpose": "MAILING",
                    "address_1": "PO Box 999",
                    "address_2": "",
                    "city": "Los Angeles",
                    "state": "CA",
                    "postal_code": "90002",
                    "telephone_number": "310-555-0200",
                    "fax_number": None,
                },
            ],
        }
    ],
}

NOT_FOUND_RESPONSE = {"result_count": 0, "results": []}


# ──────────────────────────────────────────────────────────────────
# Helper to register a mock GET with responses library
# ──────────────────────────────────────────────────────────────────

def _mock_npi_get(json_body: dict, status: int = 200):
    rsps.add(
        rsps.GET,
        NPI_API_BASE_URL,
        json=json_body,
        status=status,
    )


# ══════════════════════════════════════════════════════════════════
# 1. NPIAddress – Unit tests
# ══════════════════════════════════════════════════════════════════

class TestNPIAddress:
    def test_phone_normalised_to_digits(self):
        addr = NPIAddress(address_type="LOCATION", telephone_number="(310) 555-0100")
        assert addr.telephone_number == "3105550100"

    def test_fax_normalised_to_digits(self):
        addr = NPIAddress(address_type="LOCATION", fax_number="1-800-123-4567")
        assert addr.fax_number == "18001234567"

    def test_empty_phone_returns_none(self):
        addr = NPIAddress(address_type="LOCATION", telephone_number="")
        assert addr.telephone_number is None

    def test_zip_truncated_to_5_digits(self):
        addr = NPIAddress(address_type="LOCATION", postal_code="90001-1234")
        assert addr.postal_code == "90001"

    def test_state_uppercased(self):
        addr = NPIAddress(address_type="MAILING", state="ca")
        assert addr.state == "CA"

    def test_none_fax_stays_none(self):
        addr = NPIAddress(address_type="LOCATION", fax_number=None)
        assert addr.fax_number is None


# ══════════════════════════════════════════════════════════════════
# 2. NPIRecord – Unit tests
# ══════════════════════════════════════════════════════════════════

class TestNPIRecord:
    def _make_record(self, **kwargs) -> NPIRecord:
        defaults = dict(npi=VALID_NPI, first_name="Juan", last_name="Hernandez")
        defaults.update(kwargs)
        return NPIRecord(**defaults)

    def test_valid_npi_accepted(self):
        r = self._make_record()
        assert r.npi == VALID_NPI

    def test_npi_too_short_raises(self):
        with pytest.raises(Exception):
            self._make_record(npi="12345")

    def test_npi_non_digits_raises(self):
        with pytest.raises(Exception):
            self._make_record(npi="12345abcde")

    def test_credential_cleaned(self):
        r = self._make_record(credential="M.D.")
        assert r.credential == "MD"

    def test_full_name_with_credential(self):
        r = self._make_record(credential="MD")
        assert r.full_name == "Juan Hernandez, MD"

    def test_full_name_without_credential(self):
        r = self._make_record(credential=None)
        assert r.full_name == "Juan Hernandez"

    def test_specialty_from_taxonomy(self):
        taxonomy = NPITaxonomy(code="207Q00000X", description="Family Medicine", primary=True)
        r = self._make_record(primary_taxonomy=taxonomy)
        assert r.specialty == "Family Medicine"

    def test_specialty_empty_when_no_taxonomy(self):
        r = self._make_record(primary_taxonomy=None)
        assert r.specialty == ""

    def test_telephone_resolved_from_location(self):
        loc = NPIAddress(address_type="LOCATION", telephone_number="3105550100")
        mail = NPIAddress(address_type="MAILING", telephone_number="3105550200")
        r = self._make_record(location_address=loc, mailing_address=mail)
        assert r.telephone == "3105550100"

    def test_telephone_falls_back_to_mailing(self):
        mail = NPIAddress(address_type="MAILING", telephone_number="3105550200")
        r = self._make_record(location_address=None, mailing_address=mail)
        assert r.telephone == "3105550200"

    def test_no_address_telephone_is_none(self):
        r = self._make_record(location_address=None, mailing_address=None)
        assert r.telephone is None


# ══════════════════════════════════════════════════════════════════
# 3. Internal helpers
# ══════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_pick_primary_taxonomy_correct(self):
        taxonomies = [
            {"code": "A", "desc": "Secondary", "primary": False},
            {"code": "B", "desc": "Primary", "primary": True},
        ]
        result = _pick_primary_taxonomy(taxonomies)
        assert result is not None
        assert result.description == "Primary"
        assert result.primary is True

    def test_pick_primary_taxonomy_fallback_to_first(self):
        taxonomies = [
            {"code": "A", "desc": "Only one", "primary": False},
        ]
        result = _pick_primary_taxonomy(taxonomies)
        assert result is not None
        assert result.description == "Only one"

    def test_pick_primary_taxonomy_empty_returns_none(self):
        assert _pick_primary_taxonomy([]) is None

    def test_pick_address_location(self):
        addresses = [
            {"address_purpose": "MAILING", "city": "SF", "state": "CA", "postal_code": "94101"},
            {"address_purpose": "LOCATION", "city": "LA", "state": "CA", "postal_code": "90001"},
        ]
        result = _pick_address(addresses, "LOCATION")
        assert result is not None
        assert result.city == "LA"

    def test_pick_address_missing_type_returns_none(self):
        addresses = [
            {"address_purpose": "MAILING", "city": "SF", "state": "CA", "postal_code": "94101"},
        ]
        assert _pick_address(addresses, "LOCATION") is None

    def test_parse_result_full_record(self):
        raw = SAMPLE_API_RESPONSE["results"][0]
        record = _parse_result(raw)
        assert record.npi == VALID_NPI
        assert record.first_name == "Juan"
        assert record.credential == "MD"
        assert record.specialty == "Family Medicine"
        assert record.location_address is not None
        assert record.location_address.city == "Los Angeles"
        assert record.telephone == "3105550100"   # from LOCATION
        assert record.fax == "3105550199"


# ══════════════════════════════════════════════════════════════════
# 4. fetch_npi – Integration tests (HTTP mocked)
# ══════════════════════════════════════════════════════════════════

@rsps.activate
class TestFetchNPI:
    def test_happy_path_returns_record(self):
        _mock_npi_get(SAMPLE_API_RESPONSE)
        record = fetch_npi(VALID_NPI)
        assert isinstance(record, NPIRecord)
        assert record.npi == VALID_NPI
        assert record.last_name == "Hernandez"

    def test_invalid_npi_format_raises_before_network(self):
        # No mock needed: validation fires before HTTP call
        with pytest.raises(ValueError, match="Invalid NPI format"):
            fetch_npi("12345")

    def test_invalid_npi_with_letters_raises(self):
        with pytest.raises(ValueError):
            fetch_npi("12345ABCDE")

    def test_npi_not_found_raises_npi_not_found(self):
        _mock_npi_get(NOT_FOUND_RESPONSE)
        with pytest.raises(NPINotFoundError):
            fetch_npi(VALID_NPI)

    def test_http_500_raises_npi_api_error(self):
        _mock_npi_get({}, status=500)
        with pytest.raises(NPIAPIError, match="HTTP 500"):
            fetch_npi(VALID_NPI)

    def test_timeout_raises_npi_api_error(self):
        import requests.exceptions
        rsps.add(
            rsps.GET,
            NPI_API_BASE_URL,
            body=requests.exceptions.Timeout(),
        )
        with pytest.raises(NPIAPIError, match="timed out"):
            fetch_npi(VALID_NPI)

    def test_connection_error_raises_npi_api_error(self):
        import requests.exceptions
        rsps.add(
            rsps.GET,
            NPI_API_BASE_URL,
            body=requests.exceptions.ConnectionError("Connection refused"),
        )
        with pytest.raises(NPIAPIError, match="Connection error"):
            fetch_npi(VALID_NPI)

    def test_non_json_response_raises_npi_api_error(self):
        rsps.add(rsps.GET, NPI_API_BASE_URL, body="<html>not json</html>", status=200)
        with pytest.raises(NPIAPIError, match="non-JSON"):
            fetch_npi(VALID_NPI)

    def test_npi_whitespace_is_stripped(self):
        _mock_npi_get(SAMPLE_API_RESPONSE)
        record = fetch_npi(f"  {VALID_NPI}  ")
        assert record.npi == VALID_NPI

    def test_empty_results_list_raises_api_error(self):
        # result_count > 0 but empty results — malformed response
        _mock_npi_get({"result_count": 1, "results": []})
        with pytest.raises(NPIAPIError, match="empty results"):
            fetch_npi(VALID_NPI)