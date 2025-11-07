"""Beregninger for regnskapsanalysesiden."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_UP

import pandas as pd


@dataclass(frozen=True)
class AnalysisRow:
    """Representerer én rad i en aggregert visning."""

    label: str
    current: Optional[float]
    previous: Optional[float]
    change: Optional[float]
    is_header: bool = False


def prepare_regnskap_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliserer saldobalansen til kolonner brukt i analysen."""

    work = df.copy()

    for column in [
        "Konto",
        "Kontonavn",
        "IB Debet",
        "IB Kredit",
        "UB Debet",
        "UB Kredit",
    ]:
        if column not in work.columns:
            work[column] = 0.0

    konto_series = work["Konto"].fillna("").astype(str)
    navn_series = work.get("Kontonavn", "").fillna("")

    ib_netto = work.get("IB_netto")
    if ib_netto is None:
        ib_netto = work["IB Debet"].fillna(0.0) - work["IB Kredit"].fillna(0.0)
    else:
        ib_netto = ib_netto.fillna(0.0)

    ub_netto = work.get("UB_netto")
    if ub_netto is None:
        ub_netto = work["UB Debet"].fillna(0.0) - work["UB Kredit"].fillna(0.0)
    else:
        ub_netto = ub_netto.fillna(0.0)

    endring = ub_netto - ib_netto

    prepared = pd.DataFrame(
        {
            "konto": konto_series,
            "navn": navn_series,
            "IB": ib_netto,
            "endring": endring,
            "UB": ub_netto,
            "forrige": work.get("forrige", ib_netto).fillna(0.0),
        }
    )

    return prepared


@dataclass
class _CachedColumn:
    """Representerer en lagret kolonne sammen med dens numeriske verdier."""

    source: pd.Series
    numeric: pd.Series


class _PrefixSumHelper:
    """Håndterer caching av summeringer for kontoprefikser."""

    __slots__ = ("_konto_text", "_column_cache", "_index")

    def __init__(self, konto_text: pd.Series):
        self._konto_text = konto_text
        self._column_cache: dict[str, _CachedColumn] = {}
        self._index = konto_text.index

    def is_compatible(self, prepared: pd.DataFrame) -> bool:
        return prepared.index.equals(self._index)

    def sum(
        self,
        column: str,
        prefixes: Iterable[str],
        value_provider: Callable[[str], pd.Series],
    ) -> float:
        prefix_tuple = tuple(
            str(prefix).strip()
            for prefix in prefixes
            if prefix is not None and str(prefix).strip() != ""
        )
        if not prefix_tuple:
            return 0.0

        series = value_provider(column)

        cached = self._column_cache.get(column)
        if cached is None or cached.source is not series:
            numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)
            cached = _CachedColumn(source=series, numeric=numeric)
            self._column_cache[column] = cached

        values = cached.numeric
        mask = self._konto_text.str.startswith(prefix_tuple)
        if not mask.any():
            return 0.0
        return float(values.loc[mask].sum())


def _sum_column(prepared: pd.DataFrame, column: str, prefixes: Iterable[str]) -> float:
    helper = prepared.attrs.get("_prefix_sum_helper")
    if not isinstance(helper, _PrefixSumHelper) or not helper.is_compatible(prepared):
        konto_series = prepared.get("konto", pd.Series("", index=prepared.index))
        helper = _PrefixSumHelper(konto_series.astype(str).str.strip())
        prepared.attrs["_prefix_sum_helper"] = helper

    zero_series = pd.Series(0.0, index=prepared.index, dtype=float)

    def _provider(col: str) -> pd.Series:
        if col in prepared.columns:
            return prepared[col]
        return zero_series

    return helper.sum(column, prefixes, _provider)


