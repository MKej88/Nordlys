"""Service-lag for oppslag mot Brønnøysundregistrene."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..constants import BRREG_URL_TMPL, ENHETSREGISTER_URL_TMPL

try:  # pragma: no cover - selve importen testes indirekte
    import requests_cache  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - miljø uten requests-cache
    requests_cache = None  # type: ignore[assignment]
    _REQUESTS_CACHE_AVAILABLE = False
else:
    _REQUESTS_CACHE_AVAILABLE = True

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 timer
_CACHE_PATH = Path(__file__).resolve().parent / "brreg_http_cache"


JSONMapping = Dict[str, Any]


@dataclass
class BrregServiceResult:
    """Resultat fra et HTTP-oppslag mot Brønnøysundregistrene."""

    data: Optional[JSONMapping]
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


_SESSION: Optional[requests.Session] = None
_NETWORK_ERROR_CODES = {
    "timeout",
    "connection_error",
    "rate_limited",
    "server_error",
    "http_error",
    "request_error",
}
_FALLBACK_CACHE: Dict[str, Tuple[float, "BrregServiceResult"]] = {}
_FALLBACK_WARNING_EMITTED = False


def _normalize_orgnr(orgnr: str) -> str:
    digits = "".join(ch for ch in str(orgnr) if ch.isdigit())
    if len(digits) != 9:
        raise ValueError("Organisasjonsnummer må bestå av 9 sifre.")
    return digits


def _ensure_cache_dir() -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _get_session() -> requests.Session:
    global _SESSION, _FALLBACK_WARNING_EMITTED
    if _SESSION is None:
        if _REQUESTS_CACHE_AVAILABLE and requests_cache is not None:
            _ensure_cache_dir()
            session = requests_cache.CachedSession(
                cache_name=str(_CACHE_PATH),
                backend="sqlite",
                expire_after=_CACHE_TTL_SECONDS,
            )
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                status=3,
                backoff_factor=1.0,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET",),
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _SESSION = session
        else:
            _SESSION = requests.Session()
            if not _FALLBACK_WARNING_EMITTED:
                _LOGGER.warning(
                    "requests-cache er ikke installert. Nordlys kjører videre uten "
                    "HTTP-cache, men vi anbefaler å installere pakken for bedre ytelse."
                )
                _FALLBACK_WARNING_EMITTED = True
    assert _SESSION is not None
    return _SESSION


def _make_cache_key(url: str, allow_list: bool) -> str:
    return f"{url}::allow_list={allow_list}"


def _fallback_cache_get(cache_key: str) -> Optional[BrregServiceResult]:
    entry = _FALLBACK_CACHE.get(cache_key)
    if not entry:
        return None
    timestamp, result = entry
    if time.monotonic() - timestamp > _CACHE_TTL_SECONDS:
        _FALLBACK_CACHE.pop(cache_key, None)
        return None
    return replace(result, from_cache=True)


def _should_cache_result(result: BrregServiceResult) -> bool:
    if result.error_code is None:
        return True
    if result.error_code in _NETWORK_ERROR_CODES:
        return False
    return True


def _fallback_cache_set(cache_key: str, result: BrregServiceResult) -> None:
    if not _should_cache_result(result):
        return
    _FALLBACK_CACHE[cache_key] = (time.monotonic(), replace(result, from_cache=False))


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
    allow_list: bool = False,
) -> BrregServiceResult:
    cache_key = _make_cache_key(url, allow_list)
    if not _REQUESTS_CACHE_AVAILABLE:
        cached_result = _fallback_cache_get(cache_key)
        if cached_result is not None:
            return cached_result

    session = _get_session()
    try:
        response = session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=_DEFAULT_TIMEOUT,
        )
    except requests.Timeout:
        return BrregServiceResult(None, "timeout", f"{source_label}: tidsavbrudd.", False)
    except requests.ConnectionError as exc:
        return BrregServiceResult(
            None,
            "connection_error",
            f"{source_label}: tilkoblingsfeil ({exc}).",
            False,
        )
    except requests.RequestException as exc:
        return BrregServiceResult(
            None,
            "request_error",
            f"{source_label}: uventet feil ({exc}).",
            False,
        )

    from_cache = bool(getattr(response, "from_cache", False))

    if response.status_code == 404:
        result = BrregServiceResult(
            None,
            "not_found",
            f"{source_label}: ingen treff for organisasjonsnummeret.",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result
    if response.status_code == 429:
        result = BrregServiceResult(
            None,
            "rate_limited",
            f"{source_label}: for mange forespørsler (429).",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result
    if response.status_code >= 500:
        result = BrregServiceResult(
            None,
            "server_error",
            f"{source_label}: tjenesten svarte med {response.status_code}.",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result
    try:
        response.raise_for_status()
    except requests.HTTPError:
        result = BrregServiceResult(
            None,
            "http_error",
            f"{source_label}: tjenesten svarte med {response.status_code}.",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result

    try:
        payload = response.json()
    except ValueError as exc:
        result = BrregServiceResult(
            None,
            "invalid_json",
            f"{source_label}: ugyldig JSON ({exc}).",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result

    if allow_list and isinstance(payload, list):
        for element in payload:
            if isinstance(element, dict):
                result = BrregServiceResult(element, None, None, from_cache)
                if not _REQUESTS_CACHE_AVAILABLE:
                    _fallback_cache_set(cache_key, result)
                return result
        result = BrregServiceResult(
            None,
            "invalid_json",
            f"{source_label}: uventet svarformat (liste).",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result

    if not isinstance(payload, dict):
        result = BrregServiceResult(
            None,
            "invalid_json",
            f"{source_label}: uventet svarformat.",
            from_cache,
        )
        if not _REQUESTS_CACHE_AVAILABLE:
            _fallback_cache_set(cache_key, result)
        return result

    result = BrregServiceResult(payload, None, None, from_cache)
    if not _REQUESTS_CACHE_AVAILABLE:
        _fallback_cache_set(cache_key, result)
    return result


def fetch_regnskapsregister(orgnr: str) -> BrregServiceResult:
    """Henter data fra Regnskapsregisteret for et organisasjonsnummer."""

    normalized = _normalize_orgnr(orgnr)
    url = BRREG_URL_TMPL.format(orgnr=normalized)
    return _fetch_json(url, "Regnskapsregisteret")


def fetch_enhetsregister(orgnr: str) -> BrregServiceResult:
    """Henter enhetsdata for et organisasjonsnummer."""

    normalized = _normalize_orgnr(orgnr)
    url = ENHETSREGISTER_URL_TMPL.format(orgnr=normalized)
    return _fetch_json(url, "Enhetsregisteret", allow_list=True)


def get_company_status(orgnr: str) -> CompanyStatus:
    """Returnerer statusfelt for et selskap basert på Enhetsregisteret."""

    normalized = _normalize_orgnr(orgnr)
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
        _LOGGER.error(
            "Brreg-status: %s (orgnr=%s)",
            message,
            normalized,
        )
        return CompanyStatus(normalized, None, None, None, None)

    data = result.data or {}
    konkurs = _interpret_bool(data.get("konkurs"))
    under_avvikling = _interpret_bool(data.get("underAvvikling"))
    under_tvangsopplosning = _interpret_bool(
        data.get("underTvangsavviklingEllerTvangsopplosning")
    )
    avvik_candidates = [
        value for value in (under_avvikling, under_tvangsopplosning) if value is not None
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


__all__ = [
    "BrregServiceResult",
    "CompanyStatus",
    "fetch_enhetsregister",
    "fetch_regnskapsregister",
    "get_company_status",
]
