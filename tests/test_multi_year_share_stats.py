"""Tester for beregning av variasjon i flerårsvisningen."""

from nordlys.ui.multi_year_stats import (
    assessment_level,
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


def test_assessment_level_mapping() -> None:
    assert (
        assessment_level(
            "Helt normal variasjon, som oftest ingen grunn til særskilt oppfølging alene."
        )
        == "normal"
    )
    assert (
        assessment_level("Moderat avvik – vurderes sammen med øvrig informasjon.")
        == "moderate"
    )
    assert (
        assessment_level(
            "Uvanlig avvik som normalt bør forklares (endret drift, "
            "klassifisering, feil mv.)"
        )
        == "unusual"
    )
    assert assessment_level("Ikke vurdert") is None


def test_deviation_assessment_with_zero_std_dev() -> None:
    unchanged = deviation_assessment(10.0, 10.0, 0.0)
    changed = deviation_assessment(12.0, 10.0, 0.0)

    assert unchanged.startswith("Helt normal variasjon")
    assert changed.startswith("Uvanlig avvik")
