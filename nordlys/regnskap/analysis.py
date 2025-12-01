"""Analysefunksjoner for saldobalanse."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional, TYPE_CHECKING, Protocol

from .prep import sum_column_by_prefix

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd


@dataclass(frozen=True)
class AnalysisRow:
    """Representerer én rad i en aggregert visning."""

    label: str
    current: Optional[float]
    previous: Optional[float]
    change: Optional[float]
    is_header: bool = False


class SumFunction(Protocol):
    def __call__(self, *prefixes: str) -> float:
        ...


def _clean_value(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0

    if abs(numeric) < 1e-6:
        return 0.0

    try:
        decimal_value = Decimal(str(numeric))
        quantized = decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return 0.0

    if quantized == 0:
        return 0.0

    return float(quantized)


def _make_row(label: str, current: float, previous: float) -> AnalysisRow:
    current_clean = _clean_value(current)
    previous_clean = _clean_value(previous)
    return AnalysisRow(
        label=label,
        current=current_clean,
        previous=previous_clean,
        change=_clean_value(current_clean - previous_clean),
    )


def _make_header(label: str) -> AnalysisRow:
    return AnalysisRow(
        label=label, current=None, previous=None, change=None, is_header=True
    )


def _value_or_zero(value: Optional[float]) -> float:
    return value if value is not None else 0.0


def _create_sum_functions(prepared: "pd.DataFrame") -> tuple[SumFunction, SumFunction]:
    def sum_ub(*prefixes: str) -> float:
        return sum_column_by_prefix(prepared, "UB", prefixes)

    def sum_py(*prefixes: str) -> float:
        return sum_column_by_prefix(prepared, "forrige", prefixes)

    return sum_ub, sum_py


def _calculate_asset_rows(
    sum_ub: SumFunction, sum_py: SumFunction
) -> tuple[List[AnalysisRow], float, float]:
    rows: List[AnalysisRow] = [_make_header("Eiendeler")]
    current_values: List[float] = []
    previous_values: List[float] = []

    def _add_row(label: str, current: float, previous: float) -> None:
        row = _make_row(label, current, previous)
        current_values.append(_value_or_zero(row.current))
        previous_values.append(_value_or_zero(row.previous))
        rows.append(row)

    immaterielle = sum_ub("10")
    immaterielle_py = sum_py("10")
    _add_row("Immaterielle eiendeler", immaterielle, immaterielle_py)

    tomter = sum_ub("11")
    tomter_py = sum_py("11")
    _add_row("Tomter, bygninger og annen fast eiendom", tomter, tomter_py)

    maskiner = sum_ub("12")
    maskiner_py = sum_py("12")
    _add_row("Transportmidler, inventar, maskiner o.l.", maskiner, maskiner_py)

    finans_anlegg = sum_ub("13")
    finans_anlegg_py = sum_py("13")
    _add_row("Finansielle anleggsmidler", finans_anlegg, finans_anlegg_py)

    varelager = sum_ub("14")
    varelager_py = sum_py("14")
    _add_row("Varelager og forskudd til leverandører", varelager, varelager_py)

    kundefordr = sum_ub("1500") + sum_ub("1580")
    kundefordr_py = sum_py("1500") + sum_py("1580")
    _add_row("Kundefordringer", kundefordr, kundefordr_py)

    korts_fordr_total = sum_ub("15")
    korts_fordr_total_py = sum_py("15")
    korts_fordr_ovrige = korts_fordr_total - kundefordr
    korts_fordr_ovrige_py = korts_fordr_total_py - kundefordr_py
    _add_row(
        "Andre kortsiktige fordringer", korts_fordr_ovrige, korts_fordr_ovrige_py
    )

    mva = sum_ub("16")
    mva_py = sum_py("16")
    _add_row("Merverdiavgift, tilskudd o.l.", mva, mva_py)

    forskudd = sum_ub("17")
    forskudd_py = sum_py("17")
    _add_row(
        "Forskuddsbetalte kostnader og påløpte inntekter", forskudd, forskudd_py
    )

    finans_kortsiktig = sum_ub("18")
    finans_kortsiktig_py = sum_py("18")
    _add_row(
        "Kortsiktige finansinvesteringer", finans_kortsiktig, finans_kortsiktig_py
    )

    bank = sum_ub("19")
    bank_py = sum_py("19")
    _add_row("Kontanter, bankinnskudd o.l.", bank, bank_py)

    sum_eiendeler = sum(current_values)
    sum_eiendeler_py = sum(previous_values)
    rows.append(_make_row("Sum eiendeler", sum_eiendeler, sum_eiendeler_py))

    return rows, sum_eiendeler, sum_eiendeler_py


def _calculate_equity_and_liabilities_rows(
    sum_ub: SumFunction, sum_py: SumFunction
) -> tuple[List[AnalysisRow], float, float]:
    rows: List[AnalysisRow] = [_make_header("Egenkapital og gjeld")]

    egenkapital = -sum_ub("20")
    egenkapital_py = -sum_py("20")
    egenkapital_row = _make_row("Egenkapital", egenkapital, egenkapital_py)
    rows.append(egenkapital_row)
    egenkapital_current = _value_or_zero(egenkapital_row.current)
    egenkapital_previous = _value_or_zero(egenkapital_row.previous)

    rows.append(_make_header("Langsiktig gjeld"))

    avsetninger = -sum_ub("21")
    avsetninger_py = -sum_py("21")
    avsetninger_row = _make_row(
        "Avsetninger for forpliktelser", avsetninger, avsetninger_py
    )
    rows.append(avsetninger_row)
    avsetninger_current = _value_or_zero(avsetninger_row.current)
    avsetninger_previous = _value_or_zero(avsetninger_row.previous)

    annen_langsiktig = -sum_ub("22")
    annen_langsiktig_py = -sum_py("22")
    annen_langsiktig_row = _make_row(
        "Annen langsiktig gjeld", annen_langsiktig, annen_langsiktig_py
    )
    rows.append(annen_langsiktig_row)
    annen_langsiktig_current = _value_or_zero(annen_langsiktig_row.current)
    annen_langsiktig_previous = _value_or_zero(annen_langsiktig_row.previous)

    sum_langsiktig = annen_langsiktig_current + avsetninger_current
    sum_langsiktig_py = annen_langsiktig_previous + avsetninger_previous
    rows.append(_make_row("Sum langsiktig gjeld", sum_langsiktig, sum_langsiktig_py))

    rows.append(_make_header("Kortsiktig gjeld"))

    kortsiktig_kategorier = [
        ("Kassakreditt og annet", "23"),
        ("Leverandørgjeld", "24"),
        ("Betalbar skatt", "25"),
        ("Skattetrekk og andre trekk", "26"),
        ("Skyldige offentlige avgifter", "27"),
        ("Utbytte", "28"),
        ("Annen kortsiktig gjeld", "29"),
    ]

    kortsiktig_sum = 0.0
    kortsiktig_sum_py = 0.0

    for label, prefix in kortsiktig_kategorier:
        current_value = -sum_ub(prefix)
        previous_value = -sum_py(prefix)
        row = _make_row(label, current_value, previous_value)
        kortsiktig_sum += _value_or_zero(row.current)
        kortsiktig_sum_py += _value_or_zero(row.previous)
        rows.append(row)

    rows.append(_make_row("Sum kortsiktig gjeld", kortsiktig_sum, kortsiktig_sum_py))

    sum_ek_gjeld = egenkapital_current + sum_langsiktig + kortsiktig_sum
    sum_ek_gjeld_py = egenkapital_previous + sum_langsiktig_py + kortsiktig_sum_py
    rows.append(_make_row("Sum egenkapital og gjeld", sum_ek_gjeld, sum_ek_gjeld_py))

    return rows, sum_ek_gjeld, sum_ek_gjeld_py


def _build_control_rows(
    sum_eiendeler: float,
    sum_eiendeler_py: float,
    sum_ek_gjeld: float,
    sum_ek_gjeld_py: float,
) -> List[AnalysisRow]:
    return [
        _make_header("Kontroll"),
        _make_row(
            "Avvik",
            sum_eiendeler - sum_ek_gjeld,
            sum_eiendeler_py - sum_ek_gjeld_py,
        ),
    ]


def compute_balance_analysis(prepared: "pd.DataFrame") -> List[AnalysisRow]:
    """Beregner balanseaggregater basert på kontonummer-prefikser."""

    sum_ub, sum_py = _create_sum_functions(prepared)
    assets_rows, sum_eiendeler, sum_eiendeler_py = _calculate_asset_rows(
        sum_ub, sum_py
    )
    ek_rows, sum_ek_gjeld, sum_ek_gjeld_py = _calculate_equity_and_liabilities_rows(
        sum_ub, sum_py
    )
    control_rows = _build_control_rows(
        sum_eiendeler, sum_eiendeler_py, sum_ek_gjeld, sum_ek_gjeld_py
    )

    return assets_rows + ek_rows + control_rows


def compute_result_analysis(prepared: "pd.DataFrame") -> List[AnalysisRow]:
    """Beregner resultatposter basert på kontonummer-prefikser."""

    work = prepared

    def sum_ub(*prefixes: str) -> float:
        return sum_column_by_prefix(work, "UB", prefixes)

    def sum_py(*prefixes: str) -> float:
        return sum_column_by_prefix(work, "forrige", prefixes)

    rows: List[AnalysisRow] = []

    salg = -sum_ub("30", "31", "32", "33", "34", "35", "36", "37")
    salg_py = -sum_py("30", "31", "32", "33", "34", "35", "36", "37")
    annen_inntekt = -(sum_ub("38") + sum_ub("39"))
    annen_inntekt_py = -(sum_py("38") + sum_py("39"))
    sum_salg_total = salg + annen_inntekt
    sum_salg_total_py = salg_py + annen_inntekt_py
    rows.append(_make_row("Salgsinntekter", salg, salg_py))
    rows.append(_make_row("Annen inntekt", annen_inntekt, annen_inntekt_py))

    rows.append(_make_row("Sum inntekter", sum_salg_total, sum_salg_total_py))

    varekostnad = sum_ub("4")
    varekostnad_py = sum_py("4")
    rows.append(_make_row("Varekostnad", varekostnad, varekostnad_py))

    lonn = sum_ub("5")
    lonn_py = sum_py("5")
    rows.append(_make_row("Lønnskostnader", lonn, lonn_py))

    avskr = sum_ub("60")
    avskr_py = sum_py("60")
    rows.append(_make_row("Av-/nedskrivning", avskr, avskr_py))

    andre6_total = sum_ub("6")
    andre6_total_py = sum_py("6")
    andre_drift = andre6_total - avskr
    andre_drift_py = andre6_total_py - avskr_py
    rows.append(_make_row("Andre driftskostnader", andre_drift, andre_drift_py))

    annen_kost = sum_ub("7")
    annen_kost_py = sum_py("7")
    rows.append(_make_row("Annen kostnad", annen_kost, annen_kost_py))

    finansinntekt = -sum_ub("80")
    finansinntekt_py = -sum_py("80")
    rows.append(_make_row("Finansinntekter", finansinntekt, finansinntekt_py))

    finanskost = sum_ub("81")
    finanskost_py = sum_py("81")
    rows.append(_make_row("Finanskostnader", finanskost, finanskost_py))

    resultat_for_skatt = (
        sum_salg_total
        - varekostnad
        - lonn
        - avskr
        - andre_drift
        - annen_kost
        + finansinntekt
        - finanskost
    )
    resultat_for_skatt_py = (
        sum_salg_total_py
        - varekostnad_py
        - lonn_py
        - avskr_py
        - andre_drift_py
        - annen_kost_py
        + finansinntekt_py
        - finanskost_py
    )
    rows.append(
        _make_row("Resultat før skatt", resultat_for_skatt, resultat_for_skatt_py)
    )

    return rows


__all__ = [
    "AnalysisRow",
    "compute_balance_analysis",
    "compute_result_analysis",
]
