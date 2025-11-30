"""Vesentlighetsside for Nordlys UI."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..delegates import CompactRowDelegate
from ..tables import create_table_widget, format_money_norwegian, populate_table
from ..helpers import SignalBlocker
from ..widgets import CardFrame

if TYPE_CHECKING:
    from ...industry_groups import IndustryClassification

__all__ = ["SummaryPage"]


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self._metrics_populating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.industry_label = QLabel("Bransje: —")
        self.industry_label.setObjectName("statusLabel")
        self.industry_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.metrics_table = create_table_widget()
        self.metrics_table.setColumnCount(6)
        self.metrics_table.setHorizontalHeaderLabels(
            ["Type", "Beløp", "% fra", "Minimum", "% til", "Maksimum"]
        )
        self.metrics_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.metrics_table.setItemDelegate(_ReadableItemDelegate(self.metrics_table))

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
        self.threshold_table.setItemDelegate(
            _ReadableItemDelegate(self.threshold_table)
        )
        self._populate_threshold_rows(["Ordinær", "Skatter og avgifter"])

        self.metrics_table.itemChanged.connect(self._on_metrics_item_changed)

        self.card.add_widget(self.industry_label)
        self.card.add_widget(self.metrics_table)
        self.card.add_widget(self.threshold_table)

        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_summary(
        self,
        summary: Optional[Mapping[str, float]],
        *,
        industry: Optional["IndustryClassification"] = None,
        industry_error: Optional[str] = None,
    ) -> None:
        self._update_industry_label(industry, industry_error)
        rows = self._build_metric_rows(summary or {})
        with SignalBlocker(self.metrics_table):
            self._metrics_populating = True
            populate_table(
                self.metrics_table,
                ["Type", "Beløp", "% fra", "Minimum", "% til", "Maksimum"],
                rows,
                money_cols={1, 3, 5},
            )
            self._metrics_populating = False
        self._lock_metric_columns()

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
            (
                "Overskudd",
                5.0,
                10.0,
                self._get_number(summary, "resultat_for_skatt")
                or self._get_number(summary, "arsresultat"),
            ),
            ("Sum eiendeler", 1.0, 3.0, self._get_number(summary, "eiendeler_UB")),
            ("Egenkapital", 5.0, 10.0, self._get_number(summary, "egenkapital_UB")),
        ]

        for label, min_pct, max_pct, amount in metric_settings:
            sanitized = self._sanitize_amount(amount)
            minimum = self._percentage_of(sanitized, min_pct)
            maximum = self._percentage_of(sanitized, max_pct)
            yield (
                label,
                sanitized,
                self._format_percent(min_pct),
                minimum,
                self._format_percent(max_pct),
                maximum,
            )

    def _lock_metric_columns(self) -> None:
        percent_columns = {2, 4}
        row_count = self.metrics_table.rowCount()
        col_count = self.metrics_table.columnCount()
        for row in range(row_count):
            for col in range(col_count):
                item = self.metrics_table.item(row, col)
                if item is None:
                    continue
                if col in percent_columns:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _on_metrics_item_changed(self, item: QTableWidgetItem) -> None:
        if self._metrics_populating or item.column() not in {2, 4}:
            return

        percent = self._parse_percent(item.text())
        if percent is None:
            return

        self._metrics_populating = True
        try:
            item.setText(self._format_percent(percent))
            amount = self._metric_amount(item.row())
            if item.column() == 2:
                target_col = 3
            else:
                target_col = 5
            updated_value = self._percentage_of(amount, percent)
            self._update_money_cell(item.row(), target_col, updated_value)
        finally:
            self._metrics_populating = False

    def _update_industry_label(
        self,
        industry: Optional["IndustryClassification"],
        error: Optional[str],
    ) -> None:
        if error:
            self.industry_label.setText(f"Bransje: ikke tilgjengelig ({error})")
            return
        if industry and industry.group:
            self.industry_label.setText(f"Bransje: {industry.group}")
            return
        if industry:
            self.industry_label.setText("Bransje: Ukjent bransje")
            return
        self.industry_label.setText("Bransje: —")

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

    def _metric_amount(self, row: int) -> Optional[float]:
        amount_item = self.metrics_table.item(row, 1)
        if amount_item is None:
            return None
        data = amount_item.data(Qt.UserRole)
        try:
            return float(data) if data is not None else None
        except (TypeError, ValueError):
            return None

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

    def _sanitize_amount(self, amount: Optional[float]) -> Optional[float]:
        if amount is None:
            return None
        return amount if amount >= 0 else None

    def _format_percent(self, value: float) -> str:
        return f"{value:.2f}%"

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

    def _parse_percent(self, text: str) -> Optional[float]:
        sanitized = (text or "").replace("%", "").replace(" ", "").replace(",", ".")
        if not sanitized:
            return None
        try:
            return float(sanitized)
        except ValueError:
            return None

    def _update_money_cell(self, row: int, column: int, value: Optional[float]) -> None:
        target = self.metrics_table.item(row, column)
        if target is None:
            target = QTableWidgetItem()
            target.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.metrics_table.setItem(row, column, target)
        target.setData(Qt.UserRole, value if value is not None else None)
        display = format_money_norwegian(value) if value is not None else "—"
        target.setText(display)


class _ReadableItemDelegate(CompactRowDelegate):
    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            palette = QPalette()
            palette.setColor(QPalette.Text, QColor("#0f172a"))
            palette.setColor(QPalette.PlaceholderText, QColor("#94a3b8"))
            palette.setColor(QPalette.Base, QColor("#ffffff"))
            palette.setColor(QPalette.Highlight, QColor("#bfdbfe"))
            palette.setColor(QPalette.HighlightedText, QColor("#0f172a"))
            editor.setPalette(palette)
            editor.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        return editor
