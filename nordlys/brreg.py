"""Integrasjon mot regnskapsregisteret."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from .constants import BRREG_URL_TMPL


def fetch_brreg(orgnr: str) -> Dict[str, object]:
    """Henter JSON-data for angitt organisasjonsnummer.

    Ved nettverks- eller tjenestefeil returneres en strukturert feilmelding i stedet
    for at unntaket bobler helt ut til brukergrensesnittet.
    """

    url = BRREG_URL_TMPL.format(orgnr=orgnr)
    try:
        response = requests.get(url, headers={'Accept': 'application/json'}, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            'error': {
                'message': (
                    'Klarte ikke å hente data fra Brønnøysundregistrene. '
                    f'Detaljer: {exc}'
                )
            }
        }
    return response.json()


def find_numbers(data: object, path: str = '') -> List[Tuple[str, float]]:
    """Traverserer en struktur og finner tallverdier."""
    found: List[Tuple[str, float]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            found.extend(find_numbers(value, new_path))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            new_path = f"{path}[{idx}]"
            found.extend(find_numbers(value, new_path))
    else:
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            found.append((path, float(data)))
    return found


def _last_key(segment_path: str) -> str:
    """Returnerer siste nøkkelkomponent i en punktseparert sti."""

    parts = segment_path.split('.')
    for part in reversed(parts):
        if not part:
            continue
        if '[' in part:
            part = part.split('[', 1)[0]
        part = part.strip()
        if part:
            return part
    return ''


def _find_first_by_exact_endkey_in_numbers(
    numbers: Sequence[Tuple[str, float]],
    prefer_keys: Sequence[str],
    disallow_contains: Optional[Iterable[str]] = None,
) -> Optional[Tuple[str, float]]:
    """Returnerer første tall fra en forhåndsskannet liste som matcher preferanse."""

    disallow_contains = disallow_contains or []
    for key in prefer_keys:
        for path, value in numbers:
            last_key = _last_key(path).lower()
            if last_key == key.lower() and not any(bad.lower() in path.lower() for bad in disallow_contains):
                return (path, value)
    for key in prefer_keys:
        for path, value in numbers:
            if key.lower() in path.lower() and not any(bad.lower() in path.lower() for bad in disallow_contains):
                return (path, value)
    return None


def find_first_by_exact_endkey(
    data: object,
    prefer_keys: Sequence[str],
    disallow_contains: Optional[Iterable[str]] = None,
) -> Optional[Tuple[str, float]]:
    """Returnerer første tall der slutt-nøkkelen matcher en av preferansene."""

    numbers = find_numbers(data)
    return _find_first_by_exact_endkey_in_numbers(numbers, prefer_keys, disallow_contains)


def map_brreg_metrics(json_obj: Dict[str, object]) -> Dict[str, Optional[float]]:
    """Mapper regnskapsverdier til kjente nøkkeltall."""
    metric_keys = [
        'eiendeler_UB',
        'egenkapital_UB',
        'gjeld_UB',
        'driftsinntekter',
        'ebit',
        'arsresultat',
    ]
    if not isinstance(json_obj, dict) or 'error' in json_obj:
        return {key: None for key in metric_keys}

    numbers = find_numbers(json_obj)
    mapped: Dict[str, Optional[float]] = {}
    hit_eiendeler = _find_first_by_exact_endkey_in_numbers(numbers, ['sumEiendeler'])
    if not hit_eiendeler:
        hit_eiendeler = _find_first_by_exact_endkey_in_numbers(numbers, ['sumEgenkapitalOgGjeld'])
    mapped['eiendeler_UB'] = hit_eiendeler[1] if hit_eiendeler else None

    hit_ek = _find_first_by_exact_endkey_in_numbers(
        numbers,
        ['sumEgenkapital'],
        disallow_contains=['EgenkapitalOgGjeld', 'egenkapitalOgGjeld'],
    )
    if not hit_ek:
        hit_ek = _find_first_by_exact_endkey_in_numbers(numbers, ['sumEgenkapital'])
    mapped['egenkapital_UB'] = hit_ek[1] if hit_ek else None

    hit_gjeld = _find_first_by_exact_endkey_in_numbers(numbers, ['sumGjeld'])
    mapped['gjeld_UB'] = hit_gjeld[1] if hit_gjeld else None

    for key, hints in [
        ('driftsinntekter', ['driftsinntekter', 'sumDriftsinntekter', 'salgsinntekter']),
        ('ebit', ['driftsresultat', 'ebit', 'driftsresultatFoerFinans']),
        ('arsresultat', ['arsresultat', 'resultat', 'resultatEtterSkatt']),
    ]:
        hit = _find_first_by_exact_endkey_in_numbers(numbers, hints)
        mapped[key] = hit[1] if hit else None
    return mapped


__all__ = [
    'fetch_brreg',
    'find_numbers',
    'find_first_by_exact_endkey',
    'map_brreg_metrics',
]
