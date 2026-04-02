"""
tools/npi_fetcher.py
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
from pydantic import BaseModel, Field, field_validator, model_validator

load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Settings (from .env with sensible defaults)
# ──────────────────────────────────────────────────────────────────
NPI_API_BASE_URL: str = os.getenv("NPI_API_BASE_URL", "https://npiregistry.cms.hhs.gov/api/")
NPI_API_VERSION: str = os.getenv("NPI_API_VERSION", "2.1")
NPI_REQUEST_TIMEOUT: int = int(os.getenv("NPI_REQUEST_TIMEOUT", "10"))


# ──────────────────────────────────────────────────────────────────
# Pydantic Models
# ──────────────────────────────────────────────────────────────────

class NPIAddress(BaseModel):
    """Validated practice/mailing address."""

    address_type: str = Field(..., description="LOCATION | MAILING")
    address_1: str = ""
    address_2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    telephone_number: Optional[str] = None
    fax_number: Optional[str] = None

    @field_validator("telephone_number", "fax_number", mode="before")
    @classmethod
    def normalise_phone(cls, v: Optional[str]) -> Optional[str]:
        """Strip all non-digit characters; return None if empty."""
        if not v:
            return None
        digits = re.sub(r"\D", "", v)
        return digits if digits else None

    @field_validator("postal_code", mode="before")
    @classmethod
    def normalise_zip(cls, v: str) -> str:
        """Keep only first 5 digits of ZIP."""
        if not v:
            return ""
        return re.sub(r"\D", "", v)[:5]

    @field_validator("state", mode="before")
    @classmethod
    def upper_state(cls, v: str) -> str:
        return v.upper().strip() if v else ""


class NPITaxonomy(BaseModel):
    """Primary specialty/taxonomy block."""

    code: str = ""
    description: str = ""
    primary: bool = False
    state: Optional[str] = None   # state licence issued in (if any)
    license: Optional[str] = None


class NPIRecord(BaseModel):
    """
    Canonical representation of a single physician NPI record.
    All fields consumed downstream (fuzzy matching, LangGraph agents).
    """

    npi: str
    first_name: str = ""
    last_name: str = ""
    credential: str = ""          # e.g. "MD", "DO", "NP"
    gender: Optional[str] = None

    primary_taxonomy: Optional[NPITaxonomy] = None
    location_address: Optional[NPIAddress] = None  # preferred for matching
    mailing_address: Optional[NPIAddress] = None

    # Convenience aliases resolved by model_validator
    telephone: Optional[str] = None
    fax: Optional[str] = None

    @field_validator("npi")
    @classmethod
    def validate_npi(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{10}", v):
            raise ValueError(f"NPI must be exactly 10 digits, got: '{v}'")
        return v

    @field_validator("credential", mode="before")
    @classmethod
    def clean_credential(cls, v: Optional[str]) -> str:
        """Remove punctuation and normalise to upper-case."""
        if not v:
            return ""
        return re.sub(r"[^A-Za-z]", "", v).upper()

    @model_validator(mode="after")
    def resolve_contact(self) -> NPIRecord:
        """
        Populate top-level telephone/fax from the LOCATION address first,
        falling back to MAILING so downstream code has a single contact field.
        """
        preferred = self.location_address or self.mailing_address
        if preferred:
            self.telephone = preferred.telephone_number
            self.fax = preferred.fax_number
        return self

    @property
    def full_name(self) -> str:
        parts = filter(None, [self.first_name, self.last_name])
        name = " ".join(parts)
        if self.credential:
            name = f"{name}, {self.credential}"
        return name

    @property
    def specialty(self) -> str:
        return self.primary_taxonomy.description if self.primary_taxonomy else ""


# ──────────────────────────────────────────────────────────────────
# Custom Exceptions
# ──────────────────────────────────────────────────────────────────

class NPINotFoundError(Exception):
    """Raised when the NPI number returns zero results."""


class NPIAPIError(Exception):
    """Raised on HTTP errors or unexpected API responses."""


class NPIValidationError(Exception):
    """Raised when Pydantic validation fails for a raw API payload."""


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

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
        raise NPIAPIError(f"HTTP {response.status_code} for NPI {npi_number}: {exc}") from exc

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