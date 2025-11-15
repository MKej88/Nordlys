"""Sammenstillingsside mellom SAF-T og Brønnøysund."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...utils import format_currency, format_difference
from ..tables import create_table_widget, populate_table
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
        layout.addStretch(1)

    def update_comparison(
        self,
        rows: Optional[
            Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ],
    ) -> None:
        if not rows:
            self.table.setRowCount(0)
            return
        formatted_rows = [
            (
                label,
                format_currency(saf_v),
                format_currency(brreg_v),
                format_difference(saf_v, brreg_v),
            )
            for label, saf_v, brreg_v, _ in rows
        ]
        populate_table(
            self.table,
            ["Nøkkel", "SAF-T", "Brreg", "Avvik"],
            formatted_rows,
            money_cols={1, 2, 3},
        )
