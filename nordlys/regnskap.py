"""Beregninger for regnskapsanalysesiden."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

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
    value = float(value)
    return 0.0 if abs(value) < 1e-6 else value


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

    assets_rows.append(_make_header("Eiendeler"))

    immaterielle = sum_ub("10")
    immaterielle_py = sum_py("10")
    assets_rows.append(_make_row("10 Immaterielle", immaterielle, immaterielle_py))

    tomter = sum_ub("11")
    tomter_py = sum_py("11")
    assets_rows.append(_make_row("11 Tomter/bygninger", tomter, tomter_py))

    maskiner = sum_ub("12")
    maskiner_py = sum_py("12")
    assets_rows.append(_make_row("12 Maskiner/inventar/transport", maskiner, maskiner_py))

    finans_anlegg = sum_ub("13")
    finans_anlegg_py = sum_py("13")
    assets_rows.append(_make_row("13 Finansielle anleggsmidler", finans_anlegg, finans_anlegg_py))

    varelager = sum_ub("14")
    varelager_py = sum_py("14")
    assets_rows.append(_make_row("14 Varelager", varelager, varelager_py))

    kundefordr = sum_ub("1500") + sum_ub("1580")
    kundefordr_py = sum_py("1500") + sum_py("1580")
    assets_rows.append(_make_row("Kundefordringer (netto)", kundefordr, kundefordr_py))

    korts_fordr_total = sum_ub("15")
    korts_fordr_total_py = sum_py("15")
    korts_fordr_ovrige = korts_fordr_total - kundefordr
    korts_fordr_ovrige_py = korts_fordr_total_py - kundefordr_py
    assets_rows.append(
        _make_row("Kortsiktige fordringer (øvrige)", korts_fordr_ovrige, korts_fordr_ovrige_py)
    )

    mva = sum_ub("16")
    mva_py = sum_py("16")
    assets_rows.append(_make_row("16 MVA/tilskudd", mva, mva_py))

    forskudd = sum_ub("17")
    forskudd_py = sum_py("17")
    assets_rows.append(
        _make_row("17 Forskuddsbet. kostn./påløpt inntekt", forskudd, forskudd_py)
    )

    finans_kortsiktig = sum_ub("18")
    finans_kortsiktig_py = sum_py("18")
    assets_rows.append(
        _make_row("18 Kortsiktige finansinvesteringer", finans_kortsiktig, finans_kortsiktig_py)
    )

    bank = sum_ub("19")
    bank_py = sum_py("19")
    assets_rows.append(_make_row("19 Bank/kasse", bank, bank_py))

    sum_eiendeler = sum(
        value.current if value.current is not None else 0.0
        for value in assets_rows
        if not value.is_header
    )
    sum_eiendeler_py = sum(
        value.previous if value.previous is not None else 0.0
        for value in assets_rows
        if not value.is_header
    )

    ek_rows: List[AnalysisRow] = []
    ek_rows.append(_make_header("Egenkapital og gjeld"))

    egenkapital = -sum_ub("20")
    egenkapital_py = -sum_py("20")
    ek_rows.append(_make_row("Egenkapital (20)", egenkapital, egenkapital_py))

    avsetninger = -sum_ub("21")
    avsetninger_py = -sum_py("21")
    ek_rows.append(_make_row("21 Avsetninger", avsetninger, avsetninger_py))

    langsiktig = -sum_ub("22")
    langsiktig_py = -sum_py("22")
    ek_rows.append(_make_row("22 Langsiktig gjeld", langsiktig, langsiktig_py))

    kortsiktig = -sum(sum_ub(prefix) for prefix in ["23", "24", "25", "26", "27", "28", "29"])
    kortsiktig_py = -sum(sum_py(prefix) for prefix in ["23", "24", "25", "26", "27", "28", "29"])
    ek_rows.append(_make_row("Kortsiktig gjeld (23–29)", kortsiktig, kortsiktig_py))

    sum_ek_gjeld = egenkapital + avsetninger + langsiktig + kortsiktig
    sum_ek_gjeld_py = egenkapital_py + avsetninger_py + langsiktig_py + kortsiktig_py

    control_rows: List[AnalysisRow] = []
    control_rows.append(_make_header("Kontroll"))
    control_rows.append(_make_row("Sum eiendeler", sum_eiendeler, sum_eiendeler_py))
    control_rows.append(_make_row("Sum EK og gjeld", sum_ek_gjeld, sum_ek_gjeld_py))
    control_rows.append(
        _make_row(
            "Differanse",
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
    rows.append(_make_row("Salgsinntekter (3xxx ekskl. 38/39)", salg, salg_py))

    rows.append(_make_row("Sum inntekter", sum_salg_total, sum_salg_total_py))

    varekostnad = sum_ub("4")
    varekostnad_py = sum_py("4")
    rows.append(_make_row("Varekostnad", varekostnad, varekostnad_py))

    lonn = sum_ub("5")
    lonn_py = sum_py("5")
    rows.append(_make_row("Lønn", lonn, lonn_py))

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

