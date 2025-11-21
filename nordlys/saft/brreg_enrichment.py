"""Innhenting av Brønnøysund-data og bransjeklassifisering."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from ..brreg import fetch_brreg, map_brreg_metrics
from ..industry_groups import (
    IndustryClassification,
    classify_from_brreg_json,
    classify_from_orgnr,
    load_cached_brreg,
)

if TYPE_CHECKING:
    from ..saft import SaftHeader


@dataclass
class BrregEnrichment:
    """Samler resultatene fra Brønnøysund-oppslag."""

    brreg_json: Optional[Dict[str, object]]
    brreg_map: Optional[Dict[str, Optional[float]]]
    brreg_error: Optional[str]
    industry: Optional[IndustryClassification]
    industry_error: Optional[str]


_ENRICHMENT_CACHE: Dict[str, BrregEnrichment] = {}
_CACHE_LOCK = Lock()


def _clear_enrichment_cache() -> None:
    """Tømmer cache. Eksponert for tester."""

    with _CACHE_LOCK:
        _ENRICHMENT_CACHE.clear()


def _normalize_orgnr(orgnr: str) -> str:
    digits = "".join(ch for ch in orgnr if ch.isdigit())
    if len(digits) != 9:
        raise ValueError("Organisasjonsnummer må bestå av 9 sifre.")
    return digits


def enrich_from_header(header: Optional["SaftHeader"]) -> BrregEnrichment:
    """Hent data fra Brønnøysundregistrene og gjør bransjeklassifisering."""

    if header is None:
        return BrregEnrichment(None, None, None, None, None)
    if not header.orgnr:
        return BrregEnrichment(
            brreg_json=None,
            brreg_map=None,
            brreg_error="SAF-T mangler organisasjonsnummer.",
            industry=None,
            industry_error="SAF-T mangler organisasjonsnummer.",
        )

    try:
        orgnr = _normalize_orgnr(header.orgnr)
    except ValueError as exc:
        message = str(exc)
        return BrregEnrichment(
            brreg_json=None,
            brreg_map=None,
            brreg_error=message,
            industry=None,
            industry_error=message,
        )

    with _CACHE_LOCK:
        cached = _ENRICHMENT_CACHE.get(orgnr)
    if cached:
        return cached

    with ThreadPoolExecutor(max_workers=2) as executor:
        brreg_future = executor.submit(fetch_brreg, orgnr)
        industry_future = executor.submit(
            classify_from_orgnr, orgnr, header.company_name
        )

        brreg_json, brreg_error = _resolve_brreg_future(brreg_future)
        industry, industry_error = _resolve_industry_future(
            industry_future, orgnr, header.company_name
        )

    brreg_map = map_brreg_metrics(brreg_json) if brreg_json else None
    result = BrregEnrichment(
        brreg_json=brreg_json,
        brreg_map=brreg_map,
        brreg_error=brreg_error,
        industry=industry,
        industry_error=industry_error,
    )

    with _CACHE_LOCK:
        _ENRICHMENT_CACHE[orgnr] = result

    return result


def _resolve_brreg_future(future) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    try:
        fetched_json, fetch_error = future.result()
    except Exception as exc:  # pragma: no cover - nettverksfeil vises i GUI
        return None, str(exc)
    if fetch_error:
        return None, fetch_error
    if fetched_json is None:
        return None, "Fikk ikke noe data fra Brønnøysundregistrene."
    return fetched_json, None


def _resolve_industry_future(
    future,
    orgnr: str,
    company_name: Optional[str],
) -> Tuple[Optional[IndustryClassification], Optional[str]]:
    try:
        return future.result(), None
    except Exception as exc:  # pragma: no cover - nettverksfeil vises i GUI
        cached: Optional[Dict[str, object]] = None
        try:
            cached = load_cached_brreg(orgnr)
        except Exception:
            cached = None
        if cached:
            try:
                industry = classify_from_brreg_json(orgnr, company_name, cached)
                return industry, None
            except Exception as cache_exc:  # pragma: no cover - sjelden
                return None, str(cache_exc)
        try:
            fallback = classify_from_brreg_json(orgnr, company_name, {})
        except Exception:
            return None, str(exc)
        return fallback, str(exc)
