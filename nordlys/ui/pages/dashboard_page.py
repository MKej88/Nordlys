from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QTableWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...helpers.formatting import format_currency
from ..tables import create_table_widget, populate_table
from ..widgets import CardFrame, EmptyStateWidget, StatBadge

__all__ = ["DashboardPage"]


class DashboardPage(QWidget):
    """Viser nøkkeltall for selskapet."""

    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)

        self.kpi_card = CardFrame(
            "Lønnsomhet",
            "Marginer og balanseindikatorer basert på innlastet SAF-T.",
        )
        self.kpi_grid = QGridLayout()
        self.kpi_grid.setHorizontalSpacing(16)
        self.kpi_grid.setVerticalSpacing(16)
        self.kpi_card.add_layout(self.kpi_grid)

        self.kpi_badges: Dict[str, StatBadge] = {}
        for idx, (key, title, desc) in enumerate(
            [
                ("revenue", "Driftsinntekter", "Sum av kontogruppe 3xxx."),
                (
                    "ebitda_margin",
                    "EBITDA-margin",
                    "EBITDA i prosent av driftsinntekter.",
                ),
                (
                    "ebit_margin",
                    "EBIT-margin",
                    "Driftsresultat i prosent av driftsinntekter.",
                ),
                (
                    "result_margin",
                    "Resultatmargin",
                    "Årsresultat i prosent av driftsinntekter.",
                ),
            ]
        ):
            badge = StatBadge(title, desc)
            row = idx // 3
            col = idx % 3
            self.kpi_grid.addWidget(badge, row, col)
            self.kpi_badges[key] = badge

        grid.addWidget(self.kpi_card, 0, 0)

        (
            self.liquidity_card,
            self.liquidity_empty_state,
            self.liquidity_table,
        ) = self._create_metrics_card(
            "Likviditet",
            "Kontantstrøm- og arbeidskapitalindikatorer basert på SAF-T.",
            "Ingen nøkkeltall å vise ennå",
            "Importer en SAF-T-fil for å se nøkkeltall for likviditet.",
            icon="💧",
        )
        grid.addWidget(self.liquidity_card, 0, 1)

        (
            self.soliditet_card,
            self.soliditet_empty_state,
            self.soliditet_table,
        ) = self._create_metrics_card(
            "Soliditet",
            "Viser egenkapitalandel og gearing basert på SAF-T.",
            "Ingen nøkkeltall å vise ennå",
            "Importer en SAF-T-fil for å se nøkkeltall for soliditet.",
            icon="🏦",
        )
        grid.addWidget(self.soliditet_card, 0, 2)

        self.bransje_card = CardFrame(
            "Bransjespesifikk",
            "Tilpassede perspektiver basert på bransjeidentifisering.",
        )
        self.bransje_label = QLabel(
            "Importer en SAF-T-fil for å se bransjespesifikke nøkkeltall."
        )
        self.bransje_label.setObjectName("statusLabel")
        self.bransje_label.setWordWrap(True)
        self.bransje_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.bransje_card.add_widget(self.bransje_label)
        grid.addWidget(self.bransje_card, 1, 0)

        self.trend_card = CardFrame(
            "Antall bilag",
            "Tilgjengelige inngående fakturaer for stikkprøver.",
        )
        self.trend_label = QLabel("Importer en SAF-T-fil for å se antall bilag.")
        self.trend_label.setObjectName("statusLabel")
        self.trend_label.setWordWrap(True)
        self.trend_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.trend_card.add_widget(self.trend_label)
        grid.addWidget(self.trend_card, 1, 1)

        (
            self.summary_card,
            self.summary_empty_state,
            self.summary_table,
        ) = self._create_metrics_card(
            "Fokus for revisjonen",
            "Oppsummerte nøkkeltall fra SAF-T som peker ut fokusområder.",
            "Ingen nøkkeltall å vise ennå",
            "Importer en SAF-T-fil for å se oppsummerte hovedtall her.",
            icon="📊",
        )
        grid.addWidget(self.summary_card, 1, 2)

        self._metric_sections = (
            (self.summary_table, self.summary_empty_state),
            (self.liquidity_table, self.liquidity_empty_state),
            (self.soliditet_table, self.soliditet_empty_state),
        )

        layout.addStretch(1)

    def update_summary(
        self, summary: Optional[Dict[str, float]], voucher_count: Optional[int] = None
    ) -> None:
        self._update_voucher_count(voucher_count)
        if not summary:
            for table, empty_state in self._metric_sections:
                table.setRowCount(0)
                table.hide()
                empty_state.show()
            self._update_kpis(None)
            return
        for table, empty_state in self._metric_sections:
            empty_state.hide()
            table.show()
        rows = [
            ("Driftsinntekter (3xxx)", summary.get("driftsinntekter")),
            ("Varekostnad (4xxx)", summary.get("varekostnad")),
            ("Lønn (5xxx)", summary.get("lonn")),
            ("Andre driftskostnader", summary.get("andre_drift")),
            ("EBITDA", summary.get("ebitda")),
            ("Avskrivninger", summary.get("avskrivninger")),
            ("EBIT", summary.get("ebit")),
            ("Netto finans", summary.get("finans_netto")),
            ("Skatt", summary.get("skattekostnad")),
            ("Årsresultat", summary.get("arsresultat")),
            ("Eiendeler (UB)", summary.get("eiendeler_UB")),
            ("Gjeld (UB)", summary.get("gjeld_UB")),
        ]
        for table, _ in self._metric_sections:
            populate_table(table, ["Nøkkel", "Beløp"], rows, money_cols={1})
        self._update_kpis(summary)

    def _create_metrics_card(
        self,
        title: str,
        subtitle: str,
        empty_title: str,
        empty_description: str,
        *,
        icon: str,
    ) -> tuple[CardFrame, EmptyStateWidget, QTableWidget]:
        card = CardFrame(title, subtitle)
        empty_state = EmptyStateWidget(empty_title, empty_description, icon=icon)
        empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table = create_table_widget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        table.hide()
        card.add_widget(empty_state)
        card.add_widget(table)
        return card, empty_state, table

    def _update_kpis(self, summary: Optional[Dict[str, float]]) -> None:
        def set_badge(key: str, value: Optional[str]) -> None:
            badge = self.kpi_badges.get(key)
            if badge:
                badge.set_value(value or "—")

        if not summary:
            for key in self.kpi_badges:
                set_badge(key, None)
            return

        revenue_value = summary.get("driftsinntekter")
        revenue = revenue_value or 0.0
        ebitda = summary.get("ebitda")
        ebit = summary.get("ebit")
        result = summary.get("arsresultat")

        set_badge(
            "revenue",
            format_currency(revenue_value) if revenue_value is not None else "—",
        )

        def percent(value: Optional[float]) -> Optional[str]:
            if value is None or not revenue:
                return None
            try:
                return f"{(value / revenue) * 100:,.1f} %"
            except ZeroDivisionError:
                return None

        set_badge("ebitda_margin", percent(ebitda))
        set_badge("ebit_margin", percent(ebit))
        set_badge("result_margin", percent(result))

    def _update_voucher_count(self, count: Optional[int]) -> None:
        if count is None:
            message = "Importer en SAF-T-fil for å se antall bilag."
        elif count == 0:
            message = "Ingen inngående fakturaer tilgjengelig i dette datasettet."
        elif count == 1:
            message = "1 inngående faktura klar for kontroll."
        else:
            message = f"{count} inngående fakturaer klare for kontroll."
        self.trend_label.setText(message)
