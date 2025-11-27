"""Håndtering av HTTP-cache og sessions for Brønnøysund-tjenestene."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests  # type: ignore[import-untyped, import-not-found]
from requests.adapters import HTTPAdapter  # type: ignore[import-untyped, import-not-found]
from urllib3.util.retry import Retry

from .brreg_models import BrregServiceResult

try:  # pragma: no cover - selve importen testes indirekte
    import requests_cache  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - miljø uten requests-cache
    requests_cache = None  # type: ignore[assignment]
    REQUESTS_CACHE_AVAILABLE = False
else:
    REQUESTS_CACHE_AVAILABLE = True

__all__ = [
    "REQUESTS_CACHE_AVAILABLE",
    "get_session",
    "fallback_cache_get",
    "fallback_cache_set",
    "make_cache_key",
    "DEFAULT_TIMEOUT",
    "clear_fallback_cache",
    "set_session",
]

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 timer
_CACHE_BASENAME = "brreg_http_cache"
_CACHE_DIR: Optional[Path] = None
_CACHE_DIR_INITIALIZED = False
_MEMORY_CACHE_WARNING_EMITTED = False
_SESSION: Optional[requests.Session] = None
_FALLBACK_CACHE: Dict[str, Tuple[float, BrregServiceResult]] = {}
_FALLBACK_WARNING_EMITTED = False


def _candidate_cache_dirs() -> Tuple[Path, ...]:
    candidates: list[Path] = []
    env_cache_dir = os.environ.get("NORDLYS_CACHE_DIR")
    if env_cache_dir:
        candidates.append(Path(env_cache_dir).expanduser())
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        candidates.append(Path(xdg_cache_home).expanduser() / "nordlys")
    try:
        candidates.append(Path.home() / ".cache" / "nordlys")
    except RuntimeError:
        pass  # pragma: no cover - Path.home kan feile på enkelte plattformer
    candidates.append(Path(tempfile.gettempdir()) / "nordlys_cache")
    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
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


def get_session() -> requests.Session:
    global _SESSION, _FALLBACK_WARNING_EMITTED, _MEMORY_CACHE_WARNING_EMITTED
    if _SESSION is None:
        if REQUESTS_CACHE_AVAILABLE and requests_cache is not None:
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
                    "Kunne ikke initialisere disk-cache for Brønnøysund-oppslag. Faller tilbake til minne-cache."
                )
                session = requests_cache.CachedSession(
                    backend="memory", expire_after=_CACHE_TTL_SECONDS
                )
            adapter = _build_retry_adapter()
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _SESSION = session
        else:
            _SESSION = requests.Session()
            if not _FALLBACK_WARNING_EMITTED:
                _LOGGER.warning(
                    "requests-cache er ikke installert. Nordlys kjører videre uten HTTP-cache, "
                    "men vi anbefaler å installere pakken for bedre ytelse."
                )
                _FALLBACK_WARNING_EMITTED = True
            adapter = _build_retry_adapter()
            _SESSION.mount("https://", adapter)
            _SESSION.mount("http://", adapter)
    assert _SESSION is not None
    return _SESSION


def make_cache_key(url: str, list_policy: str) -> str:
    return f"{url}::list_policy={list_policy}"


def fallback_cache_get(cache_key: str) -> Optional[BrregServiceResult]:
    _prune_fallback_cache()
    entry = _FALLBACK_CACHE.get(cache_key)
    if not entry:
        return None
    _, result = entry
    stored = replace(result, from_cache=True)
    return stored


def _should_cache_result(result: BrregServiceResult) -> bool:
    if result.error_code is None:
        return True
    if result.error_code in {
        "timeout",
        "connection_error",
        "rate_limited",
        "server_error",
        "http_error",
        "request_error",
    }:
        return False
    return True


def fallback_cache_set(cache_key: str, result: BrregServiceResult) -> None:
    _prune_fallback_cache()
    if not _should_cache_result(result):
        return
    _FALLBACK_CACHE[cache_key] = (
        time.monotonic(),
        replace(result, from_cache=False),
    )


def _prune_fallback_cache(now: Optional[float] = None) -> None:
    """Fjerner gamle oppføringer fra fallback-cachen."""

    current_time = time.monotonic() if now is None else now
    expired = [
        key
        for key, (timestamp, _) in _FALLBACK_CACHE.items()
        if current_time - timestamp > _CACHE_TTL_SECONDS
    ]
    for key in expired:
        _FALLBACK_CACHE.pop(key, None)


def clear_fallback_cache() -> None:
    _FALLBACK_CACHE.clear()


def set_session(session: Optional[requests.Session]) -> None:
    global _SESSION
    _SESSION = session


def _build_retry_adapter() -> HTTPAdapter:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    return HTTPAdapter(max_retries=retry)
