"""Fasade for Brønnøysund-integrasjonen."""

from __future__ import annotations

from .brreg_client import (
    fetch_enhetsregister,
    fetch_regnskapsregister,
    get_company_status,
)
from .brreg_models import BrregServiceResult, CompanyStatus

__all__ = [
    "BrregServiceResult",
    "CompanyStatus",
    "fetch_enhetsregister",
    "fetch_regnskapsregister",
    "get_company_status",
]
