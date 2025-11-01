"""PySide6-basert GUI for Nordlys."""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
)

from ..brreg import fetch_brreg, find_first_by_exact_endkey, map_brreg_metrics
from ..constants import APP_TITLE
from ..saft import (
    SaftHeader,
    SaftValidationResult,
    extract_ar_from_gl,
    extract_sales_taxbase_by_customer,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saldobalanse,
    parse_saft_header,
    validate_saft_against_xsd,
)
from ..utils import format_currency, format_difference


REVISION_TASKS: Dict[str, List[str]] = {
    "rev.innkjop": [
        "Avstem leverandørreskontro mot hovedbok",
        "Analysér kredittider og identifiser avvik",
        "Undersøk store engangskjøp",
    ],
    "rev.lonn": [
        "Kontroller lønnsarter og arbeidsgiveravgift",
        "Stem av mot a-meldinger",
        "Bekreft feriepengene",
    ],
    "rev.kostnad": [
        "Kartlegg større kostnadsdrivere",
        "Analyser periodiseringer",
        "Vurder avgrensninger mot investeringer",
    ],
    "rev.driftsmidler": [
        "Bekreft nyanskaffelser",
        "Stem av avskrivninger mot regnskap",
        "Test disposisjoner ved salg/utrangering",
    ],
    "rev.finans": [
        "Avstem bank og lånesaldo",
        "Test renteberegning og covenants",
        "Bekreft finansielle instrumenter",
    ],
    "rev.varelager": [
        "Vurder telling og lagerforskjeller",
        "Test nedskrivninger",
        "Analyser bruttomarginer",
    ],
    "rev.salg": [
        "Analysér omsetning mot kunderegister",
        "Bekreft vesentlige kontrakter",
        "Test cut-off rundt periodeslutt",
    ],
    "rev.mva": [
        "Stem av mva-koder mot innleverte oppgaver",
        "Kontroller mva-grunnlag",
        "Verifiser justeringer og korrigeringer",
    ],
}


def _create_table_widget() -> QTableWidget:
    table = QTableWidget()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setObjectName("cardTable")
    return table


class CardFrame(QFrame):
    """Visuelt kort med tittel og valgfritt innhold."""

    def __init__(self, title: str, subtitle: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(15, 23, 42, 40))
        self.setGraphicsEffect(shadow)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(12)
        layout.addLayout(self.body_layout)

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, sub_layout: QHBoxLayout | QVBoxLayout | QGridLayout) -> None:
        self.body_layout.addLayout(sub_layout)


