"""Bransjeklassifisering basert på data fra Brønnøysundregistrene."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

from .integrations.brreg_service import fetch_enhetsregister
from .saft import parse_saft_header
from .saft_customers import parse_saft


@dataclass
class IndustryClassification:
    """Resultat av bransjeklassifisering."""

    orgnr: str
    name: Optional[str]
    naringskode: Optional[str]
    description: Optional[str]
    sn2: Optional[str]
    group: str
    source: str


CACHE_PATH: Path = Path(__file__).resolve().parent / "brreg_cache.json"
_CACHE_LOCK = Lock()


def _normalize_orgnr(orgnr: str) -> str:
    digits = "".join(ch for ch in str(orgnr) if ch.isdigit())
    if len(digits) != 9:
        raise ValueError("Organisasjonsnummer må bestå av 9 sifre.")
    return digits


def _load_cache() -> Dict[str, Dict[str, object]]:
    if not CACHE_PATH.exists():
        return {}
    with _CACHE_LOCK:
        try:
            with CACHE_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}
    if isinstance(data, dict):
        return data  # type: ignore[return-value]
    return {}


def _save_cache(cache: Dict[str, Dict[str, object]]) -> None:
    with _CACHE_LOCK:
        try:
            with CACHE_PATH.open("w", encoding="utf-8") as fh:
                json.dump(cache, fh, ensure_ascii=False, indent=2)
        except OSError:
            # Manglende skrive-tilgang skal ikke stoppe applikasjonen.
            pass


def _extract_sn2(naringskode: Optional[str]) -> Optional[str]:
    if not naringskode:
        return None
    digits = "".join(ch for ch in naringskode if ch.isdigit())
    if len(digits) < 2:
        return None
    return digits[:2]


def _apply_name_overrides(name: str) -> Optional[str]:
    lowered = name.lower()
    if any(token in lowered for token in ("borettslag", "sameiet")):
        return "Borettslag og sameier"
    if any(token in lowered for token in ("holding", "invest")):
        return "Holding og investeringsselskap"
    return None


def _apply_secondary_hints(name: str) -> Optional[str]:
    lowered = name.lower()
    hints = [
        (("eiendom", "property"), "Utleie av eiendom"),
        (
            ("transport", "logist", "spedisjon", "frakt", "taxi", "buss"),
            "Transporttjenester",
        ),
        (
            (
                "restaurant",
                "restaur",
                "bar",
                "pub",
                "cafe",
                "kafé",
                "pizza",
                "pizz",
                "mat og drikke",
            ),
            "Restauranter og uteliv",
        ),
        (("butikk", "handel", "shop", "store"), "Salg av varer (detaljhandel)"),
        (
            (
                "bygg",
                "entrepren",
                "elektro",
                "verksted",
                "mekanisk",
                "betong",
                "trelast",
                "vvs",
                "rør",
                "anlegg",
            ),
            "Salg av varer og tjenester",
        ),
    ]
    for tokens, group in hints:
        if any(token in lowered for token in tokens):
            return group
    return None


def _group_from_sn2(sn2: Optional[str], naringskode: Optional[str]) -> Optional[str]:
    if naringskode and naringskode.strip() == "0":
        return "Holding og investeringsselskap"
    if sn2 is None:
        return None
    if sn2 == "97":
        return "Borettslag og sameier"
    try:
        value = int(sn2)
    except ValueError:
        return None

    ranges = [
        ((1, 3), "Salg av varer (produksjon)"),
        ((5, 32), "Salg av varer (produksjon)"),
        ((33, 33), "Salg av varer og tjenester"),
        ((35, 39), "Salg av varer (produksjon)"),
        ((41, 43), "Salg av varer og tjenester"),
        ((45, 46), "Salg av varer og tjenester"),
        ((47, 47), "Salg av varer (detaljhandel)"),
        ((49, 53), "Transporttjenester"),
        ((56, 56), "Restauranter og uteliv"),
        ((64, 66), "Holding og investeringsselskap"),
        ((68, 68), "Utleie av eiendom"),
        ((55, 55), "Salg av tjenester"),
        ((58, 63), "Salg av tjenester"),
        ((69, 75), "Salg av tjenester"),
        ((77, 82), "Salg av tjenester"),
        ((85, 88), "Salg av tjenester"),
        ((90, 94), "Salg av tjenester"),
        ((95, 95), "Salg av varer og tjenester"),
        ((96, 96), "Salg av tjenester"),
    ]
    for (start, end), group in ranges:
        if start <= value <= end:
            return group
    return None


def classify_from_brreg_json(
    orgnr: str,
    company_name: Optional[str],
    brreg_json: Dict[str, object],
) -> IndustryClassification:
    """Klassifiserer et selskap basert på JSON fra Enhetsregisteret."""

    normalized = _normalize_orgnr(orgnr)
    name = company_name or brreg_json.get("navn")  # type: ignore[arg-type]
    if isinstance(name, list):
        name = " ".join(str(part) for part in name if part)
    elif name is not None:
        name = str(name)

    naringskode = None
    description = None
    nk_data = brreg_json.get("naeringskode1")
    if isinstance(nk_data, dict):
        raw_code = nk_data.get("kode")
        if raw_code is not None:
            naringskode = str(raw_code).strip() or None
        raw_desc = nk_data.get("beskrivelse")
        if raw_desc is not None:
            description = str(raw_desc).strip() or None

    sn2 = _extract_sn2(naringskode)
    name_override = _apply_name_overrides(name or "") if name else None
    group = name_override
    if group is None:
        group = _group_from_sn2(sn2, naringskode)
    if group is None:
        group = _apply_secondary_hints(name or "") or "Salg av tjenester"
    elif group == "Salg av tjenester":
        hint = _apply_secondary_hints(name or "")
        if hint:
            group = hint

    return IndustryClassification(
        orgnr=normalized,
        name=name,
        naringskode=naringskode,
        description=description,
        sn2=sn2,
        group=group,
        source="Brønnøysundregistrene",
    )


def _fetch_enhetsregister(orgnr: str) -> Dict[str, object]:
    """Henter metadata fra Enhetsregisteret."""

    result = fetch_enhetsregister(orgnr)
    if result.data is None:
        message = result.error_message or "Enhetsregisteret: ukjent feil."
        raise RuntimeError(message)
    return result.data


def classify_from_orgnr(
    orgnr: str, company_name: Optional[str] = None
) -> IndustryClassification:
    """Henter data fra Enhetsregisteret (med cache) og klassifiserer selskapet."""

    normalized = _normalize_orgnr(orgnr)
    cache = _load_cache()
    cached_entry = cache.get(normalized)
    brreg_json: Optional[Dict[str, object]] = None
    if isinstance(cached_entry, dict):
        brreg_json = cached_entry
    if brreg_json is None:
        brreg_json = _fetch_enhetsregister(normalized)
        cache[normalized] = brreg_json
        _save_cache(cache)
    return classify_from_brreg_json(normalized, company_name, brreg_json)


def classify_from_saft_path(path: str | Path) -> IndustryClassification:
    """Leser en SAF-T-fil og klassifiserer selskapet automatisk."""

    tree, _ = parse_saft(str(path))
    header = parse_saft_header(tree.getroot())
    if header is None or not header.orgnr:
        raise ValueError("SAF-T-filen mangler organisasjonsnummer.")
    return classify_from_orgnr(header.orgnr, header.company_name)


def load_cached_brreg(orgnr: str) -> Optional[Dict[str, object]]:
    """Returnerer enhetsdata fra cache dersom tilgjengelig."""

    normalized = _normalize_orgnr(orgnr)
    cache = _load_cache()
    entry = cache.get(normalized)
    return entry if isinstance(entry, dict) else None


__all__ = [
    "IndustryClassification",
    "CACHE_PATH",
    "classify_from_orgnr",
    "classify_from_saft_path",
    "classify_from_brreg_json",
    "load_cached_brreg",
]
