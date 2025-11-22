"""HTTP-klient for Brønnøysundregistrenes API-er."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional

import requests  # type: ignore[import-untyped, import-not-found]

from ..constants import BRREG_URL_TMPL, ENHETSREGISTER_URL_TMPL
from .brreg_cache import (
    DEFAULT_TIMEOUT,
    REQUESTS_CACHE_AVAILABLE,
    fallback_cache_get,
    fallback_cache_set,
    get_session,
    make_cache_key,
)
from .brreg_models import BrregServiceResult, CompanyStatus

__all__ = [
    "fetch_regnskapsregister",
    "fetch_enhetsregister",
    "get_company_status",
]

_LOGGER = logging.getLogger(__name__)

_NETWORK_ERROR_CODES = {
    "timeout",
    "connection_error",
    "rate_limited",
    "server_error",
    "http_error",
    "request_error",
}


class _ListPolicy(str, Enum):
    DISALLOW = "disallow"
    FIRST_DICT = "first_dict"
    PASSTHROUGH = "passthrough"


def _interpret_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "ja", "j", "yes"}:
            return True
        if lowered in {"false", "0", "nei", "n", "no"}:
            return False
    return None


def _fetch_json(
    url: str,
    source_label: str,
    *,
    list_policy: _ListPolicy = _ListPolicy.DISALLOW,
) -> BrregServiceResult:
    cache_key = make_cache_key(url, list_policy.value)
    if not REQUESTS_CACHE_AVAILABLE:
        cached_result = fallback_cache_get(cache_key)
        if cached_result is not None:
            return cached_result

    def finalize(result: BrregServiceResult) -> BrregServiceResult:
        if not REQUESTS_CACHE_AVAILABLE:
            fallback_cache_set(cache_key, result)
        return result

    session = get_session()
    try:
        response = session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.Timeout:
        return finalize(
            BrregServiceResult(None, "timeout", f"{source_label}: tidsavbrudd.", False)
        )
    except requests.ConnectionError as exc:
        return finalize(
            BrregServiceResult(
                None,
                "connection_error",
                f"{source_label}: tilkoblingsfeil ({exc}).",
                False,
            )
        )
    except requests.RequestException as exc:
        return finalize(
            BrregServiceResult(
                None,
                "request_error",
                f"{source_label}: uventet feil ({exc}).",
                False,
            )
        )

    from_cache = bool(getattr(response, "from_cache", False))

    if response.status_code == 404:
        return finalize(
            BrregServiceResult(
                None,
                "not_found",
                f"{source_label}: ingen treff for organisasjonsnummeret.",
                from_cache,
            )
        )
    if response.status_code == 429:
        return finalize(
            BrregServiceResult(
                None,
                "rate_limited",
                f"{source_label}: for mange forespørsler (429).",
                from_cache,
            )
        )
    if response.status_code >= 500:
        return finalize(
            BrregServiceResult(
                None,
                "server_error",
                f"{source_label}: tjenesten svarte med {response.status_code}.",
                from_cache,
            )
        )
    try:
        response.raise_for_status()
    except requests.HTTPError:
        return finalize(
            BrregServiceResult(
                None,
                "http_error",
                f"{source_label}: tjenesten svarte med {response.status_code}.",
                from_cache,
            )
        )

    try:
        payload = response.json()
    except ValueError as exc:
        return finalize(
            BrregServiceResult(
                None,
                "invalid_json",
                f"{source_label}: ugyldig JSON ({exc}).",
                from_cache,
            )
        )

    if isinstance(payload, list):
        if list_policy is _ListPolicy.FIRST_DICT:
            for element in payload:
                if isinstance(element, dict):
                    return finalize(BrregServiceResult(element, None, None, from_cache))
            return finalize(
                BrregServiceResult(
                    None,
                    "invalid_json",
                    f"{source_label}: uventet svarformat (liste).",
                    from_cache,
                )
            )
        if list_policy is _ListPolicy.PASSTHROUGH:
            return finalize(BrregServiceResult(payload, None, None, from_cache))

    if not isinstance(payload, dict):
        return finalize(
            BrregServiceResult(
                None,
                "invalid_json",
                f"{source_label}: uventet svarformat.",
                from_cache,
            )
        )

    return finalize(BrregServiceResult(payload, None, None, from_cache))


def fetch_regnskapsregister(orgnr: str) -> BrregServiceResult:
    """Henter data fra Regnskapsregisteret for et organisasjonsnummer."""

    try:
        normalized = _normalize_orgnr(orgnr)
    except ValueError as exc:
        return BrregServiceResult(None, "invalid_orgnr", str(exc), False)
    url = BRREG_URL_TMPL.format(orgnr=normalized)
    return _fetch_json(url, "Regnskapsregisteret", list_policy=_ListPolicy.PASSTHROUGH)


def fetch_enhetsregister(orgnr: str) -> BrregServiceResult:
    """Henter enhetsdata for et organisasjonsnummer."""

    try:
        normalized = _normalize_orgnr(orgnr)
    except ValueError as exc:
        return BrregServiceResult(None, "invalid_orgnr", str(exc), False)
    url = ENHETSREGISTER_URL_TMPL.format(orgnr=normalized)
    return _fetch_json(url, "Enhetsregisteret", list_policy=_ListPolicy.FIRST_DICT)


def _normalize_orgnr(orgnr: str) -> str:
    digits = "".join(ch for ch in str(orgnr) if ch.isdigit())
    if len(digits) != 9:
        raise ValueError("Organisasjonsnummer må bestå av 9 sifre.")
    return digits


def get_company_status(orgnr: str) -> CompanyStatus:
    """Returnerer statusfelt for et selskap basert på Enhetsregisteret."""

    try:
        normalized = _normalize_orgnr(orgnr)
    except ValueError:
        cleaned = "".join(ch for ch in str(orgnr) if ch.isdigit())
        return CompanyStatus(cleaned, None, None, None, None)
    result = fetch_enhetsregister(normalized)
    if result.error_code:
        message = result.error_message or result.error_code
        if result.error_code in _NETWORK_ERROR_CODES:
            _LOGGER.warning(
                "Brreg-status: %s (orgnr=%s)",
                message,
                normalized,
            )
            return CompanyStatus(normalized, None, None, None, None)
        if result.error_code == "not_found":
            return CompanyStatus(normalized, None, None, None, "Brønnøysundregistrene")
        _LOGGER.error("Brreg-status: %s (orgnr=%s)", message, normalized)
        return CompanyStatus(normalized, None, None, None, None)

    data: Dict[str, Any] = {}
    if isinstance(result.data, dict):
        data = result.data
    konkurs = _interpret_bool(data.get("konkurs"))
    under_avvikling = _interpret_bool(data.get("underAvvikling"))
    under_tvangsopplosning = _interpret_bool(
        data.get("underTvangsavviklingEllerTvangsoppløsning")
    )
    avvik_candidates = [
        value
        for value in (under_avvikling, under_tvangsopplosning)
        if value is not None
    ]
    avvikling = any(avvik_candidates) if avvik_candidates else None
    mva_reg = _interpret_bool(data.get("registrertIMvaregisteret"))

    return CompanyStatus(
        orgnr=normalized,
        konkurs=konkurs,
        avvikling=avvikling,
        mva_reg=mva_reg,
        source="Brønnøysundregistrene",
    )