class StatBadge(QFrame):
    """Kompakt komponent for presentasjon av et nøkkeltall."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        self.setObjectName("statBadge")
        self.setAttribute(Qt.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(15, 23, 42, 30))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        layout.addWidget(self.title_label)

        self.value_label = QLabel("–")
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)

        self.description_label = QLabel(description)
        self.description_label.setObjectName("statDescription")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class DashboardPage(QWidget):
    """Viser nøkkeltall og topp kunder."""

    def __init__(self, on_calc_top: Callable[[str, int], Optional[List[Tuple[str, str, int, float]]]]) -> None:
        super().__init__()
        self._on_calc_top = on_calc_top

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.status_card = CardFrame("Status", "Hurtigoversikt over siste import og anbefalinger.")
        self.status_label = QLabel("Ingen SAF-T fil er lastet inn ennå.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_card.add_widget(self.status_label)

        self.validation_label = QLabel("Ingen XSD-validering er gjennomført.")
        self.validation_label.setObjectName("statusLabel")
        self.validation_label.setWordWrap(True)
        self.status_card.add_widget(self.validation_label)
        layout.addWidget(self.status_card)

        self.kpi_card = CardFrame(
            "Nøkkeltallsanalyse",
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
                ("ebitda_margin", "EBITDA-margin", "EBITDA i prosent av driftsinntekter."),
                ("ebit_margin", "EBIT-margin", "Driftsresultat i prosent av driftsinntekter."),
                ("result_margin", "Resultatmargin", "Årsresultat i prosent av driftsinntekter."),
                ("balance_gap", "Balanseavvik", "Differanse mellom eiendeler og gjeld."),
            ]
        ):
            badge = StatBadge(title, desc)
            row = idx // 3
            col = idx % 3
            self.kpi_grid.addWidget(badge, row, col)
            self.kpi_badges[key] = badge

        layout.addWidget(self.kpi_card)

        self.summary_card = CardFrame("Finansiell oversikt", "Oppsummerte nøkkeltall fra SAF-T.")
        self.summary_table = _create_table_widget()
        self.summary_table.setColumnCount(2)
        self.summary_table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        self.summary_card.add_widget(self.summary_table)
        layout.addWidget(self.summary_card)

        self.top_card = CardFrame("Topp kunder", "Identifiser kunder med høyest omsetning.")
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(QLabel("Kilde:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["faktura", "reskontro"])
        controls.addWidget(self.source_combo)
        controls.addWidget(QLabel("Antall:"))
        self.top_spin = QSpinBox()
        self.top_spin.setRange(5, 100)
        self.top_spin.setValue(10)
        controls.addWidget(self.top_spin)
        controls.addStretch(1)
        self.calc_button = QPushButton("Beregn topp kunder")
        self.calc_button.clicked.connect(self._handle_calc_clicked)
        controls.addWidget(self.calc_button)
        self.top_card.add_layout(controls)

        self.top_table = _create_table_widget()
        self.top_table.setColumnCount(4)
        self.top_table.setHorizontalHeaderLabels([
            "KundeID",
            "Kundenavn",
            "Fakturaer",
            "Omsetning (eks. mva)",
        ])
        self.top_card.add_widget(self.top_table)
        layout.addWidget(self.top_card)
        layout.addStretch(1)

        self.set_controls_enabled(False)

    def _handle_calc_clicked(self) -> None:
        rows = self._on_calc_top(self.source_combo.currentText(), int(self.top_spin.value()))
        if rows:
            self.set_top_customers(rows)

    def update_status(self, message: str) -> None:
        self.status_label.setText(message)

    def update_validation_status(self, result: Optional[SaftValidationResult]) -> None:
        if result is None:
            self.validation_label.setText("Ingen XSD-validering er gjennomført.")
            return

        if result.version_family:
            version_txt = result.version_family
            if result.audit_file_version and result.audit_file_version != result.version_family:
                version_txt = f"{result.version_family} (AuditFileVersion: {result.audit_file_version})"
        else:
            version_txt = result.audit_file_version or "ukjent"

        status_parts = [f"SAF-T versjon: {version_txt}"]
        if result.is_valid is True:
            status_parts.append("XSD-validering: OK")
        elif result.is_valid is False:
            status_parts.append("XSD-validering: FEILET")
        else:
            status_parts.append("XSD-validering: Ikke tilgjengelig")

        message = " · ".join(status_parts)
        if result.details:
            first_line = result.details.strip().splitlines()[0]
            message = f"{message}\nDetaljer: {first_line}"
        self.validation_label.setText(message)

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.summary_table.setRowCount(0)
            self._update_kpis(None)
            return
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
            ("Balanseavvik", summary.get("balanse_diff")),
        ]
        _populate_table(self.summary_table, ["Nøkkel", "Beløp"], rows, money_cols={1})
        self._update_kpis(summary)

    def set_top_customers(self, rows: Iterable[Tuple[str, str, int, float]]) -> None:
        _populate_table(
            self.top_table,
            ["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"],
            rows,
            money_cols={3},
        )

    def clear_top_customers(self) -> None:
        self.top_table.setRowCount(0)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.calc_button.setEnabled(enabled)
        self.top_spin.setEnabled(enabled)
        self.source_combo.setEnabled(enabled)

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

        set_badge("revenue", format_currency(revenue_value) if revenue_value is not None else "—")

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
        set_badge(
            "balance_gap",
            format_difference(summary.get("eiendeler_UB"), summary.get("gjeld_UB")),
        )


class DataFramePage(QWidget):
    """Generisk side som viser en pandas DataFrame."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        frame_builder: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None,
        money_columns: Optional[Sequence[str]] = None,
        header_mode: QHeaderView.ResizeMode = QHeaderView.Stretch,
        full_window: bool = False,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card: Optional[CardFrame] = None
        self.info_label = QLabel("Last inn en SAF-T fil for å vise data.")
        self.info_label.setObjectName("infoLabel")

        self.table = _create_table_widget()
        self.table.horizontalHeader().setSectionResizeMode(header_mode)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.hide()

        if full_window:
            title_label = QLabel(title)
            title_label.setObjectName("pageTitle")
            layout.addWidget(title_label)

            if subtitle:
                subtitle_label = QLabel(subtitle)
                subtitle_label.setObjectName("pageSubtitle")
                subtitle_label.setWordWrap(True)
                layout.addWidget(subtitle_label)

            layout.addWidget(self.info_label)
            layout.addWidget(self.table, 1)
        else:
            self.card = CardFrame(title, subtitle)
            self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.card.add_widget(self.info_label)
            self.card.add_widget(self.table)
            layout.addWidget(self.card)
            layout.addStretch(1)

        self._frame_builder = frame_builder
        self._money_columns = tuple(money_columns or [])
        self._auto_resize_columns = header_mode == QHeaderView.ResizeToContents

    def set_dataframe(self, df: Optional[pd.DataFrame]) -> None:
        if df is None or df.empty:
            self.table.hide()
            self.info_label.show()
            self.table.setRowCount(0)
            return

        work = df
        if self._frame_builder is not None:
            work = self._frame_builder(df)

        columns = list(work.columns)
        rows = [tuple(work.iloc[i][column] for column in columns) for i in range(len(work))]
        money_idx = {columns.index(col) for col in self._money_columns if col in columns}
        _populate_table(self.table, columns, rows, money_cols=money_idx)
        if self._auto_resize_columns:
            self.table.resizeColumnsToContents()
        self.table.show()
        self.info_label.hide()


