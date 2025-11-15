"""Datatyper for Brønnøysund-integrasjonen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

JSONMapping = dict[str, Any]
JSONList = list[Any]
JSONPayload = JSONMapping | JSONList

__all__ = ["BrregServiceResult", "CompanyStatus", "JSONPayload"]


@dataclass
class BrregServiceResult:
    """Resultat fra et HTTP-oppslag mot Brønnøysundregistrene."""

    data: Optional[JSONPayload]
    error_code: Optional[str]
    error_message: Optional[str]
    from_cache: bool


@dataclass
class CompanyStatus:
    """Statusfelt for et selskap hentet fra Enhetsregisteret."""

    orgnr: str
    konkurs: Optional[bool]
    avvikling: Optional[bool]
    mva_reg: Optional[bool]
    source: Optional[str]
