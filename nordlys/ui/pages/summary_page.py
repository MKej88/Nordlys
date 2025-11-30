"""Vesentlighetsside for Nordlys UI."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QTableWidgetItem, QVBoxLayout, QWidget

from ..tables import create_table_widget, populate_table
from ..widgets import CardFrame

__all__ = ["SummaryPage"]


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.metrics_table = create_table_widget()
        self.metrics_table.setColumnCount(6)
        self.metrics_table.setHorizontalHeaderLabels(
            ["Type", "Beløp", "% fra", "Minimum", "% til", "Maksimum"]
        )

        self.threshold_table = create_table_widget()
        self.threshold_table.setColumnCount(5)
        self.threshold_table.setHorizontalHeaderLabels(
            [
                "Type",
                "Vesentlighet",
                "Arb.ves",
                "Ubetydelig feilinfo",
                "Utført av",
            ]
        )
        self.threshold_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.threshold_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.threshold_table.setAlternatingRowColors(True)
        self._populate_threshold_rows(["Ordinær", "Skatter og avgifter"])

        self.card.add_widget(self.metrics_table)
        self.card.add_widget(self.threshold_table)

        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_summary(self, summary: Optional[Mapping[str, float]]) -> None:
        rows = self._build_metric_rows(summary or {})
        populate_table(
            self.metrics_table,
            ["Type", "Beløp", "% fra", "Minimum", "% til", "Maksimum"],
            rows,
            money_cols={1, 3, 5},
        )

    def _build_metric_rows(
        self, summary: Mapping[str, float]
    ) -> Iterable[
        Tuple[str, Optional[float], str, Optional[float], str, Optional[float]]
    ]:
        metric_settings: Sequence[Tuple[str, float, float, Optional[float]]] = [
            ("Driftsinntekter i år", 0.5, 2.0, self._sum_inntekter(summary)),
            (
                "Bruttofortjeneste",
                1.0,
                1.5,
                self._bruttofortjeneste(summary),
            ),
            (
                "Driftsinntekter i fjor",
                0.5,
                1.5,
                self._get_number(summary, "driftsinntekter_fjor")
                or self._get_number(summary, "sum_inntekter_fjor"),
            ),
            ("Overskudd", 5.0, 10.0, self._get_number(summary, "arsresultat")),
            ("Sum eiendeler", 1.0, 3.0, self._get_number(summary, "eiendeler_UB")),
            ("Egenkapital", 5.0, 10.0, self._get_number(summary, "egenkapital_UB")),
        ]

        for label, min_pct, max_pct, amount in metric_settings:
            minimum = self._percentage_of(amount, min_pct)
            maximum = self._percentage_of(amount, max_pct)
            yield (
                label,
                amount,
                f"{min_pct:.2f} %" if min_pct % 1 else f"{int(min_pct)}.00 %",
                minimum,
                f"{max_pct:.2f} %" if max_pct % 1 else f"{int(max_pct)}.00 %",
                maximum,
            )

    def _populate_threshold_rows(self, labels: Sequence[str]) -> None:
        self.threshold_table.setRowCount(len(labels))
        for row, label in enumerate(labels):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            self.threshold_table.setItem(row, 0, label_item)
            for col in range(1, self.threshold_table.columnCount()):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.threshold_table.setItem(row, col, item)

    def _sum_inntekter(self, summary: Mapping[str, float]) -> Optional[float]:
        return self._get_number(summary, "sum_inntekter") or self._get_number(
            summary, "driftsinntekter"
        )

    def _bruttofortjeneste(self, summary: Mapping[str, float]) -> Optional[float]:
        inntekter = self._sum_inntekter(summary)
        varekostnad = self._get_number(summary, "varekostnad")
        if inntekter is None or varekostnad is None:
            return None
        return inntekter - varekostnad

    def _get_number(self, summary: Mapping[str, float], key: str) -> Optional[float]:
        value = summary.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _percentage_of(
        self, amount: Optional[float], percent: float
    ) -> Optional[float]:
        if amount is None:
            return None
        return amount * percent / 100
