"""PySide6-basert GUI for Nordlys SAF-T analysator."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
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


# region hjelpeklasser


class PandasModel(QAbstractTableModel):
    """Enkel modell for å vise pandas-data i QTableView."""

    def __init__(self, dataframe: pd.DataFrame) -> None:
        super().__init__()
        self._dataframe = dataframe.reset_index(drop=True)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return int(self._dataframe.shape[0])

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return int(self._dataframe.shape[1])

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.TextAlignmentRole):
            return None
        value = self._dataframe.iat[index.row(), index.column()]
        if role == Qt.TextAlignmentRole:
            if isinstance(value, (int, float)):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._dataframe.columns[section])
        return str(section + 1)


class DataTablePage(QWidget):
    """Side som viser en tabell."""

    def __init__(self, title: str, description: str | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if description:
            lbl = QLabel(description)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #4a5568; font-size: 13px;")
            layout.addWidget(lbl)
        self._table = QTableView()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("QTableView { background: white; border: 1px solid #d5dbe5; }")
        layout.addWidget(self._table)
        self._empty_label = QLabel("Ingen data tilgjengelig.")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: #718096; padding: 40px;")
        layout.addWidget(self._empty_label)
        self._table.hide()

    def set_dataframe(self, df: Optional[pd.DataFrame]) -> None:
        if df is None or df.empty:
            self._table.hide()
            self._empty_label.show()
            return
        self._table.setModel(PandasModel(df))
        self._table.resizeColumnsToContents()
        self._empty_label.hide()
        self._table.show()


class SummaryCards(QWidget):
    """Viser sentrale nøkkeltall i kort."""

    def __init__(self) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setSpacing(16)
        self._cards: Dict[str, Tuple[QLabel, QLabel]] = {}

    def set_metrics(self, metrics: Sequence[Tuple[str, Optional[float]]]) -> None:
        # Fjern eksisterende widgets
        for title, (lbl_title, lbl_value) in list(self._cards.items()):
            lbl_title.deleteLater()
            lbl_value.deleteLater()
        self._cards.clear()

        layout: QGridLayout = self.layout()  # type: ignore[assignment]
        while layout.count():
            item = layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

        for index, (label, value) in enumerate(metrics):
            container = QFrame()
            container.setFrameShape(QFrame.StyledPanel)
            container.setStyleSheet(
                "QFrame { background: white; border-radius: 12px; border: 1px solid #e2e8f0; padding: 16px; }"
            )
            inner = QVBoxLayout(container)
            title_lbl = QLabel(label)
            title_lbl.setStyleSheet("font-size: 13px; color: #4a5568;")
            value_lbl = QLabel(format_currency(value))
            value_lbl.setStyleSheet("font-size: 22px; font-weight: 600; color: #1a202c;")
            inner.addWidget(title_lbl)
            inner.addStretch(1)
            inner.addWidget(value_lbl)
            row = index // 3
            col = index % 3
            layout.addWidget(container, row, col)
            self._cards[label] = (title_lbl, value_lbl)


class DashboardPage(QWidget):
    """Dashboardside med oversikt over SAF-T-filen."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self._info_frame = QFrame()
        self._info_frame.setStyleSheet(
            "QFrame { background: white; border-radius: 16px; border: 1px solid #e2e8f0; padding: 24px; }"
        )
        info_layout = QGridLayout(self._info_frame)
        info_layout.setHorizontalSpacing(32)
        info_layout.setVerticalSpacing(12)

        font = QFont()
        font.setPointSize(11)
        font.setBold(True)

        self._company_label = QLabel("Selskap: –")
        self._org_label = QLabel("Org.nr: –")
        self._period_label = QLabel("Periode: –")
        for label in (self._company_label, self._org_label, self._period_label):
            label.setStyleSheet("font-size: 15px; color: #1a202c;")

        info_layout.addWidget(self._company_label, 0, 0)
        info_layout.addWidget(self._org_label, 0, 1)
        info_layout.addWidget(self._period_label, 0, 2)

        layout.addWidget(self._info_frame)

        self._summary_cards = SummaryCards()
        layout.addWidget(self._summary_cards)

        self._message = QLabel(
            "Last inn en SAF-T-fil for å se nøkkeltall. Navigasjonen til venstre gir tilgang til planlegging og revisjon."
        )
        self._message.setWordWrap(True)
        self._message.setStyleSheet("color: #4a5568; font-size: 13px;")
        layout.addWidget(self._message)
        layout.addStretch(1)

    def update_header(self, header: Optional[SaftHeader]) -> None:
        if not header:
            self._company_label.setText("Selskap: –")
            self._org_label.setText("Org.nr: –")
            self._period_label.setText("Periode: –")
            return
        per = f"{header.fiscal_year or '–'} P{header.period_start or '?'}–P{header.period_end or '?'}"
        self._company_label.setText(f"Selskap: {header.company_name or '–'}")
        self._org_label.setText(f"Org.nr: {header.orgnr or '–'}")
        self._period_label.setText(f"Periode: {per}")

    def update_summary(self, summary: Optional[Dict[str, float]]) -> None:
        if not summary:
            self._summary_cards.set_metrics([])
            return
        metrics = [
            ("Driftsinntekter", summary.get("driftsinntekter")),
            ("Varekostnad", summary.get("varekostnad")),
            ("Lønn", summary.get("lonn")),
            ("EBITDA", summary.get("ebitda")),
            ("EBIT", summary.get("ebit")),
            ("Årsresultat", summary.get("arsresultat")),
        ]
        self._summary_cards.set_metrics(metrics)


