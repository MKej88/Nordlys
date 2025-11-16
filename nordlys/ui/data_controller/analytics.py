"""Håndterer brukerhandlinger som krever analyser."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtWidgets import QMessageBox

from ..data_manager import DataUnavailableError
from .context import ControllerContext


class AnalyticsEventHandler:
    """Kobler knappetrykk til analysene i `SaftAnalytics`."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def on_calc_top_customers(
        self, source: str, topn: int
    ) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source
        try:
            rows = self._context.analytics.top_customers(topn)
        except DataUnavailableError as exc:
            QMessageBox.information(
                self._context.parent, "Ingen inntektslinjer", str(exc)
            )
            return None
        self._context.status_bar.showMessage(f"Topp kunder (3xxx) beregnet. N={topn}.")
        if rows is not None and len(rows) < topn:
            QMessageBox.information(
                self._context.parent,
                "Færre kunder enn ønsket",
                (
                    "Datasettet inneholder færre kunder enn etterspurt. "
                    f"Viser {len(rows)} av {topn}."
                ),
            )
        return rows

    def on_calc_top_suppliers(
        self, source: str, topn: int
    ) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source
        try:
            rows = self._context.analytics.top_suppliers(topn)
        except DataUnavailableError as exc:
            QMessageBox.information(
                self._context.parent, "Ingen innkjøpslinjer", str(exc)
            )
            return None
        self._context.status_bar.showMessage(
            f"Innkjøp per leverandør (kostnadskonti 4xxx–8xxx) beregnet. N={topn}."
        )
        if rows is not None and len(rows) < topn:
            QMessageBox.information(
                self._context.parent,
                "Færre leverandører enn ønsket",
                (
                    "Datasettet inneholder færre leverandører enn etterspurt. "
                    f"Viser {len(rows)} av {topn}."
                ),
            )
        return rows
