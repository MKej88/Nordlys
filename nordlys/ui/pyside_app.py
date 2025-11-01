"""PySide6-basert GUI for Nordlys SAF-T analysator."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
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
    extract_ar_from_gl,
    extract_sales_taxbase_by_customer,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saldobalanse,
    parse_saft_header,
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
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
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


class DashboardPage(QWidget):
    """Viser nøkkeltall og topp kunder."""

    def __init__(self, on_calc_top: Callable[[str, int], Optional[List[Tuple[str, str, int, float]]]]) -> None:
        super().__init__()
        self._on_calc_top = on_calc_top

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.status_card = CardFrame(
            "Oppdragsstatus",
            "Hurtigoversikt over datagrunnlag, klient og anbefalte neste steg.",
        )
        self.status_label = QLabel(
            "Ingen SAF-T fil er lastet inn ennå. Velg «Åpne SAF-T XML …» for å starte analysen."
        )
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.RichText)
        self.status_card.add_widget(self.status_label)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(12)
        self.overview_values: Dict[str, QLabel] = {}

        for idx, (key, title) in enumerate(
            [
                ("company", "Selskap"),
                ("orgnr", "Org.nr"),
                ("fiscal_year", "Regnskapsår"),
                ("period", "Periode"),
                ("file_version", "Filversjon"),
                ("accounts", "Konti i saldobalanse"),
                ("customers", "Registrerte kunder"),
            ]
        ):
            title_label = QLabel(title.upper())
            title_label.setObjectName("overviewTitle")
            value_label = QLabel("—")
            value_label.setObjectName("overviewValue")
            info_grid.addWidget(title_label, idx // 3 * 2, idx % 3)
            info_grid.addWidget(value_label, idx // 3 * 2 + 1, idx % 3)
            self.overview_values[key] = value_label

        for col in range(3):
            info_grid.setColumnStretch(col, 1)

        self.status_card.add_layout(info_grid)
        layout.addWidget(self.status_card)

        self.metrics_card = CardFrame(
            "Resultatindikatorer",
            "Viser de mest sentrale nøkkeltallene fra SAF-T analysen.",
        )
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(16)
        self.metric_values: Dict[str, QLabel] = {}

        for key, title, hint in [
            ("driftsinntekter", "Omsetning", "Sum driftsinntekter i perioden."),
            ("ebitda", "EBITDA", "Driftsresultat før avskrivninger."),
            ("arsresultat", "Årsresultat", "Resultat etter skatt."),
            ("margin", "EBIT-margin", "EBIT i prosent av omsetning."),
            ("balanse_diff", "Balanseavvik", "Differanse mellom eiendeler og EK+gjeld."),
        ]:
            metric = QFrame()
            metric.setObjectName("metricCard")
            metric_layout = QVBoxLayout(metric)
            metric_layout.setContentsMargins(20, 16, 20, 16)
            metric_layout.setSpacing(6)

            title_label = QLabel(title.upper())
            title_label.setObjectName("metricTitle")
            metric_layout.addWidget(title_label)

            value_label = QLabel("—")
            value_label.setObjectName("metricValue")
            value_label.setProperty("trend", "neutral")
            metric_layout.addWidget(value_label)

            hint_label = QLabel(hint)
            hint_label.setObjectName("metricHint")
            hint_label.setWordWrap(True)
            metric_layout.addWidget(hint_label)

            metric_layout.addStretch(1)
            metrics_layout.addWidget(metric, 1)
            self.metric_values[key] = value_label

        self.metrics_card.add_layout(metrics_layout)
        layout.addWidget(self.metrics_card)

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

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self.summary_table.setRowCount(0)
            self._reset_metrics()
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
        self._update_metrics(summary)

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

    def update_overview(
        self,
        header: Optional[SaftHeader],
        *,
        accounts: Optional[int] = None,
        customers: Optional[int] = None,
    ) -> None:
        company = header.company_name if header is not None else None
        orgnr = header.orgnr if header is not None else None
        fiscal_year = header.fiscal_year if header is not None else None
        period_start = header.period_start if header is not None else None
        period_end = header.period_end if header is not None else None
        file_version = header.file_version if header is not None else None

        self._set_overview_value("company", company)
        self._set_overview_value("orgnr", orgnr)
        self._set_overview_value("fiscal_year", fiscal_year)
        if period_start or period_end:
            period_text = f"{period_start or '?'} – {period_end or '?'}"
        else:
            period_text = None
        self._set_overview_value("period", period_text)
        self._set_overview_value("file_version", file_version)
        accounts_text = f"{accounts:,}" if accounts is not None else None
        if accounts_text:
            accounts_text = accounts_text.replace(",", " ")
        customers_text = f"{customers:,}" if customers is not None else None
        if customers_text:
            customers_text = customers_text.replace(",", " ")
        self._set_overview_value("accounts", accounts_text)
        self._set_overview_value("customers", customers_text)

    def _set_overview_value(self, key: str, value: Optional[str]) -> None:
        label = self.overview_values.get(key)
        if not label:
            return
        label.setText(value if value else "—")

    def _reset_metrics(self) -> None:
        for label in self.metric_values.values():
            label.setText("—")
            label.setProperty("trend", "neutral")
            label.style().unpolish(label)
            label.style().polish(label)

    def _update_metrics(self, summary: Dict[str, float]) -> None:
        revenue = summary.get("driftsinntekter")
        ebitda = summary.get("ebitda")
        net_income = summary.get("arsresultat")
        ebit = summary.get("ebit")
        balance_diff = summary.get("balanse_diff")

        self._set_metric_value("driftsinntekter", format_currency(revenue), "positive")
        self._set_metric_value("ebitda", format_currency(ebitda), self._trend_from_value(ebitda))
        self._set_metric_value("arsresultat", format_currency(net_income), self._trend_from_value(net_income))

        margin = None
        if revenue:
            try:
                margin = (ebit or 0.0) / revenue if revenue else None
            except Exception:
                margin = None
        margin_text = self._format_percent(margin)
        margin_trend = "neutral"
        if margin is not None:
            if margin >= 0.1:
                margin_trend = "positive"
            elif margin >= 0.0:
                margin_trend = "warning"
            else:
                margin_trend = "negative"
        self._set_metric_value("margin", margin_text, margin_trend)

        balance_trend = "neutral"
        if balance_diff is not None:
            threshold_good = max(1000.0, (revenue or 0.0) * 0.002)
            threshold_warn = max(5000.0, (revenue or 0.0) * 0.01)
            diff_abs = abs(balance_diff)
            if diff_abs <= threshold_good:
                balance_trend = "positive"
            elif diff_abs <= threshold_warn:
                balance_trend = "warning"
            else:
                balance_trend = "negative"
        balance_text = format_currency(balance_diff)
        self._set_metric_value("balanse_diff", balance_text, balance_trend)

    def _set_metric_value(self, key: str, text: str, trend: str) -> None:
        label = self.metric_values.get(key)
        if not label:
            return
        label.setText(text if text else "—")
        label.setProperty("trend", trend)
        label.style().unpolish(label)
        label.style().polish(label)

    @staticmethod
    def _trend_from_value(value: Optional[float]) -> str:
        if value is None:
            return "neutral"
        if value > 0:
            return "positive"
        if value == 0:
            return "neutral"
        return "negative"

    @staticmethod
    def _format_percent(value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"{value * 100:,.1f} %"


class DataFramePage(QWidget):
    """Generisk side som viser en pandas DataFrame."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.card = CardFrame(title, subtitle)
        self.info_label = QLabel("Last inn en SAF-T fil for å vise data.")
        self.info_label.setObjectName("infoLabel")
        self.card.add_widget(self.info_label)

        self.table = _create_table_widget()
        self.table.hide()
        self.card.add_widget(self.table)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def set_dataframe(self, df: Optional[pd.DataFrame]) -> None:
        if df is None or df.empty:
            self.table.hide()
            self.info_label.show()
            self.table.setRowCount(0)
            return
        columns = list(df.columns)
        rows = [tuple(df.iloc[i][column] for column in columns) for i in range(len(df))]
        _populate_table(self.table, columns, rows)
        self.table.show()
        self.info_label.hide()


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
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(24)

        self.logo_label = QLabel("Nordlys")
        self.logo_label.setObjectName("logoLabel")
        layout.addWidget(self.logo_label)

        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(12)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional[SaftHeader] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._cust_map: Dict[str, str] = {}
        self._sales_agg: Optional[pd.DataFrame] = None
        self._ar_agg: Optional[pd.DataFrame] = None

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
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(24)
        root_layout.addWidget(content_wrapper, 1)

        header_layout = QHBoxLayout()
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

        content_layout.addLayout(header_layout)

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
        self.dashboard_page.update_overview(None)

        status = QStatusBar()
        status.showMessage("Klar.")
        self.setStatusBar(status)

    def _create_pages(self) -> None:
        dashboard = DashboardPage(self._on_calc_top_customers)
        self._register_page("dashboard", dashboard)
        self.stack.addWidget(dashboard)
        self.dashboard_page = dashboard

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
            QWidget { font-family: 'Inter', 'IBM Plex Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 13px; color: #0f172a; }
            QMainWindow { background-color: #f1f5f9; }
            QStatusBar { background-color: #e2e8f0; border-top: 1px solid #cbd5f5; color: #1e293b; }
            #navPanel { background-color: #0b1120; color: #e2e8f0; }
            #logoLabel { font-size: 24px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #f8fafc; }
            #navTree { background: transparent; border: none; color: #cbd5f5; font-size: 14px; font-weight: 500; }
            #navTree::item { height: 34px; margin: 2px 0; padding-left: 6px; border-radius: 8px; }
            #navTree::item:selected { background-color: #1d4ed8; color: white; }
            #navTree::item:hover { background-color: rgba(59, 130, 246, 0.25); }
            QPushButton { background-color: #1d4ed8; color: white; border-radius: 8px; padding: 10px 18px; font-weight: 600; border: none; }
            QPushButton:disabled { background-color: #94a3b8; color: #e2e8f0; }
            QPushButton:hover:!disabled { background-color: #1e3a8a; }
            QPushButton:focus-visible { outline: 3px solid rgba(59, 130, 246, 0.45); outline-offset: 2px; }
            #card { background-color: #ffffff; border-radius: 20px; border: 1px solid #e2e8f0; }
            #cardTitle { font-size: 18px; font-weight: 700; color: #0f172a; }
            #cardSubtitle { color: #64748b; font-size: 13px; }
            #pageTitle { font-size: 26px; font-weight: 700; color: #0f172a; }
            #statusLabel { color: #1f2937; font-size: 14px; line-height: 1.5; }
            #overviewTitle { font-size: 11px; letter-spacing: 0.1em; color: #94a3b8; }
            #overviewValue { font-size: 15px; font-weight: 600; color: #0f172a; }
            QFrame#metricCard { background-color: #f8fafc; border-radius: 18px; border: 1px solid #e2e8f0; }
            QLabel#metricTitle { font-size: 11px; letter-spacing: 0.12em; color: #64748b; }
            QLabel#metricValue { font-size: 24px; font-weight: 700; color: #0f172a; }
            QLabel#metricValue[trend="positive"] { color: #047857; }
            QLabel#metricValue[trend="negative"] { color: #dc2626; }
            QLabel#metricValue[trend="warning"] { color: #b45309; }
            QLabel#metricValue[trend="neutral"] { color: #0f172a; }
            QLabel#metricHint { color: #64748b; font-size: 12px; }
            #infoLabel { color: #64748b; }
            #jsonView { background-color: #0f172a; color: #f8fafc; font-family: 'Fira Code', 'JetBrains Mono', monospace; border-radius: 12px; padding: 12px; }
            #cardTable { border: none; }
            QHeaderView::section { background-color: transparent; border: none; font-weight: 600; color: #475569; }
            QListWidget#checklist { border: none; }
            QListWidget#checklist::item { padding: 8px; margin: 2px 0; border-radius: 6px; }
            QListWidget#checklist::item:selected { background-color: rgba(37, 99, 235, 0.15); color: #0f172a; }
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

            self._update_header_fields()
            self.kontroll_page.set_dataframe(df)
            self.dashboard_page.update_summary(self._saft_summary)
            account_count = len(df.index)
            customer_count = len(self._cust_map)

            def money_text(key: str) -> str:
                if not self._saft_summary:
                    return "—"
                formatted = format_currency(self._saft_summary.get(key))
                return f"{formatted} kr" if formatted != "—" else "—"

            revenue = self._saft_summary.get("driftsinntekter") if self._saft_summary else None
            ebit = self._saft_summary.get("ebit") if self._saft_summary else None
            margin = (ebit / revenue * 100) if revenue else None
            margin_text = "—" if margin is None else f"{margin:,.1f} %"

            if self._header:
                period_desc = (
                    f"År {self._header.fiscal_year or 'ukjent'}, "
                    f"P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
                )
                company_name = self._header.company_name or "ukjent selskap"
            else:
                period_desc = "—"
                company_name = "ukjent selskap"

            account_text = f"{account_count:,}".replace(",", " ")
            customer_text = f"{customer_count:,}".replace(",", " ")

            status_html = (
                f"<b>Analyse fullført for {company_name}.</b><br>"
                "<ul>"
                f"<li>Periode: {period_desc}</li>"
                f"<li>{account_text} konti og {customer_text} kunder analysert.</li>"
                f"<li>Omsetning: {money_text('driftsinntekter')} | EBITDA: {money_text('ebitda')}</li>"
                f"<li>EBIT-margin: {margin_text} | Balanseavvik: {money_text('balanse_diff')}</li>"
                "</ul>"
                "Planlegg videre arbeid via navigasjonen til venstre."
            )

            self.dashboard_page.update_status(status_html)
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
        account_count = int(self._saft_df.shape[0]) if self._saft_df is not None else None
        customer_count = len(self._cust_map) or None
        self.dashboard_page.update_overview(
            self._header,
            accounts=account_count,
            customers=customer_count,
        )

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
    if isinstance(value, (int, float)):
        if money:
            return f"{float(value):,.2f}"
        return f"{float(value):,.0f}" if float(value).is_integer() else f"{float(value):,.2f}"
    return str(value)


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