def _standard_tb_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Bygger en norsk standard saldobalanse med nettoverdier."""

    work = df.copy()
    if "Konto_int" in work.columns:
        work = work.sort_values("Konto_int", na_position="last")
    elif "Konto" in work.columns:
        work = work.sort_values("Konto", na_position="last")

    if "IB_netto" not in work.columns:
        work["IB_netto"] = work.get("IB Debet", 0.0).fillna(0) - work.get("IB Kredit", 0.0).fillna(0)
    if "UB_netto" not in work.columns:
        work["UB_netto"] = work.get("UB Debet", 0.0).fillna(0) - work.get("UB Kredit", 0.0).fillna(0)

    work["Endringer"] = work["UB_netto"] - work["IB_netto"]

    columns = ["Konto", "Kontonavn", "IB", "Endringer", "UB"]
    konto = work["Konto"].fillna("") if "Konto" in work.columns else pd.Series([""] * len(work))
    navn = (
        work["Kontonavn"].fillna("")
        if "Kontonavn" in work.columns
        else pd.Series([""] * len(work))
    )

    result = pd.DataFrame({
        "Konto": konto.astype(str),
        "Kontonavn": navn.astype(str),
        "IB": work["IB_netto"].fillna(0.0),
        "Endringer": work["Endringer"].fillna(0.0),
        "UB": work["UB_netto"].fillna(0.0),
    })
    return result[columns].reset_index(drop=True)


class SummaryPage(QWidget):
    """Side for vesentlighetsvurdering med tabell og forklaring."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.table = _create_table_widget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Nøkkel", "Beløp"])
        self.card.add_widget(self.table)

        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.table.setRowCount(0)
            return
        rows = [
            ("Relevante beløp", None),
            ("EBIT", summary.get("ebit")),
            ("Årsresultat", summary.get("arsresultat")),
            ("Eiendeler (UB)", summary.get("eiendeler_UB_brreg")),
            ("Gjeld (UB)", summary.get("gjeld_UB_brreg")),
            ("Balanseavvik (Brreg)", summary.get("balanse_diff_brreg")),
        ]
        _populate_table(self.table, ["Nøkkel", "Beløp"], rows, money_cols={1})


class ComparisonPage(QWidget):
    """Sammenstilling mellom SAF-T og Regnskapsregisteret."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(
            "Regnskapsanalyse",
            "Sammenligner SAF-T data med nøkkeltall hentet fra Regnskapsregisteret.",
        )
        self.table = _create_table_widget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Nøkkel",
            "SAF-T",
            "Brreg",
            "Avvik",
        ])
        self.card.add_widget(self.table)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def update_comparison(
        self, rows: Optional[Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]]
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
        _populate_table(
            self.table,
            ["Nøkkel", "SAF-T", "Brreg", "Avvik"],
            formatted_rows,
            money_cols={1, 2, 3},
        )


class BrregPage(QWidget):
    """Visning av mapping mot Regnskapsregisteret og rådata."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.map_card = CardFrame("Brreg-nøkler", "Mapping mellom SAF-T og Regnskapsregisteret.")
        self.map_table = _create_table_widget()
        self.map_table.setColumnCount(2)
        self.map_table.setHorizontalHeaderLabels(["Felt", "Sti = Verdi"])
        self.map_card.add_widget(self.map_table)
        layout.addWidget(self.map_card)

        self.json_card = CardFrame("Detaljert JSON", "Rådata fra Regnskapsregisteret for videre analyse.")
        self.json_view = QTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setObjectName("jsonView")
        self.json_card.add_widget(self.json_view)
        layout.addWidget(self.json_card)
        layout.addStretch(1)

    def update_mapping(self, rows: Optional[Sequence[Tuple[str, str]]]) -> None:
        if not rows:
            self.map_table.setRowCount(0)
            return
        _populate_table(self.map_table, ["Felt", "Sti = Verdi"], rows)

    def update_json(self, data: Optional[Dict[str, object]]) -> None:
        if not data:
            self.json_view.clear()
            return
        self.json_view.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))


