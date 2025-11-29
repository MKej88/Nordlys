"""Sammenstillingsside mellom SAF-T og Brønnøysund."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...helpers.formatting import format_currency, format_difference
from ..tables import apply_compact_row_heights, create_table_widget
from ..widgets import CardFrame

__all__ = ["ComparisonPage"]


class ComparisonPage(QWidget):
    """Sammenstilling mellom SAF-T og Regnskapsregisteret."""

    def __init__(
        self,
        title: str = "Regnskapsanalyse",
        subtitle: str = (
            "Sammenligner SAF-T data med nøkkeltall hentet fra Regnskapsregisteret."
        ),
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.table = create_table_widget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                "Nøkkel",
                "SAF-T",
                "Brreg",
                "Avvik",
            ]
        )
        self.card.add_widget(self.table)
        layout.addWidget(self.card)
        self.suggestion_card = CardFrame(
            "Mulige forklaringer",
            (
                "Viser konti med beløp som er omtrent det samme som avvikene i "
                "kontrollen."
            ),
        )
        self.suggestion_label = QLabel(
            "Ingen forslag enda. Kjør kontrollen for å se mulige forklaringer."
        )
        self.suggestion_label.setWordWrap(True)
        self.suggestion_card.add_widget(self.suggestion_label)
        self.suggestion_card.hide()
        layout.addWidget(self.suggestion_card)
        layout.addStretch(1)

    def update_comparison(
        self,
        rows: Optional[
            Sequence[
                Tuple[
                    str,
                    Optional[float],
                    Optional[float],
                    Optional[float],
                ]
            ]
        ],
    ) -> None:
        if not rows:
            self.table.setRowCount(0)
            return

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(rows))
            headers = ["Nøkkel", "SAF-T", "Brreg", "Avvik"]
            self.table.setHorizontalHeaderLabels(headers)

            status_states = []
            for row_idx, (label, saf_v, brreg_v, _) in enumerate(rows):
                self._set_item(row_idx, 0, label)
                self._set_item(row_idx, 1, format_currency(saf_v), align_center=True)
                self._set_item(row_idx, 2, format_currency(brreg_v), align_center=True)
                status_text, is_ok = self._status_and_flag(saf_v, brreg_v)
                status_states.append(is_ok)
                self._set_item(row_idx, 3, status_text)

            self._apply_status_highlighting(status_states)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.resizeColumnsToContents()
            apply_compact_row_heights(self.table)

    def update_suggestions(self, suggestions: Optional[Sequence[str]]) -> None:
        if not suggestions:
            self.suggestion_label.setText(
                "Ingen forslag enda. Kjør kontrollen for å se mulige forklaringer."
            )
            self.suggestion_card.hide()
            return

        blocks = "".join(f"<div>{text}</div>" for text in suggestions)
        self.suggestion_label.setText(blocks)
        self.suggestion_card.show()

    def _status_and_flag(
        self, saf_value: Optional[float], brreg_value: Optional[float]
    ) -> Tuple[str, Optional[bool]]:
        if saf_value is None or brreg_value is None:
            return "—", None
        try:
            diff = float(saf_value) - float(brreg_value)
        except (TypeError, ValueError):
            return "—", None

        if abs(diff) <= 2:
            return "OK", True

        difference_text = format_difference(saf_value, brreg_value)
        return f"Ikke OK (avvik: {difference_text} kr)", False

    def _set_item(
        self, row: int, column: int, text: str, *, align_center: bool = False
    ) -> None:
        item = QTableWidgetItem(text)
        alignment = Qt.AlignVCenter | (
            Qt.AlignHCenter if align_center else Qt.AlignLeft
        )
        item.setTextAlignment(alignment)
        self.table.setItem(row, column, item)

    def _apply_status_highlighting(self, statuses: Sequence[Optional[bool]]) -> None:
        ok_brush = QBrush(QColor(34, 197, 94, 60))
        default_brush = QBrush()
        for row_idx, is_ok in enumerate(statuses):
            item = self.table.item(row_idx, 3)
            if item is None:
                continue
            if is_ok:
                item.setBackground(ok_brush)
            else:
                item.setBackground(default_brush)
