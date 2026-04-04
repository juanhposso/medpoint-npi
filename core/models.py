"""
Pydantic models for NPI records and related data structures.

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
from pydantic import BaseModel, Field, field_validator, model_validator


logger = logging.getLogger(__name__)



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