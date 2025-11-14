"""Integrasjon mot regnskapsregisteret."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .integrations.brreg_service import fetch_regnskapsregister


def fetch_brreg(orgnr: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    """Henter JSON-data for angitt organisasjonsnummer."""
    result = fetch_regnskapsregister(orgnr)
    return result.data, result.error_message


def find_numbers(data: object, path: str = "") -> List[Tuple[str, float]]:
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

    parts = segment_path.split(".")
    for part in reversed(parts):
        if not part:
            continue
        if "[" in part:
            part = part.split("[", 1)[0]
        part = part.strip()
        if part:
            return part
    return ""


def find_first_by_exact_endkey(
    data: object,
    prefer_keys: Sequence[str],
    disallow_contains: Optional[Iterable[str]] = None,
    numbers: Optional[Sequence[Tuple[str, float]]] = None,
) -> Optional[Tuple[str, float]]:
    """Returnerer første tall der slutt-nøkkelen matcher en av preferansene."""
    disallow_contains = disallow_contains or []
    numbers_list = list(numbers) if numbers is not None else find_numbers(data)
    for key in prefer_keys:
        for path, value in numbers_list:
            last_key = _last_key(path).lower()
            if last_key == key.lower() and not any(
                bad.lower() in path.lower() for bad in disallow_contains
            ):
                return (path, value)
    for key in prefer_keys:
        for path, value in numbers_list:
            if key.lower() in path.lower() and not any(
                bad.lower() in path.lower() for bad in disallow_contains
            ):
                return (path, value)
    return None


def map_brreg_metrics(json_obj: Dict[str, object]) -> Dict[str, Optional[float]]:
    """Mapper regnskapsverdier til kjente nøkkeltall."""
    mapped: Dict[str, Optional[float]] = {}
    numbers = find_numbers(json_obj)
    hit_eiendeler = find_first_by_exact_endkey(
        json_obj, ["sumEiendeler"], numbers=numbers
    )
    if not hit_eiendeler:
        hit_eiendeler = find_first_by_exact_endkey(
            json_obj,
            ["sumEgenkapitalOgGjeld"],
            numbers=numbers,
        )
    mapped["eiendeler_UB"] = hit_eiendeler[1] if hit_eiendeler else None

    hit_ek = find_first_by_exact_endkey(
        json_obj,
        ["sumEgenkapital"],
        disallow_contains=["EgenkapitalOgGjeld", "egenkapitalOgGjeld"],
        numbers=numbers,
    )
    if not hit_ek:
        hit_ek = find_first_by_exact_endkey(
            json_obj, ["sumEgenkapital"], numbers=numbers
        )
    mapped["egenkapital_UB"] = hit_ek[1] if hit_ek else None

    hit_gjeld = find_first_by_exact_endkey(json_obj, ["sumGjeld"], numbers=numbers)
    mapped["gjeld_UB"] = hit_gjeld[1] if hit_gjeld else None

    for key, hints in [
        (
            "driftsinntekter",
            ["driftsinntekter", "sumDriftsinntekter", "salgsinntekter"],
        ),
        ("ebit", ["driftsresultat", "ebit", "driftsresultatFoerFinans"]),
        ("arsresultat", ["arsresultat", "resultat", "resultatEtterSkatt"]),
    ]:
        hit = find_first_by_exact_endkey(json_obj, hints, numbers=numbers)
        mapped[key] = hit[1] if hit else None
    return mapped


__all__ = [
    "fetch_brreg",
    "find_numbers",
    "find_first_by_exact_endkey",
    "map_brreg_metrics",
]