class ChecklistPage(QWidget):
    """Enkel sjekkliste for revisjonsområder."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("checklist")
        self.card.add_widget(self.list_widget)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def set_items(self, items: Iterable[str]) -> None:
        self.list_widget.clear()
        for item in items:
            QListWidgetItem(item, self.list_widget)


@dataclass
class NavigationItem:
    key: str
    item: QTreeWidgetItem


class NavigationPanel(QFrame):
    """Sidepanel med navigasjonsstruktur."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("navPanel")
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(24)

        self.logo_label = QLabel("Nordlys")
        self.logo_label.setObjectName("logoLabel")
        layout.addWidget(self.logo_label)

        self.subtitle_label = QLabel("Analyse av SAF-T og nøkkeltall")
        self.subtitle_label.setObjectName("navSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(12)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.tree, 1)

    def add_root(self, title: str, key: str | None = None) -> NavigationItem:
        item = QTreeWidgetItem([title])
        if key:
            item.setData(0, Qt.UserRole, key)
        self.tree.addTopLevelItem(item)
        self.tree.expandItem(item)
        return NavigationItem(key or title.lower(), item)

    def add_child(self, parent: NavigationItem, title: str, key: str) -> NavigationItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, key)
        parent.item.addChild(item)
        parent.item.setExpanded(True)
        return NavigationItem(key, item)


