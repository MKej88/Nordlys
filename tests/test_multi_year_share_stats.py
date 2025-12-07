"""Tester for beregning av variasjon i flerårsvisningen."""

from nordlys.ui.multi_year_stats import (
    deviation_assessment,
    normal_variation_text,
    standard_deviation,
)


def test_standard_deviation_ignores_none_values() -> None:
    values = [10.0, None, 12.0, 14.0]

    result = standard_deviation(values)

    assert result is not None
    assert round(result, 3) == 1.633


def test_normal_variation_text_formats_range() -> None:
    text = normal_variation_text(40.0, 5.2)

    assert text == "34,8 %–45,2 %"


def test_deviation_assessment_categories() -> None:
    normal = deviation_assessment(105.0, 100.0, 10.0)
    moderate = deviation_assessment(120.0, 100.0, 10.0)
    unusual = deviation_assessment(130.0, 100.0, 10.0)

    assert normal.startswith("Helt normal variasjon")
    assert moderate == "Moderat avvik – vurderes sammen med øvrig informasjon."
    assert unusual.startswith("Uvanlig avvik")