def _clean_value(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0

    if abs(numeric) < 1e-6:
        return 0.0

    try:
        decimal_value = Decimal(str(numeric))
        rounding_mode = ROUND_UP if decimal_value < 0 else ROUND_HALF_UP
        quantized = decimal_value.quantize(Decimal("1"), rounding=rounding_mode)
    except (InvalidOperation, ValueError):
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
    return AnalysisRow(label=label, current=None, previous=None, change=None, is_header=True)


def compute_balance_analysis(prepared: pd.DataFrame) -> List[AnalysisRow]:
    """Beregner balanseaggregater basert på kontonummer-prefikser."""

    work = prepared

    def sum_ub(*prefixes: str) -> float:
        return _sum_column(work, "UB", prefixes)

    def sum_py(*prefixes: str) -> float:
        return _sum_column(work, "forrige", prefixes)

    assets_rows: List[AnalysisRow] = []
    assets_current_values: List[float] = []
    assets_previous_values: List[float] = []

    assets_rows.append(_make_header("Eiendeler"))

    def _add_asset_row(label: str, current: float, previous: float) -> None:
        assets_current_values.append(current)
        assets_previous_values.append(previous)
        assets_rows.append(_make_row(label, current, previous))

    immaterielle = sum_ub("10")
    immaterielle_py = sum_py("10")
    _add_asset_row("Immaterielle eiendeler", immaterielle, immaterielle_py)

    tomter = sum_ub("11")
    tomter_py = sum_py("11")
    _add_asset_row("Tomter, bygninger og annen fast eiendom", tomter, tomter_py)

    maskiner = sum_ub("12")
    maskiner_py = sum_py("12")
    _add_asset_row("Transportmidler, inventar, maskiner o.l.", maskiner, maskiner_py)

    finans_anlegg = sum_ub("13")
    finans_anlegg_py = sum_py("13")
    _add_asset_row("Finansielle anleggsmidler", finans_anlegg, finans_anlegg_py)

    varelager = sum_ub("14")
    varelager_py = sum_py("14")
    _add_asset_row("Varelager og forskudd til leverandører", varelager, varelager_py)

    kundefordr = sum_ub("1500") + sum_ub("1580")
    kundefordr_py = sum_py("1500") + sum_py("1580")
    _add_asset_row("Kundefordringer", kundefordr, kundefordr_py)

    korts_fordr_total = sum_ub("15")
    korts_fordr_total_py = sum_py("15")
    korts_fordr_ovrige = korts_fordr_total - kundefordr
    korts_fordr_ovrige_py = korts_fordr_total_py - kundefordr_py
    _add_asset_row("Andre kortsiktige fordringer", korts_fordr_ovrige, korts_fordr_ovrige_py)

    mva = sum_ub("16")
    mva_py = sum_py("16")
    _add_asset_row("Merverdiavgift, tilskudd o.l.", mva, mva_py)

    forskudd = sum_ub("17")
    forskudd_py = sum_py("17")
    _add_asset_row(
        "Forskuddsbetalte kostnader og påløpte inntekter", forskudd, forskudd_py
    )

    finans_kortsiktig = sum_ub("18")
    finans_kortsiktig_py = sum_py("18")
    _add_asset_row("Kortsiktige finansinvesteringer", finans_kortsiktig, finans_kortsiktig_py)

    bank = sum_ub("19")
    bank_py = sum_py("19")
    _add_asset_row("Kontanter, bankinnskudd o.l.", bank, bank_py)

    sum_eiendeler = sum(assets_current_values)
    sum_eiendeler_py = sum(assets_previous_values)

    assets_rows.append(_make_row("Sum eiendeler", sum_eiendeler, sum_eiendeler_py))

    ek_rows: List[AnalysisRow] = []
    ek_rows.append(_make_header("Egenkapital og gjeld"))

    egenkapital = -sum_ub("20")
    egenkapital_py = -sum_py("20")
    egenkapital_row = _make_row("Egenkapital", egenkapital, egenkapital_py)
    ek_rows.append(egenkapital_row)

    avsetninger = -sum_ub("21")
    avsetninger_py = -sum_py("21")
    avsetninger_row = _make_row(
        "Avsetninger for forpliktelser", avsetninger, avsetninger_py
    )
    ek_rows.append(avsetninger_row)

    ek_rows.append(_make_header("Langsiktig gjeld"))
    annen_langsiktig = -sum_ub("22")
    annen_langsiktig_py = -sum_py("22")
    annen_langsiktig_row = _make_row(
        "Annen langsiktig gjeld", annen_langsiktig, annen_langsiktig_py
    )
    ek_rows.append(annen_langsiktig_row)

    sum_langsiktig = annen_langsiktig
    sum_langsiktig_py = annen_langsiktig_py
    ek_rows.append(_make_row("Sum langsiktig gjeld", sum_langsiktig, sum_langsiktig_py))

    ek_rows.append(_make_header("Kortsiktig gjeld"))

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
        kortsiktig_sum += current_value
        kortsiktig_sum_py += previous_value
        ek_rows.append(_make_row(label, current_value, previous_value))

    ek_rows.append(_make_row("Sum kortsiktig gjeld", kortsiktig_sum, kortsiktig_sum_py))

    sum_ek_gjeld = (
        egenkapital
        + avsetninger
        + sum_langsiktig
        + kortsiktig_sum
    )
    sum_ek_gjeld_py = (
        egenkapital_py
        + avsetninger_py
        + sum_langsiktig_py
        + kortsiktig_sum_py
    )

    ek_rows.append(_make_row("Sum egenkapital og gjeld", sum_ek_gjeld, sum_ek_gjeld_py))

    control_rows: List[AnalysisRow] = []
    control_rows.append(_make_header("Kontroll"))
    control_rows.append(
        _make_row(
            "Avvik",
            sum_eiendeler - sum_ek_gjeld,
            sum_eiendeler_py - sum_ek_gjeld_py,
        )
    )

    return assets_rows + ek_rows + control_rows


def compute_result_analysis(prepared: pd.DataFrame) -> List[AnalysisRow]:
    """Beregner resultatposter basert på kontonummer-prefikser."""

    work = prepared

    def sum_ub(*prefixes: str) -> float:
        return _sum_column(work, "UB", prefixes)

    def sum_py(*prefixes: str) -> float:
        return _sum_column(work, "forrige", prefixes)

    rows: List[AnalysisRow] = []
    rows.append(_make_header("Resultat"))

    annen_inntekt = -(sum_ub("38") + sum_ub("39"))
    annen_inntekt_py = -(sum_py("38") + sum_py("39"))
    rows.append(_make_row("Annen inntekt", annen_inntekt, annen_inntekt_py))

    sum_salg_total = -sum_ub("3")
    sum_salg_total_py = -sum_py("3")
    salg = sum_salg_total - annen_inntekt
    salg_py = sum_salg_total_py - annen_inntekt_py
    rows.append(_make_row("Salgsinntekter", salg, salg_py))

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
    rows.append(_make_row("Resultat før skatt", resultat_for_skatt, resultat_for_skatt_py))

    return rows


__all__ = [
    "AnalysisRow",
    "prepare_regnskap_dataframe",
    "compute_balance_analysis",
    "compute_result_analysis",
]

