"""Vesentlighetsside for Nordlys UI."""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ..tables import create_table_widget, populate_table
from ..widgets import CardFrame, EmptyStateWidget

__all__ = ["SummaryPage"]


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.empty_state = EmptyStateWidget(
            "Ingen nøkkeltall å vise ennå",
            "Importer en SAF-T-fil eller velg et annet datasett for å se "
            "oppsummeringen.",
            icon="📊",
        )
        self.empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.table = create_table_widget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        self.table.hide()
        self.card.add_widget(self.empty_state)
        self.card.add_widget(self.table)

        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.table.setRowCount(0)
            self.table.hide()
            self.empty_state.show()
            return
        rows = [
            ("Relevante beløp", None),
            ("EBIT", summary.get("ebit")),
            ("Årsresultat", summary.get("arsresultat")),
            ("Eiendeler (UB)", summary.get("eiendeler_UB_brreg")),
            ("Gjeld (UB)", summary.get("gjeld_UB_brreg")),
            ("Balanseavvik (Brreg)", summary.get("balanse_diff_brreg")),
        ]
        populate_table(self.table, ["Nøkkel", "Beløp"], rows, money_cols={1})
        self.table.show()
        self.empty_state.hide()
