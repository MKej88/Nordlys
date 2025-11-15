"""Forberedelse og summering av regnskapsdata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, TYPE_CHECKING

from ..helpers.lazy_imports import lazy_pandas

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

pd = lazy_pandas()


def prepare_regnskap_dataframe(df: "pd.DataFrame") -> "pd.DataFrame":
    """Normaliserer saldobalansen til kolonner brukt i analysen."""

    work = df.copy()

    required_defaults: dict[str, object] = {
        "Konto": "",
        "Kontonavn": "",
        "IB Debet": 0.0,
        "IB Kredit": 0.0,
        "UB Debet": 0.0,
        "UB Kredit": 0.0,
    }

    for column, default in required_defaults.items():
        if column not in work.columns:
            work[column] = default

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

    source: "pd.Series"
    numeric: "pd.Series"


class _PrefixSumHelper:
    """Håndterer caching av summeringer for kontoprefikser."""

    __slots__ = ("_konto_text", "_column_cache", "_index", "_zero_series")

    def __init__(self, konto_text: "pd.Series") -> None:
        self._konto_text = konto_text
        self._column_cache: dict[str, _CachedColumn] = {}
        self._index = konto_text.index
        self._zero_series: Optional["pd.Series"] = None

    def is_compatible(self, prepared: "pd.DataFrame") -> bool:
        return prepared.index.equals(self._index)

    def zero_series(self) -> "pd.Series":
        if self._zero_series is None or not self._zero_series.index.equals(self._index):
            self._zero_series = pd.Series(0.0, index=self._index, dtype=float)
        return self._zero_series

    def sum(
        self,
        column: str,
        prefixes: Iterable[str],
        value_provider: Callable[[str], "pd.Series"],
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


def sum_column_by_prefix(
    prepared: "pd.DataFrame", column: str, prefixes: Iterable[str]
) -> float:
    """Summerer verdier i en kolonne basert på kontonummer-prefikser."""

    helper = prepared.attrs.get("_prefix_sum_helper")
    if not isinstance(helper, _PrefixSumHelper) or not helper.is_compatible(prepared):
        konto_series = prepared.get("konto", pd.Series("", index=prepared.index))
        helper = _PrefixSumHelper(konto_series.astype(str).str.strip())
        prepared.attrs["_prefix_sum_helper"] = helper

    def _provider(col: str) -> "pd.Series":
        if col in prepared.columns:
            return prepared[col]
        return helper.zero_series()

    return helper.sum(column, prefixes, _provider)


__all__ = ["prepare_regnskap_dataframe", "sum_column_by_prefix"]
