"""Service-lag for oppslag mot Brønnøysundregistrene."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass, replace
from enum import Enum
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
_CACHE_BASENAME = "brreg_http_cache"
_CACHE_DIR: Optional[Path] = None
_CACHE_DIR_INITIALIZED = False
_MEMORY_CACHE_WARNING_EMITTED = False


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


def _candidate_cache_dirs() -> Tuple[Path, ...]:
    candidates = []
    env_cache_dir = os.environ.get("NORDLYS_CACHE_DIR")
    if env_cache_dir:
        candidates.append(Path(env_cache_dir).expanduser())
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        candidates.append(Path(xdg_cache_home).expanduser() / "nordlys")
    try:
        home_cache = Path.home() / ".cache" / "nordlys"
    except RuntimeError:  # pragma: no cover - Path.home kan feile på enkelte plattformer
        home_cache = None
    else:
        candidates.append(home_cache)
    candidates.append(Path(tempfile.gettempdir()) / "nordlys_cache")
    # Filtrer bort duplikater samtidig som vi bevarer rekkefølgen
    unique_candidates = []
    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(resolved)
    return tuple(unique_candidates)


def _get_cache_path() -> Optional[Path]:
    global _CACHE_DIR_INITIALIZED, _CACHE_DIR
    if not _CACHE_DIR_INITIALIZED:
        for candidate in _candidate_cache_dirs():
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
            if os.access(candidate, os.W_OK):
                _CACHE_DIR = candidate
                break
        _CACHE_DIR_INITIALIZED = True
    if _CACHE_DIR is None:
        return None
    return _CACHE_DIR / _CACHE_BASENAME


def _get_session() -> requests.Session:
    global _SESSION, _FALLBACK_WARNING_EMITTED, _MEMORY_CACHE_WARNING_EMITTED
    if _SESSION is None:
        if _REQUESTS_CACHE_AVAILABLE and requests_cache is not None:
            cache_kwargs: Dict[str, Any] = {
                "backend": "sqlite",
                "expire_after": _CACHE_TTL_SECONDS,
            }
            cache_path = _get_cache_path()
            if cache_path is not None:
                cache_kwargs["cache_name"] = str(cache_path)
            else:
                cache_kwargs["backend"] = "memory"
                if not _MEMORY_CACHE_WARNING_EMITTED:
                    _LOGGER.warning(
                        "Fant ingen skrivbar katalog for Brønnøysund-cache. Bruker minne-cache."
                    )
                    _MEMORY_CACHE_WARNING_EMITTED = True
            try:
                session = requests_cache.CachedSession(**cache_kwargs)
            except OSError:
                _LOGGER.warning(
                    "Kunne ikke initialisere disk-cache for Brønnøysund-oppslag. "
                    "Faller tilbake til minne-cache."
                )
                session = requests_cache.CachedSession(
                    backend="memory", expire_after=_CACHE_TTL_SECONDS
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


class _ListPolicy(str, Enum):
    DISALLOW = "disallow"
    FIRST_DICT = "first_dict"
    PASSTHROUGH = "passthrough"


def _make_cache_key(url: str, list_policy: _ListPolicy) -> str:
    return f"{url}::list_policy={list_policy.value}"


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
    list_policy: _ListPolicy = _ListPolicy.DISALLOW,
) -> BrregServiceResult:
    cache_key = _make_cache_key(url, list_policy)
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

    if isinstance(payload, list):
        if list_policy is _ListPolicy.FIRST_DICT:
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
        if list_policy is _ListPolicy.PASSTHROUGH:
            result = BrregServiceResult(payload, None, None, from_cache)
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
    return _fetch_json(url, "Regnskapsregisteret", list_policy=_ListPolicy.PASSTHROUGH)


def fetch_enhetsregister(orgnr: str) -> BrregServiceResult:
    """Henter enhetsdata for et organisasjonsnummer."""

    normalized = _normalize_orgnr(orgnr)
    url = ENHETSREGISTER_URL_TMPL.format(orgnr=normalized)
    return _fetch_json(url, "Enhetsregisteret", list_policy=_ListPolicy.FIRST_DICT)


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