class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 940)
        # Sikrer at hovedvinduet kan maksimeres uten Qt-advarsler selv om enkelte
        # underliggende widgets har begrensende størrelseshint.
        self.setMinimumSize(1100, 720)
        self.setMaximumSize(16777215, 16777215)

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional[SaftHeader] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._cust_map: Dict[str, str] = {}
        self._sales_agg: Optional[pd.DataFrame] = None
        self._ar_agg: Optional[pd.DataFrame] = None
        self._validation_result: Optional[SaftValidationResult] = None

        self._page_map: Dict[str, QWidget] = {}

        self._setup_ui()
        self._apply_styles()

    # region UI
    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.nav_panel = NavigationPanel()
        root_layout.addWidget(self.nav_panel, 0)

        content_wrapper = QWidget()
        content_wrapper.setObjectName("contentArea")
        content_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(24)
        root_layout.addWidget(content_wrapper, 1)

        header_bar = QFrame()
        header_bar.setObjectName("headerBar")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(24, 20, 24, 20)
        header_layout.setSpacing(16)

        self.title_label = QLabel("Dashboard")
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label, 1)

        self.btn_open = QPushButton("Åpne SAF-T XML …")
        self.btn_open.clicked.connect(self.on_open)
        header_layout.addWidget(self.btn_open)

        self.btn_brreg = QPushButton("Hent Regnskapsregisteret")
        self.btn_brreg.clicked.connect(self.on_brreg)
        self.btn_brreg.setEnabled(False)
        header_layout.addWidget(self.btn_brreg)

        self.btn_export = QPushButton("Eksporter rapport (Excel)")
        self.btn_export.clicked.connect(self.on_export)
        self.btn_export.setEnabled(False)
        header_layout.addWidget(self.btn_export)

        content_layout.addWidget(header_bar)

        info_card = CardFrame("Selskapsinformasjon")
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(8)

        self.lbl_company = QLabel("Selskap: –")
        self.lbl_orgnr = QLabel("Org.nr: –")
        self.lbl_period = QLabel("Periode: –")
        info_grid.addWidget(self.lbl_company, 0, 0)
        info_grid.addWidget(self.lbl_orgnr, 0, 1)
        info_grid.addWidget(self.lbl_period, 0, 2)
        info_card.add_layout(info_grid)
        content_layout.addWidget(info_card)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self._create_pages()

        status = QStatusBar()
        status.showMessage("Klar.")
        self.setStatusBar(status)

    def _create_pages(self) -> None:
        dashboard = DashboardPage(self._on_calc_top_customers)
        self._register_page("dashboard", dashboard)
        self.stack.addWidget(dashboard)
        self.dashboard_page = dashboard

        saldobalanse_page = DataFramePage(
            "Saldobalanse",
            "Viser saldobalansen slik den er rapportert i SAF-T.",
            frame_builder=_standard_tb_frame,
            money_columns=("IB", "Endringer", "UB"),
            header_mode=QHeaderView.ResizeToContents,
            full_window=True,
        )
        self._register_page("plan.saldobalanse", saldobalanse_page)
        self.stack.addWidget(saldobalanse_page)
        self.saldobalanse_page = saldobalanse_page

        kontroll_page = DataFramePage(
            "Kontroll av inngående balanse",
            "Detaljert saldobalanse fra SAF-T for kvalitetssikring.",
        )
        self._register_page("plan.kontroll", kontroll_page)
        self.stack.addWidget(kontroll_page)
        self.kontroll_page = kontroll_page

        vesentlig_page = SummaryPage(
            "Vesentlighetsvurdering",
            "Nøkkeltall som understøtter fastsettelse av vesentlighetsgrenser.",
        )
        self._register_page("plan.vesentlighet", vesentlig_page)
        self.stack.addWidget(vesentlig_page)
        self.vesentlig_page = vesentlig_page

        regnskap_page = ComparisonPage()
        self._register_page("plan.regnskapsanalyse", regnskap_page)
        self.stack.addWidget(regnskap_page)
        self.regnskap_page = regnskap_page

        brreg_page = BrregPage()
        self._register_page("plan.sammenstilling", brreg_page)
        self.stack.addWidget(brreg_page)
        self.brreg_page = brreg_page

        self.revision_pages: Dict[str, ChecklistPage] = {}
        for key, (title, subtitle) in {
            "rev.innkjop": ("Innkjøp og leverandørgjeld", "Fokuser på varekjøp, kredittider og periodisering."),
            "rev.lonn": ("Lønn", "Kontroll av lønnskjøringer, skatt og arbeidsgiveravgift."),
            "rev.kostnad": ("Kostnad", "Analyse av driftskostnader og periodisering."),
            "rev.driftsmidler": ("Driftsmidler", "Verifikasjon av investeringer og avskrivninger."),
            "rev.finans": ("Finans og likvid", "Bank, finansielle instrumenter og kontantstrøm."),
            "rev.varelager": ("Varelager og varekjøp", "Telling, nedskrivninger og bruttomargin."),
            "rev.salg": ("Salg og kundefordringer", "Omsetning, cut-off og reskontro."),
            "rev.mva": ("MVA", "Kontroll av avgiftsbehandling og rapportering."),
        }.items():
            page = ChecklistPage(title, subtitle)
            self.revision_pages[key] = page
            self._register_page(key, page)
            self.stack.addWidget(page)

        self._populate_navigation()

    def _populate_navigation(self) -> None:
        nav = self.nav_panel
        dashboard_item = nav.add_root("Dashboard", "dashboard")

        planning_root = nav.add_root("Planlegging")
        nav.add_child(planning_root, "Saldobalanse", "plan.saldobalanse")
        nav.add_child(planning_root, "Kontroll IB", "plan.kontroll")
        nav.add_child(planning_root, "Vesentlighetsvurdering", "plan.vesentlighet")
        nav.add_child(planning_root, "Regnskapsanalyse", "plan.regnskapsanalyse")
        nav.add_child(planning_root, "Sammenstillingsanalyse", "plan.sammenstilling")

        revision_root = nav.add_root("Revisjon")
        nav.add_child(revision_root, "Innkjøp og leverandørgjeld", "rev.innkjop")
        nav.add_child(revision_root, "Lønn", "rev.lonn")
        nav.add_child(revision_root, "Kostnad", "rev.kostnad")
        nav.add_child(revision_root, "Driftsmidler", "rev.driftsmidler")
        nav.add_child(revision_root, "Finans og likvid", "rev.finans")
        nav.add_child(revision_root, "Varelager og varekjøp", "rev.varelager")
        nav.add_child(revision_root, "Salg og kundefordringer", "rev.salg")
        nav.add_child(revision_root, "MVA", "rev.mva")

        nav.tree.currentItemChanged.connect(self._on_navigation_changed)
        nav.tree.setCurrentItem(dashboard_item.item)

        for key, items in REVISION_TASKS.items():
            page = self.revision_pages.get(key)
            if page:
                page.set_items(items)

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_map[key] = widget

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-family: 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 13px; color: #0f172a; }
            QMainWindow { background-color: #eef2f9; }
            #contentArea { background-color: #f8fafc; border-top-left-radius: 28px; border-bottom-left-radius: 28px; }
            #headerBar { background-color: #ffffff; border-radius: 20px; border: 1px solid rgba(148, 163, 184, 0.24); }
            #navPanel { background-color: #0f172a; color: #e2e8f0; border-right: 1px solid rgba(148, 163, 184, 0.18); }
            #logoLabel { font-size: 24px; font-weight: 700; letter-spacing: 0.4px; color: #f8fafc; }
            #navSubtitle { color: #94a3b8; font-size: 12px; line-height: 160%; }
            #navTree { background: transparent; border: none; color: #e2e8f0; font-size: 14px; }
            #navTree:focus { outline: none; border: none; }
            QTreeWidget::item:focus { outline: none; }
            #navTree::item { height: 36px; padding: 6px 10px; margin: 2px 4px; border-radius: 10px; }
            #navTree::item:selected { background-color: #2563eb; color: #ffffff; }
            #navTree::item:hover { background-color: rgba(37, 99, 235, 0.32); }
            QTreeWidget::branch { background: transparent; }
            QPushButton { background-color: #2563eb; color: white; border-radius: 10px; padding: 10px 20px; font-weight: 600; letter-spacing: 0.2px; }
            QPushButton:focus { outline: none; }
            QPushButton:disabled { background-color: #9ca3af; color: #e5e7eb; }
            QPushButton:hover:!disabled { background-color: #1d4ed8; }
            QPushButton:pressed { background-color: #1e40af; }
            QComboBox, QSpinBox { background-color: #ffffff; border-radius: 10px; border: 1px solid rgba(148, 163, 184, 0.6); padding: 6px 10px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { border-radius: 10px; background-color: #ffffff; selection-background-color: rgba(37, 99, 235, 0.12); }
            #card { background-color: #ffffff; border-radius: 20px; border: 1px solid rgba(203, 213, 225, 0.7); }
            #cardTitle { font-size: 18px; font-weight: 600; color: #0f172a; }
            #cardSubtitle { color: #64748b; font-size: 12px; line-height: 150%; }
            #pageTitle { font-size: 28px; font-weight: 700; color: #020617; letter-spacing: 0.3px; }
            #statusLabel { color: #1f2937; font-size: 14px; }
            #infoLabel { color: #475569; }
            #jsonView { background-color: #0f172a; color: #f9fafb; font-family: "Fira Code", monospace; border-radius: 16px; padding: 16px; }
            #cardTable { border: none; gridline-color: rgba(148, 163, 184, 0.4); }
            QTableWidget::item { padding: 8px; }
            QTableWidget::item:selected { background-color: rgba(37, 99, 235, 0.12); color: #0f172a; }
            QHeaderView::section { background-color: transparent; border: none; font-weight: 600; color: #475569; padding: 8px 6px; }
            QTableCornerButton::section { background-color: transparent; border: none; }
            QListWidget#checklist { border: none; }
            QListWidget#checklist::item { padding: 12px; margin: 4px 0; border-radius: 10px; }
            QListWidget#checklist::item:selected { background-color: rgba(37, 99, 235, 0.2); color: #0f172a; }
            #statBadge { background-color: #ffffff; border: 1px solid rgba(226, 232, 240, 0.8); border-radius: 16px; }
            #statTitle { font-size: 13px; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: 1px; }
            #statValue { font-size: 24px; font-weight: 700; color: #0f172a; }
            #statDescription { font-size: 12px; color: #64748b; }
            QScrollBar:vertical { width: 12px; background: transparent; }
            QScrollBar::handle:vertical { background-color: rgba(148, 163, 184, 0.6); border-radius: 6px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { background: none; }
            QStatusBar { background: transparent; color: #475569; }
            """
        )

    # endregion

    # region Handlinger
    def on_open(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Åpne SAF-T XML",
            str(Path.home()),
            "SAF-T XML (*.xml);;Alle filer (*)",
        )
        if not file_name:
            return
        try:
            root = ET.parse(file_name).getroot()
            self._header = parse_saft_header(root)
            df = parse_saldobalanse(root)
            self._cust_map = parse_customers(root)
            self._sales_agg = extract_sales_taxbase_by_customer(root)
            self._ar_agg = extract_ar_from_gl(root)
            self._saft_df = df
            self._saft_summary = ns4102_summary_from_tb(df)
            validation = validate_saft_against_xsd(file_name, self._header.file_version if self._header else None)
            self._validation_result = validation

            self._update_header_fields()
            self.saldobalanse_page.set_dataframe(df)
            self.kontroll_page.set_dataframe(df)
            self.dashboard_page.update_summary(self._saft_summary)
            company = self._header.company_name if self._header else None
            orgnr = self._header.orgnr if self._header else None
            period = None
            if self._header:
                period = (
                    f"{self._header.fiscal_year or '—'} P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
                )
            revenue_txt = (
                format_currency(self._saft_summary.get("driftsinntekter"))
                if self._saft_summary and self._saft_summary.get("driftsinntekter") is not None
                else "—"
            )
            account_count = len(df.index)
            status_bits = [
                company or "Ukjent selskap",
                f"Org.nr: {orgnr}" if orgnr else "Org.nr: –",
                f"Periode: {period}" if period else None,
                f"{account_count} konti analysert",
                f"Driftsinntekter: {revenue_txt}",
            ]
            self.dashboard_page.update_status(" · ".join(bit for bit in status_bits if bit))
            self.dashboard_page.update_validation_status(validation)
            if validation.is_valid is False:
                QMessageBox.warning(
                    self,
                    "XSD-validering feilet",
                    validation.details or "Valideringen mot XSD feilet. Se dashboard for detaljer.",
                )
            elif validation.is_valid is None and validation.details:
                QMessageBox.information(self, "XSD-validering", validation.details)
            self.dashboard_page.set_controls_enabled(True)
            self.dashboard_page.clear_top_customers()
            self.vesentlig_page.update_summary(self._saft_summary)
            self.regnskap_page.update_comparison(None)
            self.brreg_page.update_mapping(None)
            self.brreg_page.update_json(None)

            self.btn_brreg.setEnabled(True)
            self.btn_export.setEnabled(True)
            self.statusBar().showMessage(f"SAF-T lastet: {file_name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved lesing av SAF-T", str(exc))
            self.statusBar().showMessage("Feil ved lesing av SAF-T.")

    def _on_calc_top_customers(self, source: str, topn: int) -> Optional[List[Tuple[str, str, int, float]]]:
        if source == "faktura":
            if self._sales_agg is None or self._sales_agg.empty:
                QMessageBox.information(
                    self,
                    "Ingen fakturaer",
                    "Fant ingen fakturaopplysninger i SAF-T. Prøv kilde 'reskontro'.",
                )
                return None
            data = self._sales_agg.copy()
            data["Kundenavn"] = data["CustomerID"].map(self._cust_map).fillna("")
            data = data.sort_values("OmsetningEksMva", ascending=False).head(topn)
            rows = [
                (
                    str(row["CustomerID"]),
                    str(row["Kundenavn"] or ""),
                    int(row["Fakturaer"]),
                    float(row["OmsetningEksMva"]),
                )
                for _, row in data.iterrows()
            ]
            self.statusBar().showMessage(f"Topp kunder (faktura) beregnet. N={topn}.")
            return rows

        if self._ar_agg is None or self._ar_agg.empty:
            QMessageBox.information(
                self,
                "Ingen reskontro",
                "Fant ikke kunde-ID på reskontro (1500–1599) i SAF-T.",
            )
            return None
        data = self._ar_agg.copy()
        data["Kundenavn"] = data["CustomerID"].map(self._cust_map).fillna("")
        data["OmsetningEksMva"] = data["AR_Debit"]
        data["Fakturaer"] = 0
        data = data.sort_values("AR_Debit", ascending=False).head(topn)
        rows = [
            (
                str(row["CustomerID"]),
                str(row["Kundenavn"] or ""),
                int(row.get("Fakturaer", 0)),
                float(row["OmsetningEksMva"]),
            )
            for _, row in data.iterrows()
        ]
        self.statusBar().showMessage(f"Topp kunder (reskontro) beregnet. N={topn}.")
        return rows

    def on_brreg(self) -> None:
        if not self._header or not self._header.orgnr:
            QMessageBox.warning(self, "Mangler org.nr", "Fant ikke org.nr i SAF-T-headeren.")
            return
        orgnr = self._header.orgnr
        try:
            js = fetch_brreg(orgnr)
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved henting", str(exc))
            return
        self._brreg_json = js
        self._brreg_map = map_brreg_metrics(js)

        rows: List[Tuple[str, str]] = []

        def add_row(label: str, prefer_keys: Iterable[str]) -> None:
            hit = find_first_by_exact_endkey(js, prefer_keys, disallow_contains=["egenkapitalOgGjeld"] if "sumEgenkapital" in prefer_keys else None)
            if not hit and "sumEiendeler" in prefer_keys:
                hit = find_first_by_exact_endkey(js, ["sumEgenkapitalOgGjeld"])
            rows.append((label, f"{hit[0]} = {hit[1]}" if hit else "—"))

        add_row("Eiendeler (UB)", ["sumEiendeler"])
        add_row("Egenkapital (UB)", ["sumEgenkapital"])
        add_row("Gjeld (UB)", ["sumGjeld"])
        add_row("Driftsinntekter", ["driftsinntekter", "sumDriftsinntekter", "salgsinntekter"])
        add_row("EBIT", ["driftsresultat", "ebit", "driftsresultatFoerFinans"])
        add_row("Årsresultat", ["arsresultat", "resultat", "resultatEtterSkatt"])

        self.brreg_page.update_mapping(rows)
        self.brreg_page.update_json(js)

        if not self._saft_summary:
            self.statusBar().showMessage("Brreg-data hentet, men ingen SAF-T oppsummering å sammenligne mot.")
            return

        cmp_rows = [
            (
                "Driftsinntekter",
                self._saft_summary.get("driftsinntekter"),
                self._brreg_map.get("driftsinntekter") if self._brreg_map else None,
                None,
            ),
            (
                "EBIT",
                self._saft_summary.get("ebit"),
                self._brreg_map.get("ebit") if self._brreg_map else None,
                None,
            ),
            (
                "Årsresultat",
                self._saft_summary.get("arsresultat"),
                self._brreg_map.get("arsresultat") if self._brreg_map else None,
                None,
            ),
            (
                "Eiendeler (UB)",
                self._saft_summary.get("eiendeler_UB_brreg"),
                self._brreg_map.get("eiendeler_UB") if self._brreg_map else None,
                None,
            ),
            (
                "Egenkapital (UB)",
                self._saft_summary.get("egenkapital_UB"),
                self._brreg_map.get("egenkapital_UB") if self._brreg_map else None,
                None,
            ),
            (
                "Gjeld (UB)",
                self._saft_summary.get("gjeld_UB_brreg"),
                self._brreg_map.get("gjeld_UB") if self._brreg_map else None,
                None,
            ),
        ]
        self.regnskap_page.update_comparison(cmp_rows)
        self.statusBar().showMessage("Data hentet fra Regnskapsregisteret.")

    def on_export(self) -> None:
        if self._saft_df is None:
            QMessageBox.warning(self, "Ingenting å eksportere", "Last inn SAF-T først.")
            return
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Eksporter rapport",
            str(Path.home() / "SAFT_rapport.xlsx"),
            "Excel (*.xlsx)",
        )
        if not file_name:
            return
        try:
            with pd.ExcelWriter(file_name, engine="xlsxwriter") as writer:
                self._saft_df.to_excel(writer, sheet_name="Saldobalanse", index=False)
                if self._saft_summary:
                    summary_df = pd.DataFrame([self._saft_summary]).T.reset_index()
                    summary_df.columns = ["Nøkkel", "Beløp"]
                    summary_df.to_excel(writer, sheet_name="NS4102_Sammendrag", index=False)
                if self._sales_agg is not None:
                    self._sales_agg.to_excel(writer, sheet_name="Sales_by_customer", index=False)
                if self._ar_agg is not None:
                    self._ar_agg.to_excel(writer, sheet_name="AR_agg", index=False)
                if self._brreg_json:
                    pd.json_normalize(self._brreg_json).to_excel(writer, sheet_name="Brreg_JSON", index=False)
                if self._brreg_map:
                    map_df = pd.DataFrame(list(self._brreg_map.items()), columns=["Felt", "Verdi"])
                    map_df.to_excel(writer, sheet_name="Brreg_Mapping", index=False)
            self.statusBar().showMessage(f"Eksportert: {file_name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved eksport", str(exc))

    # endregion

    # region Navigasjon
    def _on_navigation_changed(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        if current is None:
            return
        key = current.data(0, Qt.UserRole)
        if key and key in self._page_map:
            widget = self._page_map[key]
            self.stack.setCurrentWidget(widget)
            self.title_label.setText(current.text(0))

    # endregion

    # region Hjelpere
    def _update_header_fields(self) -> None:
        if not self._header:
            return
        self.lbl_company.setText(f"Selskap: {self._header.company_name or '–'}")
        self.lbl_orgnr.setText(f"Org.nr: {self._header.orgnr or '–'}")
        per = f"{self._header.fiscal_year or '–'} P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
        self.lbl_period.setText(f"Periode: {per}")

    # endregion


def _populate_table(
    table: QTableWidget,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    money_cols: Optional[Iterable[int]] = None,
) -> None:
    money_idx = set(money_cols or [])
    table.setRowCount(0)
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)

    for row_idx, row in enumerate(rows):
        table.insertRow(row_idx)
        for col_idx, value in enumerate(row):
            display = _format_value(value, col_idx in money_idx)
            item = QTableWidgetItem(display)
            if col_idx in money_idx:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(row_idx, col_idx, item)

    table.resizeRowsToContents()


def _format_value(value: object, money: bool) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and math.isnan(value):
        return "—"
    try:
        if isinstance(value, (float, int)) and pd.isna(value):
            return "—"
        if not isinstance(value, (float, int)) and pd.isna(value):  # type: ignore[arg-type]
            return "—"
    except NameError:
        pass
    except Exception:
        pass
    if isinstance(value, (int, float)):
        if money:
            return _format_money_norwegian(float(value))
        numeric = float(value)
        return _format_integer_norwegian(numeric) if numeric.is_integer() else _format_money_norwegian(numeric)
    return str(value)


def _format_money_norwegian(value: float) -> str:
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", " ")
    return formatted.replace(".", ",")


def _format_integer_norwegian(value: float) -> str:
    formatted = f"{int(round(value)):,}"
    return formatted.replace(",", " ")


def create_app() -> Tuple[QApplication, NordlysWindow]:
    """Fabrikkfunksjon for å opprette QApplication og hovedvindu."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = NordlysWindow()
    return app, window


def run() -> None:
    """Starter PySide6-applikasjonen på en trygg måte."""
    try:
        app, window = create_app()
        window.show()
        sys.exit(app.exec())
    except Exception as exc:  # pragma: no cover - fallback dersom Qt ikke starter
        print("Kritisk feil:", exc, file=sys.stderr)
        sys.exit(1)


__all__ = ["NordlysWindow", "create_app", "run"]