class SummaryListPage(QWidget):
    """Side for nøkkeltall-lister."""

    def __init__(self, description: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._description = QLabel(description)
        self._description.setWordWrap(True)
        self._description.setStyleSheet("color: #4a5568; font-size: 13px;")
        layout.addWidget(self._description)
        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.setStyleSheet("QTextEdit { background: white; border: 1px solid #d5dbe5; padding: 16px; }")
        self._content.setMinimumHeight(280)
        layout.addWidget(self._content)
        layout.addStretch(1)

    def set_entries(self, rows: Sequence[Tuple[str, Optional[float]]]) -> None:
        if not rows:
            self._content.setPlainText("Ingen data tilgjengelig.")
            return
        lines = [f"• {label}: {format_currency(value)}" for label, value in rows]
        self._content.setPlainText("\n".join(lines))


class PlaceholderPage(QWidget):
    """Generisk plassholder for moduler uten funksjonalitet enda."""

    def __init__(self, message: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #718096; font-size: 14px; padding: 40px;")
        layout.addWidget(label)
        layout.addStretch(1)


class ComparisonPage(QWidget):
    """Side for sammenstilling mellom SAF-T og Brreg."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self._mapping_table = DataTablePage(
            "Brreg-nøkkeltall",
            "Direkte funn fra Regnskapsregisteret med tilhørende JSON-stier.",
        )
        layout.addWidget(self._mapping_table)

        self._comparison_table = DataTablePage(
            "Sammenstilling",
            "Tallene nedenfor viser nøkkeltall fra SAF-T sammenlignet med Regnskapsregisteret.",
        )
        layout.addWidget(self._comparison_table)

        self._json_view = QTextEdit()
        self._json_view.setReadOnly(True)
        self._json_view.setStyleSheet("QTextEdit { background: white; border: 1px solid #d5dbe5; padding: 16px; }")
        self._json_view.setPlaceholderText("Regnskapsdata fra Brønnøysundregistrene vises her etter henting.")
        self._json_view.setMinimumHeight(240)
        layout.addWidget(self._json_view)

    def set_mapping(self, rows: Sequence[Tuple[str, str]]) -> None:
        df = pd.DataFrame(rows, columns=["Felt", "Sti = Verdi"])
        self._mapping_table.set_dataframe(df)

    def set_comparison(self, rows: Sequence[Tuple[str, str, str, str]]) -> None:
        df = pd.DataFrame(rows, columns=["Nøkkel", "SAF-T", "Brreg", "Avvik"])
        self._comparison_table.set_dataframe(df)

    def set_json(self, data: Optional[Dict[str, object]]) -> None:
        if not data:
            self._json_view.setPlainText("")
            return
        self._json_view.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))


class TopCustomersPage(QWidget):
    """Side for beregning av toppkunder."""

    request_calculation = Signal(str, int)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        controls = QFrame()
        controls.setStyleSheet("QFrame { background: white; border: 1px solid #d5dbe5; border-radius: 12px; }")
        ctrl_layout = QHBoxLayout(controls)
        ctrl_layout.setContentsMargins(16, 16, 16, 16)
        ctrl_layout.setSpacing(12)

        ctrl_layout.addWidget(QLabel("Datakilde:"))
        self._source = QComboBox()
        self._source.addItems(["faktura", "reskontro"])
        ctrl_layout.addWidget(self._source)

        ctrl_layout.addWidget(QLabel("Antall:"))
        self._spin = QSpinBox()
        self._spin.setRange(5, 100)
        self._spin.setValue(10)
        ctrl_layout.addWidget(self._spin)

        self._button = QPushButton("Beregn toppkunder")
        self._button.clicked.connect(self._on_clicked)
        ctrl_layout.addWidget(self._button)
        ctrl_layout.addStretch(1)

        layout.addWidget(controls)

        self._table = DataTablePage("Toppkunder")
        layout.addWidget(self._table)

    def _on_clicked(self) -> None:
        self.request_calculation.emit(self._source.currentText(), self._spin.value())

    def set_rows(self, rows: Sequence[Tuple[str, str, int, float]]) -> None:
        df = pd.DataFrame(rows, columns=["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"])
        self._table.set_dataframe(df)


# endregion


@dataclass
class NavigationEntry:
    page_id: str
    title: str
    children: Sequence["NavigationEntry"] | None = None


NAVIGATION: List[NavigationEntry] = [
    NavigationEntry("dashboard", "Dashboard"),
    NavigationEntry(
        "planlegging",
        "Planlegging",
        children=[
            NavigationEntry("planlegging_kontroll_ib", "Kontroll IB"),
            NavigationEntry("planlegging_vesentlighet", "Vesentlighetsvurdering"),
            NavigationEntry("planlegging_regnskapsanalyse", "Regnskapsanalyse"),
            NavigationEntry("planlegging_sammenstilling", "Sammenstillingsanalyse"),
        ],
    ),
    NavigationEntry(
        "revisjon",
        "Revisjon",
        children=[
            NavigationEntry("revisjon_innkjop", "Innkjøp og leverandørgjeld"),
            NavigationEntry("revisjon_lonn", "Lønn"),
            NavigationEntry("revisjon_kostnad", "Kostnad"),
            NavigationEntry("revisjon_driftsmidler", "Driftsmidler"),
            NavigationEntry("revisjon_finans", "Finans og likvid"),
            NavigationEntry("revisjon_varelager", "Varelager og varekjøp"),
            NavigationEntry("revisjon_salg", "Salg og kundefordringer"),
            NavigationEntry("revisjon_mva", "MVA"),
        ],
    ),
]


class NavigationList(QListWidget):
    """Navigasjonsliste med hoved- og underpunkter."""

    page_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setSpacing(4)
        self.setStyleSheet(
            "QListWidget { background-color: #172337; color: #e2e8f0; border: none; }"
            "QListWidget::item { padding: 10px 14px; border-radius: 8px; }"
            "QListWidget::item:selected { background-color: #2c3e63; color: white; }"
        )
        self.setSelectionMode(QListWidget.SingleSelection)
        self._populate()
        self.currentItemChanged.connect(self._on_change)

    def _populate(self) -> None:
        bold = QFont()
        bold.setBold(True)
        for entry in NAVIGATION:
            item = QListWidgetItem(entry.title)
            item.setData(Qt.UserRole, entry.page_id)
            item.setFont(bold)
            self.addItem(item)
            if not entry.children:
                continue
            for child in entry.children:
                child_item = QListWidgetItem(f"   {child.title}")
                child_item.setData(Qt.UserRole, child.page_id)
                self.addItem(child_item)

    def _on_change(self, current: QListWidgetItem, previous: QListWidgetItem | None) -> None:  # noqa: ARG002
        if not current:
            return
        page_id = current.data(Qt.UserRole)
        if page_id:
            self.page_selected.emit(page_id)


class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 900)

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional[SaftHeader] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._cust_map: Dict[str, str] = {}
        self._sales_agg: Optional[pd.DataFrame] = None
        self._ar_agg: Optional[pd.DataFrame] = None

        self._build_ui()

    # region UI
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(
            "QSplitter::handle { background-color: #e2e8f0; width: 1px; }"
        )
        main_layout.addWidget(splitter)

        nav_container = QFrame()
        nav_container.setMinimumWidth(260)
        nav_container.setMaximumWidth(320)
        nav_container.setStyleSheet("QFrame { background-color: #172337; }")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(24, 24, 24, 24)
        nav_layout.setSpacing(16)

        title = QLabel("Nordlys Revisjon")
        title.setStyleSheet("color: white; font-size: 20px; font-weight: 600;")
        nav_layout.addWidget(title)

        subtitle = QLabel("Naviger mellom faser og arbeidsområder")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #cbd5f5; font-size: 12px;")
        nav_layout.addWidget(subtitle)

        self._nav = NavigationList()
        nav_layout.addWidget(self._nav, 1)

        nav_layout.addStretch(1)

        splitter.addWidget(nav_container)

        content_container = QWidget()
        splitter.addWidget(content_container)
        splitter.setStretchFactor(1, 1)

        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(32, 24, 32, 24)
        content_layout.setSpacing(16)
        content_container.setStyleSheet("background-color: #f3f6fb;")

        header_frame = QFrame()
        header_frame.setStyleSheet(
            "QFrame { background-color: white; border-radius: 16px; border: 1px solid #e2e8f0; }"
        )
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(24, 16, 24, 16)

        self._page_title = QLabel("Dashboard")
        self._page_title.setStyleSheet("font-size: 22px; font-weight: 600; color: #1a202c;")
        header_layout.addWidget(self._page_title)
        header_layout.addStretch(1)

        self._btn_open = QPushButton("Åpne SAF-T …")
        self._btn_open.clicked.connect(self.on_open)
        header_layout.addWidget(self._btn_open)

        self._btn_brreg = QPushButton("Hent Regnskapsregisteret")
        self._btn_brreg.clicked.connect(self.on_brreg)
        self._btn_brreg.setEnabled(False)
        header_layout.addWidget(self._btn_brreg)

        self._btn_export = QPushButton("Eksporter rapport")
        self._btn_export.clicked.connect(self.on_export)
        self._btn_export.setEnabled(False)
        header_layout.addWidget(self._btn_export)

        content_layout.addWidget(header_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content_layout.addWidget(scroll, 1)

        self._stack_container = QWidget()
        self._stack_layout = QVBoxLayout(self._stack_container)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._stack_container)

        self._stack = QStackedWidget()
        self._stack_layout.addWidget(self._stack)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Klar.")

        self._pages: Dict[str, QWidget] = {}
        self._create_pages()

        self._nav.page_selected.connect(self._on_page_selected)
        self._nav.setCurrentRow(0)

    def _create_pages(self) -> None:
        self._dashboard_page = DashboardPage()
        self._add_page("dashboard", self._dashboard_page)

        self._add_page(
            "planlegging",
            PlaceholderPage("Velg et område under planlegging for å se detaljer fra SAF-T-analysen."),
        )
        self._kontroll_ib_page = DataTablePage(
            "Kontroll IB",
            "Detaljert oversikt over saldobalanse slik den er rapportert i SAF-T.",
        )
        self._add_page("planlegging_kontroll_ib", self._kontroll_ib_page)

        self._vesentlighet_page = SummaryListPage(
            "Nøkkeltallene brukes som grunnlag for vesentlighetsvurderingen og gir et raskt overblikk over "
            "resultat- og balanseposter.",
        )
        self._add_page("planlegging_vesentlighet", self._vesentlighet_page)

        self._regnskapsanalyse_page = PlaceholderPage(
            "Regnskapsanalyse blir tilgjengelig når ytterligere moduler er utviklet."
        )
        self._add_page("planlegging_regnskapsanalyse", self._regnskapsanalyse_page)

        self._sammenstilling_page = ComparisonPage()
        self._add_page("planlegging_sammenstilling", self._sammenstilling_page)

        self._add_page(
            "revisjon",
            PlaceholderPage("Velg et revisjonsområde i menyen for å få tilgang til planlagte analyser."),
        )
        self._innkjop_page = PlaceholderPage(
            "Analyse av innkjøp og leverandørgjeld er under utvikling."
        )
        self._add_page("revisjon_innkjop", self._innkjop_page)

        self._lonn_page = PlaceholderPage("Lønnsanalyser implementeres i en senere versjon.")
        self._add_page("revisjon_lonn", self._lonn_page)

        self._kostnad_page = PlaceholderPage("Kostnadsanalyse blir tilgjengelig senere.")
        self._add_page("revisjon_kostnad", self._kostnad_page)

        self._driftsmidler_page = PlaceholderPage("Driftsmiddelkontroller blir tilgjengelig senere.")
        self._add_page("revisjon_driftsmidler", self._driftsmidler_page)

        self._finans_page = PlaceholderPage("Finans- og likviditetsanalyse kommer snart.")
        self._add_page("revisjon_finans", self._finans_page)

        self._varelager_page = PlaceholderPage("Analyse av varelager og varekjøp er under arbeid.")
        self._add_page("revisjon_varelager", self._varelager_page)

        self._salg_page = TopCustomersPage()
        self._salg_page.request_calculation.connect(self._on_calc_top_customers)
        self._add_page("revisjon_salg", self._salg_page)

        self._mva_page = PlaceholderPage("MVA-avstemminger blir tilgjengelig senere.")
        self._add_page("revisjon_mva", self._mva_page)

    def _add_page(self, page_id: str, widget: QWidget) -> None:
        self._pages[page_id] = widget
        self._stack.addWidget(widget)

    # endregion

    # region Datahåndtering
    def _set_current_page(self, page_id: str) -> None:
        widget = self._pages.get(page_id)
        if widget is None:
            return
        self._stack.setCurrentWidget(widget)

    def _on_page_selected(self, page_id: str) -> None:
        self._set_current_page(page_id)
        title = next((entry.title for entry in self._walk_navigation() if entry.page_id == page_id), page_id)
        self._page_title.setText(title)

    def _walk_navigation(self) -> Iterable[NavigationEntry]:
        for entry in NAVIGATION:
            yield entry
            if entry.children:
                for child in entry.children:
                    yield child

    def on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Velg SAF-T XML", "", "SAF-T XML (*.xml);;Alle filer (*.*)")
        if not path:
            return
        try:
            root = ET.parse(path).getroot()
            self._header = parse_saft_header(root)
            df = parse_saldobalanse(root)
            self._cust_map = parse_customers(root)
            self._sales_agg = extract_sales_taxbase_by_customer(root)
            self._ar_agg = extract_ar_from_gl(root)
            self._saft_df = df
            self._saft_summary = ns4102_summary_from_tb(df)
        except Exception as exc:
            QMessageBox.critical(self, "Feil ved lesing", str(exc))
            self.status_bar.showMessage("Feil ved lesing av SAF-T.")
            return

        self._dashboard_page.update_header(self._header)
        self._dashboard_page.update_summary(self._saft_summary)
        self._kontroll_ib_page.set_dataframe(self._saft_df)

        if self._saft_summary:
            rows = [
                ("Driftsinntekter (3xxx)", self._saft_summary.get("driftsinntekter")),
                ("Varekostnad (4xxx)", self._saft_summary.get("varekostnad")),
                ("Lønn (5xxx)", self._saft_summary.get("lonn")),
                ("Andre driftskostnader", self._saft_summary.get("andre_drift")),
                ("EBITDA", self._saft_summary.get("ebitda")),
                ("Avskrivninger", self._saft_summary.get("avskrivninger")),
                ("EBIT", self._saft_summary.get("ebit")),
                ("Netto finans", self._saft_summary.get("finans_netto")),
                ("Skatt", self._saft_summary.get("skattekostnad")),
                ("Årsresultat", self._saft_summary.get("arsresultat")),
                ("Eiendeler (UB)", self._saft_summary.get("eiendeler_UB")),
                ("Gjeld (UB)", self._saft_summary.get("gjeld_UB")),
                ("Balanseavvik", self._saft_summary.get("balanse_diff")),
                ("Eiendeler (Brreg-tilpasset)", self._saft_summary.get("eiendeler_UB_brreg")),
                ("Gjeld (Brreg-tilpasset)", self._saft_summary.get("gjeld_UB_brreg")),
                ("Balanseavvik (Brreg)", self._saft_summary.get("balanse_diff_brreg")),
                (
                    "Reklassifisering (21xx–29xx)",
                    self._saft_summary.get("liab_debet_21xx_29xx"),
                ),
            ]
            self._vesentlighet_page.set_entries(rows)
        else:
            self._vesentlighet_page.set_entries([])

        self._btn_brreg.setEnabled(True)
        self._btn_export.setEnabled(True)
        self.status_bar.showMessage("SAF-T lest. Klar til videre analyser.")

    def _on_calc_top_customers(self, source: str, topn: int) -> None:
        topn = max(1, min(topn, 100))
        if source == "faktura":
            if self._sales_agg is None or self._sales_agg.empty:
                QMessageBox.information(
                    self,
                    "Ingen fakturaer",
                    "Fant ingen fakturaer med CustomerID/TaxBase/NetTotal i SAF-T. Prøv reskontro.",
                )
                return
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
            self._salg_page.set_rows(rows)
            self.status_bar.showMessage(f"Topp kunder (faktura) beregnet for N={topn}.")
            return

        if self._ar_agg is None or self._ar_agg.empty:
            QMessageBox.information(
                self,
                "Ingen reskontro",
                "Fant ikke kunde-ID på reskontro (1500–1599) i SAF-T.",
            )
            return
        data = self._ar_agg.copy()
        data["Kundenavn"] = data["CustomerID"].map(self._cust_map).fillna("")
        data["OmsetningEksMva"] = data["AR_Debit"]
        data["Fakturaer"] = 0
        data = data.sort_values("AR_Debit", ascending=False).head(topn)
        rows = [
            (
                str(row["CustomerID"]),
                str(row["Kundenavn"] or ""),
                int(row.get("Fakturaer", 0) or 0),
                float(row["OmsetningEksMva"]),
            )
            for _, row in data.iterrows()
        ]
        self._salg_page.set_rows(rows)
        self.status_bar.showMessage(f"Topp kunder (reskontro) beregnet for N={topn}.")

    def on_brreg(self) -> None:
        if not self._header or not self._header.orgnr:
            QMessageBox.warning(self, "Mangler organisasjonsnummer", "SAF-T-headeren mangler org.nr.")
            return
        orgnr = self._header.orgnr
        try:
            js = fetch_brreg(orgnr)
        except Exception as exc:
            QMessageBox.critical(self, "Feil ved henting", str(exc))
            return

        self._brreg_json = js
        self._sammenstilling_page.set_json(js)
        self._brreg_map = map_brreg_metrics(js)

        rows: List[Tuple[str, str]] = []

        def add_row(label: str, prefer_keys: Iterable[str]) -> None:
            hit = find_first_by_exact_endkey(
                js,
                prefer_keys,
                disallow_contains=["egenkapitalOgGjeld"] if "sumEgenkapital" in prefer_keys else None,
            )
            if not hit and "sumEiendeler" in prefer_keys:
                hit = find_first_by_exact_endkey(js, ["sumEgenkapitalOgGjeld"])
            rows.append((label, f"{hit[0]} = {hit[1]}" if hit else "—"))

        add_row("Eiendeler (UB)", ["sumEiendeler"])
        add_row("Egenkapital (UB)", ["sumEgenkapital"])
        add_row("Gjeld (UB)", ["sumGjeld"])
        add_row("Driftsinntekter", ["driftsinntekter", "sumDriftsinntekter", "salgsinntekter"])
        add_row("EBIT", ["driftsresultat", "ebit", "driftsresultatFoerFinans"])
        add_row("Årsresultat", ["arsresultat", "resultat", "resultatEtterSkatt"])

        self._sammenstilling_page.set_mapping(rows)

        if self._saft_summary and self._brreg_map:
            cmp_rows: List[Tuple[str, str, str, str]] = []

            def add_cmp(label: str, saf_v: Optional[float], key: str) -> None:
                br_v = self._brreg_map.get(key) if self._brreg_map else None
                cmp_rows.append((label, format_currency(saf_v), format_currency(br_v), format_difference(saf_v, br_v)))

            add_cmp("Driftsinntekter", self._saft_summary.get("driftsinntekter"), "driftsinntekter")
            add_cmp("EBIT", self._saft_summary.get("ebit"), "ebit")
            add_cmp("Årsresultat", self._saft_summary.get("arsresultat"), "arsresultat")
            add_cmp("Eiendeler (UB)", self._saft_summary.get("eiendeler_UB_brreg"), "eiendeler_UB")
            add_cmp("Egenkapital (UB)", self._saft_summary.get("egenkapital_UB"), "egenkapital_UB")
            add_cmp("Gjeld (UB)", self._saft_summary.get("gjeld_UB_brreg"), "gjeld_UB")
            self._sammenstilling_page.set_comparison(cmp_rows)

        self.status_bar.showMessage("Data fra Regnskapsregisteret hentet.")

    def on_export(self) -> None:
        if self._saft_df is None:
            QMessageBox.warning(self, "Ingen data", "Last inn SAF-T før eksport.")
            return
        out, _ = QFileDialog.getSaveFileName(
            self,
            "Eksporter rapport",
            "SAFT_rapport.xlsx",
            "Excel (*.xlsx)",
        )
        if not out:
            return
        try:
            with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
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
        except Exception as exc:
            QMessageBox.critical(self, "Feil ved eksport", str(exc))
            return
        self.status_bar.showMessage(f"Eksportert: {out}")

    # endregion


def create_app() -> Tuple[QApplication, NordlysWindow]:
    """Oppretter QApplication og hovedvindu."""

    app = QApplication.instance() or QApplication(sys.argv)
    window = NordlysWindow()
    return app, window


def run() -> None:
    """Starter PySide6-applikasjonen."""

    try:
        app, window = create_app()
        window.show()
        sys.exit(app.exec())
    except Exception as exc:  # pragma: no cover - fallback dersom Qt ikke starter
        print("Kritisk feil:", exc, file=sys.stderr)
        sys.exit(1)


__all__ = ["NordlysWindow", "create_app", "run"]
