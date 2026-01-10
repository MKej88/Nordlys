from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
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

        self.liquidity_card = CardFrame(
            "Likviditet",
            "Sammendrag basert på beregninger fra nøkkeltallene.",
        )
        self.liquidity_label = QLabel("Likviditet kan ikke vurderes uten data.")
        self.liquidity_label.setObjectName("statusLabel")
        self.liquidity_label.setWordWrap(True)
        self.liquidity_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.liquidity_card.add_widget(self.liquidity_label)
        grid.addWidget(self.liquidity_card, 0, 1)

        self.soliditet_card = CardFrame(
            "Soliditet",
            "Vurderer egenkapitalandel basert på regnskapssammendraget.",
        )
        self.soliditet_label = QLabel("Egenkapitalandel er ikke beregnet ennå.")
        self.soliditet_label.setObjectName("statusLabel")
        self.soliditet_label.setWordWrap(True)
        self.soliditet_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.soliditet_card.add_widget(self.soliditet_label)
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

        self.voucher_card = CardFrame("Antall bilag")
        self.voucher_label = QLabel("Ingen bilag er importert ennå.")
        self.voucher_label.setObjectName("statusLabel")
        self.voucher_label.setWordWrap(True)
        self.voucher_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.voucher_card.add_widget(self.voucher_label)
        grid.addWidget(self.voucher_card, 1, 1)

        self.summary_card = CardFrame(
            "Fokus for revisjonen",
            "Oppsummerte nøkkeltall fra SAF-T som peker ut fokusområder.",
        )
        self.summary_empty_state = EmptyStateWidget(
            "Ingen nøkkeltall å vise ennå",
            "Importer en SAF-T-fil for å se oppsummerte hovedtall her.",
            icon="📊",
        )
        self.summary_empty_state.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self.summary_table = create_table_widget()
        self.summary_table.setColumnCount(2)
        self.summary_table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        self.summary_table.hide()
        self.summary_card.add_widget(self.summary_empty_state)
        self.summary_card.add_widget(self.summary_table)
        grid.addWidget(self.summary_card, 1, 2)

        layout.addStretch(1)

    def update_summary(
        self, summary: Optional[Dict[str, float]], voucher_count: Optional[int] = None
    ) -> None:
        if not summary:
            self.summary_table.setRowCount(0)
            self.summary_table.hide()
            self.summary_empty_state.show()
            self._update_kpis(None)
            self._update_liquidity(None)
            self._update_soliditet(None)
            self._update_voucher_count(voucher_count)
            return
        self.summary_empty_state.hide()
        self.summary_table.show()
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
        populate_table(self.summary_table, ["Nøkkel", "Beløp"], rows, money_cols={1})
        self._update_kpis(summary)
        self._update_liquidity(summary)
        self._update_soliditet(summary)
        self._update_voucher_count(voucher_count)

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

    def _update_liquidity(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.liquidity_label.setText(
                self._summary_html(
                    "Likviditet", "Importer en SAF-T-fil for å vurdere kontantstrøm."
                )
            )
            return

        assets = self._get_numeric(summary, "eiendeler_UB")
        debt = self._get_numeric(summary, "gjeld_UB")
        if assets is not None and debt is not None and abs(debt) > 1e-6:
            liquidity_ratio = assets / debt
            liquidity_text = (
                f"Likviditetsindikator (eiendeler/gjeld) på {liquidity_ratio:.1f} "
                "tyder på at eiendelene dekker kortsiktige forpliktelser."
            )
        else:
            liquidity_text = (
                "Likviditet kan ikke vurderes uten tall for eiendeler og gjeld."
            )

        self.liquidity_label.setText(
            self._summary_html(
                "Likviditet",
                liquidity_text,
            )
        )

    def _update_soliditet(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.soliditet_label.setText(
                self._summary_html(
                    "Soliditet", "Ingen beregning uten eiendeler og egenkapital."
                )
            )
            return

        assets = self._get_numeric(summary, "eiendeler_UB")
        equity = self._get_numeric(summary, "egenkapital_UB")
        equity_ratio = self._ratio(equity, assets)
        if equity_ratio is None:
            solid_text = "Egenkapitalandel kan ikke beregnes uten eiendeler."
        elif equity_ratio < 25:
            solid_text = f"Lav egenkapitalandel på {self._format_percent(equity_ratio)} må følges opp."
        else:
            solid_text = f"Egenkapitalandel på {self._format_percent(equity_ratio)} vurderes som betryggende."
        self.soliditet_label.setText(self._summary_html("Soliditet", solid_text))

    def _update_voucher_count(self, voucher_count: Optional[int]) -> None:
        if voucher_count is None:
            self.voucher_label.setText("Importer SAF-T for å se antall bilag.")
            return
        if voucher_count == 0:
            text = "Ingen bilag ble funnet i datasettet."
        elif voucher_count == 1:
            text = "1 bilag er tilgjengelig i datasettet."
        else:
            text = f"{voucher_count} bilag er tilgjengelige i datasettet."
        self.voucher_label.setText(text)

    def _ratio(
        self, numerator: Optional[float], denominator: Optional[float]
    ) -> Optional[float]:
        if numerator is None or denominator is None or abs(denominator) < 1e-6:
            return None
        return (numerator / denominator) * 100

    def _format_percent(self, value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"{value:.1f} %"

    def _summary_html(self, title: str, body: str) -> str:
        return f"<b>{title}</b><br>{body}"

    def _get_numeric(self, summary: Dict[str, float], key: str) -> Optional[float]:
        value = summary.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
