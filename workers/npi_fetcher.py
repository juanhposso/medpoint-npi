"""
workers/npi_fetcher.py
────────────────────────────────────────────────────────
NPI Registry API client with Pydantic validation.

Public API docs:
  https://npiregistry.cms.hhs.gov/api-page

Key rules:
  - NPI must be exactly 10 digits.
  - We always extract the PRIMARY taxonomy only.
  - Addresses: we prefer LOCATION type; fall back to MAILING.
  - Phone/fax are normalised to digits-only strings.
"""

from __future__ import annotations

import os
import re
import logging
from typing import Optional
import requests
from dotenv import load_dotenv
from core.models import NPIAddress, NPITaxonomy, NPIRecord, NPINotFoundError, NPIAPIError, NPIValidationError

load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Settings (from .env with sensible defaults)
# ──────────────────────────────────────────────────────────────────
NPI_API_BASE_URL: str = os.getenv("NPI_API_BASE_URL", "https://npiregistry.cms.hhs.gov/api/")
NPI_API_VERSION: str = os.getenv("NPI_API_VERSION", "2.1")
NPI_REQUEST_TIMEOUT: int = int(os.getenv("NPI_REQUEST_TIMEOUT", "10"))





def _pick_primary_taxonomy(taxonomies: list[dict]) -> Optional[NPITaxonomy]:
    """Return the taxonomy block flagged as primary; fall back to first."""
    if not taxonomies:
        return None
    primary = next((t for t in taxonomies if t.get("primary")), taxonomies[0])
    return NPITaxonomy(
        code=primary.get("code", ""),
        description=primary.get("desc", ""),
        primary=primary.get("primary", False),
        state=primary.get("state"),
        license=primary.get("license"),
    )


def _pick_address(addresses: list[dict], addr_type: str) -> Optional[NPIAddress]:
    """Find the first address of the requested type and build NPIAddress."""
    match = next(
        (a for a in addresses if a.get("address_purpose", "").upper() == addr_type.upper()),
        None,
    )
    if not match:
        return None
    return NPIAddress(
        address_type=addr_type,
        address_1=match.get("address_1", ""),
        address_2=match.get("address_2", ""),
        city=match.get("city", ""),
        state=match.get("state", ""),
        postal_code=match.get("postal_code", ""),
        telephone_number=match.get("telephone_number"),
        fax_number=match.get("fax_number"),
    )


def _parse_result(raw: dict) -> NPIRecord:
    """Transform a single raw API result dict into a validated NPIRecord."""
    basic = raw.get("basic", {})
    taxonomies = raw.get("taxonomies", [])
    addresses = raw.get("addresses", [])

    try:
        return NPIRecord(
            npi=raw.get("number", ""),
            first_name=basic.get("first_name", ""),
            last_name=basic.get("last_name", ""),
            credential=basic.get("credential"),
            gender=basic.get("gender"),
            primary_taxonomy=_pick_primary_taxonomy(taxonomies),
            location_address=_pick_address(addresses, "LOCATION"),
            mailing_address=_pick_address(addresses, "MAILING"),
        )
    except Exception as exc:
        raise NPIValidationError(f"Pydantic validation failed: {exc}") from exc


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def fetch_npi(npi_number: str) -> NPIRecord:
    """
    Fetch and validate a single NPI record from the CMS NPI Registry.

    Args:
        npi_number: 10-digit NPI string.

    Returns:
        Validated NPIRecord.

    Raises:
        ValueError: If npi_number format is invalid (before network call).
        NPINotFoundError: If no record matches the NPI.
        NPIAPIError: On HTTP errors or malformed responses.
        NPIValidationError: If the response fails Pydantic validation.
    """
    npi_number = npi_number.strip()
    if not re.fullmatch(r"\d{10}", npi_number):
        raise ValueError(f"Invalid NPI format: '{npi_number}'. Must be 10 digits.")

    params = {
        "number": npi_number,
        "version": NPI_API_VERSION,
    }

    logger.info("Fetching NPI %s", npi_number)

    try:
        response = requests.get(
            NPI_API_BASE_URL,
            params=params,
            timeout=NPI_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise NPIAPIError(f"Request timed out after {NPI_REQUEST_TIMEOUT}s for NPI {npi_number}")
    except requests.exceptions.ConnectionError as exc:
        raise NPIAPIError(f"Connection error for NPI {npi_number}: {exc}") from exc
    except requests.exceptions.HTTPError as exc:
        raise NPIAPIError(f"HTTP {exc.response.status_code} for NPI {npi_number}: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise NPIAPIError("API returned non-JSON response.") from exc

    result_count = payload.get("result_count", 0)
    if result_count == 0:
        raise NPINotFoundError(f"No NPI record found for: {npi_number}")

    results = payload.get("results", [])
    if not results:
        raise NPIAPIError("API returned result_count > 0 but empty results list.")

    return _parse_result(results[0])