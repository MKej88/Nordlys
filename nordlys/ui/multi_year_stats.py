"""Hjelpefunksjoner for statistikk i flerårstabeller."""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

__all__ = [
    "standard_deviation",
    "standard_deviation_without_current",
    "normal_variation_text",
    "deviation_assessment",
    "assessment_level",
]


def _format_percent_with_comma(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def standard_deviation(values: Iterable[Optional[float]]) -> Optional[float]:
    valid = [value for value in values if value is not None]
    if len(valid) < 2:
        return None
    mean = sum(valid) / len(valid)
    variance = sum((value - mean) ** 2 for value in valid) / len(valid)
    return math.sqrt(variance)


def standard_deviation_without_current(
    values: Sequence[Optional[float]],
) -> Optional[float]:
    if len(values) <= 1:
        return None
    return standard_deviation(values[:-1])


def normal_variation_text(average: Optional[float], std_dev: Optional[float]) -> str:
    if average is None or std_dev is None:
        return "—"
    lower = average - std_dev
    upper = average + std_dev
    return (
        f"{_format_percent_with_comma(lower)} %–"
        f"{_format_percent_with_comma(upper)} %"
    )


def deviation_assessment(
    last_value: Optional[float],
    average: Optional[float],
    std_dev: Optional[float],
) -> str:
    if last_value is None or average is None or std_dev is None or abs(std_dev) < 1e-6:
        return "—"

    deviation = abs(last_value - average) / std_dev
    if deviation <= 1:
        return (
            "Helt normal variasjon, som oftest ingen grunn til "
            "særskilt oppfølging alene."
        )
    if deviation <= 2:
        return "Moderat avvik – vurderes sammen med øvrig informasjon."
    return (
        "Uvanlig avvik som normalt bør forklares (endret drift, "
        "klassifisering, feil mv.)."
    )


def assessment_level(text: str) -> Optional[str]:
    if text.startswith("Helt normal"):
        return "normal"
    if text.startswith("Moderat avvik"):
        return "moderate"
    if text.startswith("Uvanlig avvik"):
        return "unusual"
    return None
