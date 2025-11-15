"""Analysekode som bygger på dataset-lageret."""

from __future__ import annotations

from typing import List, Tuple

from .dataset_store import SaftDatasetStore

__all__ = ["DataUnavailableError", "SaftAnalytics"]



class DataUnavailableError(ValueError):
    """Feil som signaliserer at ønsket data ikke er tilgjengelig."""



class SaftAnalytics:
    """Beregninger for kunder og leverandører basert på lagrede data."""

    def __init__(self, store: SaftDatasetStore) -> None:
        self._store = store

    def top_customers(self, topn: int) -> List[Tuple[str, str, int, float]]:
        sales = self._store.customer_sales
        if sales is None or sales.empty:
            raise DataUnavailableError(
                "Fant ingen inntektslinjer på 3xxx-konti i SAF-T-filen."
            )
        data = sales.sort_values("Omsetning eks mva", ascending=False).head(topn)
        rows: List[Tuple[str, str, int, float]] = []
        for _, row in data.iterrows():
            number = row.get("Kundenr")
            number_text = self._store.normalize_customer_key(number)
            if not number_text and isinstance(number, str):
                number_text = number.strip() or None
            name = row.get("Kundenavn") or self._store.lookup_customer_name(
                number, number
            )
            count_val = row.get("Transaksjoner", 0)
            try:
                count_int = int(count_val)
            except (TypeError, ValueError):
                count_int = 0
            rows.append(
                (
                    number_text or "—",
                    (name or "").strip() or "—",
                    count_int,
                    self._store.safe_float(row.get("Omsetning eks mva")),
                )
            )
        return rows

    def top_suppliers(self, topn: int) -> List[Tuple[str, str, int, float]]:
        purchases = self._store.supplier_purchases
        if purchases is None or purchases.empty:
            raise DataUnavailableError(
                "Fant ingen innkjøpslinjer på kostnadskonti (4xxx–8xxx) i SAF-T-filen."
            )
        data = purchases.sort_values("Innkjøp eks mva", ascending=False).head(topn)
        rows: List[Tuple[str, str, int, float]] = []
        for _, row in data.iterrows():
            number = row.get("Leverandørnr")
            number_text = self._store.normalize_supplier_key(number)
            if not number_text and isinstance(number, str):
                number_text = number.strip() or None
            name = row.get("Leverandørnavn") or self._store.lookup_supplier_name(
                number, number
            )
            count_val = row.get("Transaksjoner", 0)
            try:
                count_int = int(count_val)
            except (TypeError, ValueError):
                count_int = 0
            rows.append(
                (
                    number_text or "—",
                    (name or "").strip() or "—",
                    count_int,
                    self._store.safe_float(row.get("Innkjøp eks mva")),
                )
            )
        return rows
