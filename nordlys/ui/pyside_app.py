"""PySide6-basert GUI for Nordlys SAF-T analysator."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:  # pragma: no cover - eksponeres kun ved manglende avhengighet
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFrame,
        QFormLayout,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QScrollArea,
        QSizePolicy,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
        QHeaderView,
        QAbstractItemView,
    )
except ImportError as exc:  # pragma: no cover - avhenger av miljøet
    _PYSIDE_AVAILABLE = False
    _IMPORT_ERROR = exc
else:
    _PYSIDE_AVAILABLE = True
    _IMPORT_ERROR = None

from ..constants import APP_TITLE
from ..saft import (
    SaftHeader,
    extract_ar_from_gl,
    extract_sales_taxbase_by_customer,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saft_header,
    parse_saldobalanse,
)
from ..brreg import fetch_brreg, map_brreg_metrics
from ..utils import format_currency, format_difference


@dataclass(frozen=True)
class NavItem:
    """Representerer ett element i navigasjonsmenyen."""

    key: str
    title: str
    subtitle: str | None = None
    children: Tuple["NavItem", ...] = ()

    def iter_flat(self) -> Iterable["NavItem"]:
        yield self
        for child in self.children:
            yield from child.iter_flat()


NAV_STRUCTURE: Tuple[NavItem, ...] = (
    NavItem(key="analysis", title="SAF-T analyse", subtitle="Importer filer og nøkkeltall"),
    NavItem(key="dashboard", title="Dashboard", subtitle="Overblikk"),
    NavItem(
        key="planning",
        title="Planlegging",
        subtitle="Forbered revisjonsløpet",
        children=(
            NavItem(key="planning_ib", title="Kontroll IB"),
            NavItem(key="planning_materiality", title="Vesentlighetsvurdering"),
            NavItem(key="planning_analysis", title="Regnskapsanalyse"),
            NavItem(key="planning_compilation", title="Sammenstillingsanalyse"),
        ),
    ),
    NavItem(
        key="audit",
        title="Revisjon",
        subtitle="Detaljtester",
        children=(
            NavItem(key="audit_purchases", title="Innkjøp og leverandørgjeld"),
            NavItem(key="audit_payroll", title="Lønn"),
            NavItem(key="audit_cost", title="Kostnad"),
            NavItem(key="audit_assets", title="Driftsmidler"),
            NavItem(key="audit_finance", title="Finans og likvid"),
            NavItem(key="audit_inventory", title="Varelager og varekjøp"),
            NavItem(key="audit_sales", title="Salg og kundefordringer"),
            NavItem(key="audit_vat", title="MVA"),
        ),
    ),
)


if _PYSIDE_AVAILABLE:

    SUMMARY_FIELDS: Tuple[Tuple[str, str], ...] = (
        ("driftsinntekter", "Driftsinntekter"),
        ("varekostnad", "Varekostnad"),
        ("lonn", "Lønn"),
        ("andre_drift", "Andre driftskostnader"),
        ("ebitda", "EBITDA"),
        ("ebit", "EBIT"),
        ("finans_netto", "Finans netto"),
        ("ebt", "Resultat før skatt"),
        ("arsresultat", "Årsresultat"),
        ("eiendeler_UB", "Eiendeler (UB)"),
        ("egenkapital_UB", "Egenkapital (UB)"),
        ("gjeld_UB", "Gjeld (UB)"),
    )


    @dataclass
    class AnalysisState:
        """Holder resultatene fra sist lastede SAF-T fil."""

        path: Path
        header: SaftHeader
        trial_balance: pd.DataFrame
        summary: Dict[str, float]
        customers: Dict[str, str]
        sales_by_customer: pd.DataFrame
        ar_by_customer: pd.DataFrame
        top_customers: pd.DataFrame
        brreg_json: Optional[Dict[str, object]] = None
        brreg_metrics: Optional[Dict[str, Optional[float]]] = None

    class InfoCard(QFrame):
        """Visuell kortkomponent brukt på dashbordet."""

        def __init__(self, title: str, value: str, subtitle: str = "", badge: str | None = None) -> None:
            super().__init__()
            self.setObjectName("InfoCard")
            layout = QVBoxLayout(self)
            layout.setSpacing(6)
            layout.setContentsMargins(18, 18, 18, 18)

            title_label = QLabel(title)
            title_label.setObjectName("InfoCardTitle")
            layout.addWidget(title_label)

            value_label = QLabel(value)
            value_label.setObjectName("InfoCardValue")
            layout.addWidget(value_label)

            if badge:
                badge_label = QLabel(badge)
                badge_label.setObjectName("InfoCardBadge")
                badge_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                layout.addWidget(badge_label)

            if subtitle:
                subtitle_label = QLabel(subtitle)
                subtitle_label.setObjectName("InfoCardSubtitle")
                subtitle_label.setWordWrap(True)
                layout.addWidget(subtitle_label)

            layout.addStretch()


    class StatusPill(QLabel):
        """Farget status-etikett brukt i hovedinnholdet."""

        def __init__(self, text: str, variant: str = "info") -> None:
            super().__init__(text)
            self.setObjectName("StatusPill")
            self.setProperty("variant", variant)
            self.setAlignment(Qt.AlignCenter)
            self.setMargin(4)


    class DashboardPage(QWidget):
        """Hovedoversikten med nøkkeltall og anbefalinger."""

        def __init__(self) -> None:
            super().__init__()
            layout = QVBoxLayout(self)
            layout.setSpacing(24)
            layout.setContentsMargins(0, 0, 0, 0)

            header = QLabel("Dashboard")
            header.setObjectName("PageTitle")
            layout.addWidget(header)

            subheader = QLabel("Oppsummering av kapasitet, anbefalinger og status for pågående revisjoner.")
            subheader.setObjectName("PageSubtitle")
            subheader.setWordWrap(True)
            layout.addWidget(subheader)

            location_bar = QFrame()
            location_layout = QHBoxLayout(location_bar)
            location_layout.setContentsMargins(0, 0, 0, 0)
            location_layout.setSpacing(12)

            location_label = QLabel("Kontor")
            location_combo = QComboBox()
            location_combo.addItems(["Oslo", "Coppell Office", "Los Angeles Office"])
            location_combo.setCurrentIndex(0)
            location_combo.setMinimumWidth(200)

            location_layout.addWidget(location_label)
            location_layout.addWidget(location_combo)
            location_layout.addStretch()

            layout.addWidget(location_bar)

            info_row = QFrame()
            info_row_layout = QHBoxLayout(info_row)
            info_row_layout.setContentsMargins(0, 0, 0, 0)
            info_row_layout.setSpacing(18)

            occupancy_card = InfoCard(
                title="Anbefalt utnyttelse",
                value="39%",
                subtitle="Prognose viser at maksimal anbefalt utnyttelse ved dagens vaksinasjonsgrad er 47%.",
                badge="37 plasser ledig",
            )

            weeks_card = InfoCard(
                title="Anbefalinger",
                value="Neste tiltak",
                subtitle="Følg opp avvikende kunder og bekreft vaksinasjonskrav for ansatte i planlagte møter.",
            )

            compliance_card = InfoCard(
                title="Samsvar",
                value="84%",
                subtitle="Med dagens kapasitet er det forventet at 84% av arbeidsstasjonene kan benyttes.",
                badge="Stabilt",
            )

            for card in (occupancy_card, weeks_card, compliance_card):
                card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                info_row_layout.addWidget(card)

            layout.addWidget(info_row)

            detail_section = QFrame()
            detail_layout = QGridLayout(detail_section)
            detail_layout.setContentsMargins(0, 0, 0, 0)
            detail_layout.setHorizontalSpacing(18)
            detail_layout.setVerticalSpacing(18)

            forecast_card = self._build_forecast_card()
            office_card = self._build_office_card()
            detail_layout.addWidget(forecast_card, 0, 0)
            detail_layout.addWidget(office_card, 0, 1)

            layout.addWidget(detail_section)
            layout.addStretch()

        def _build_forecast_card(self) -> QWidget:
            card = QFrame()
            card.setObjectName("PanelCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(22, 22, 22, 22)
            layout.setSpacing(16)

            title = QLabel("Prognose og anbefalinger")
            title.setObjectName("PanelTitle")
            layout.addWidget(title)

            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(39)
            progress.setFormat("Nåværende kapasitetsutnyttelse: %p%")
            progress.setAlignment(Qt.AlignCenter)
            layout.addWidget(progress)

            layout.addWidget(StatusPill("Mulig", "warning"))
            layout.addWidget(StatusPill("Sannsynlig", "info"))
            layout.addWidget(StatusPill("Sikret", "success"))

            recommendation = QLabel(
                "Maksimal anbefalt utnyttelse ved nåværende vaksinasjonsgrad og krav til munnbind er 47% av plassen."
            )
            recommendation.setWordWrap(True)
            layout.addWidget(recommendation)

            return card

        def _build_office_card(self) -> QWidget:
            card = QFrame()
            card.setObjectName("PanelCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(22, 22, 22, 22)
            layout.setSpacing(18)

            title_row = QHBoxLayout()
            title = QLabel("Oslo-kontoret")
            title.setObjectName("PanelTitle")
            status = StatusPill("Status: 50%", "info")
            title_row.addWidget(title)
            title_row.addStretch()
            title_row.addWidget(status)

            layout.addLayout(title_row)

            details = [
                ("Delte pulter", "40"),
                ("Private kontorer", "9"),
                ("Ledige pulter", "37"),
                ("Regelverk", "Oppfylt"),
            ]
            for label_text, value_text in details:
                row = QHBoxLayout()
                label = QLabel(label_text)
                value = QLabel(value_text)
                value.setObjectName("MutedValue")
                row.addWidget(label)
                row.addStretch()
                row.addWidget(value)
                layout.addLayout(row)

            guideline = QLabel(
                "Følg opp at alle ansatte fullfører egenmelding før fysisk oppmøte. Prioriter kunder med høy risiko."
            )
            guideline.setWordWrap(True)
            layout.addWidget(guideline)

            button_row = QHBoxLayout()
            button_row.addStretch()
            button = QPushButton("Åpne detaljvisning")
            button_row.addWidget(button)
            layout.addLayout(button_row)

            return card


    class PlaceholderPage(QWidget):
        """En enkel side som beskriver hva brukeren finner under hvert område."""

        def __init__(self, title: str, description: str, actions: List[str] | None = None) -> None:
            super().__init__()
            layout = QVBoxLayout(self)
            layout.setSpacing(18)
            layout.setContentsMargins(0, 0, 0, 0)

            header = QLabel(title)
            header.setObjectName("PageTitle")
            layout.addWidget(header)

            desc_label = QLabel(description)
            desc_label.setObjectName("PageSubtitle")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

            if actions:
                for action in actions:
                    bullet = QLabel(f"• {action}")
                    bullet.setObjectName("BulletText")
                    bullet.setWordWrap(True)
                    layout.addWidget(bullet)

            layout.addStretch()


    class AnalysisPage(QWidget):
        """Side for å importere SAF-T og kjøre analyser."""

        def __init__(self, main_window: "MainWindow") -> None:
            super().__init__()
            self._main_window = main_window
            self._state: Optional[AnalysisState] = None

            layout = QVBoxLayout(self)
            layout.setSpacing(24)
            layout.setContentsMargins(0, 0, 0, 0)

            title = QLabel("SAF-T analyse")
            title.setObjectName("PageTitle")
            layout.addWidget(title)

            subtitle = QLabel(
                "Importer SAF-T filer, hent nøkkeltall og sammenlign mot Regnskapsregisteret."
            )
            subtitle.setObjectName("PageSubtitle")
            subtitle.setWordWrap(True)
            layout.addWidget(subtitle)

            action_row = QHBoxLayout()
            self.open_button = QPushButton("Åpne SAF-T-fil…")
            self.open_button.clicked.connect(self._main_window.prompt_open_saft)
            action_row.addWidget(self.open_button)

            self.brreg_button = QPushButton("Hent Brreg-data")
            self.brreg_button.clicked.connect(self._main_window.fetch_brreg_data)
            action_row.addWidget(self.brreg_button)

            self.export_button = QPushButton("Eksporter analyse…")
            self.export_button.clicked.connect(self._main_window.export_analysis)
            action_row.addWidget(self.export_button)

            action_row.addStretch()
            layout.addLayout(action_row)

            self.file_value = QLabel("Ingen fil valgt")
            self.file_value.setObjectName("BulletText")
            layout.addWidget(self.file_value)

            header_card = QFrame()
            header_card.setObjectName("PanelCard")
            header_layout = QVBoxLayout(header_card)
            header_layout.setContentsMargins(22, 22, 22, 22)
            header_layout.setSpacing(12)

            header_title = QLabel("Metadata fra SAF-T")
            header_title.setObjectName("PanelTitle")
            header_layout.addWidget(header_title)

            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignLeft)
            self.header_labels: Dict[str, QLabel] = {}
            for key, label_text in [
                ("company_name", "Selskap"),
                ("orgnr", "Organisasjonsnummer"),
                ("fiscal_year", "Regnskapsår"),
                ("period_start", "Periode start"),
                ("period_end", "Periode slutt"),
                ("file_version", "SAF-T versjon"),
            ]:
                label = QLabel("—")
                label.setObjectName("BulletText")
                form.addRow(f"{label_text}:", label)
                self.header_labels[key] = label
            header_layout.addLayout(form)

            self.brreg_status = QLabel("Ingen Brreg-data hentet ennå.")
            self.brreg_status.setObjectName("BulletText")
            self.brreg_status.setWordWrap(True)
            header_layout.addWidget(self.brreg_status)

            layout.addWidget(header_card)

            summary_card = QFrame()
            summary_card.setObjectName("PanelCard")
            summary_layout = QVBoxLayout(summary_card)
            summary_layout.setContentsMargins(22, 22, 22, 22)
            summary_layout.setSpacing(12)

            summary_title = QLabel("Nøkkeltall")
            summary_title.setObjectName("PanelTitle")
            summary_layout.addWidget(summary_title)

            self.summary_table = QTableWidget(0, 4)
            self.summary_table.setHorizontalHeaderLabels([
                "Nøkkeltall",
                "SAF-T",
                "Brreg",
                "Differanse",
            ])
            self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.summary_table.verticalHeader().setVisible(False)
            self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.summary_table.setSelectionMode(QAbstractItemView.NoSelection)
            summary_layout.addWidget(self.summary_table)

            layout.addWidget(summary_card)

            top_card = QFrame()
            top_card.setObjectName("PanelCard")
            top_layout = QVBoxLayout(top_card)
            top_layout.setContentsMargins(22, 22, 22, 22)
            top_layout.setSpacing(12)

            top_title = QLabel("Toppkunder")
            top_title.setObjectName("PanelTitle")
            top_layout.addWidget(top_title)

            self.top_table = QTableWidget(0, 5)
            self.top_table.setHorizontalHeaderLabels([
                "Kunde",
                "Kunde-ID",
                "Omsetning eks mva",
                "Fakturaer",
                "Reskontro netto",
            ])
            self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for column in range(1, 5):
                self.top_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
            self.top_table.verticalHeader().setVisible(False)
            self.top_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.top_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.top_table.setSelectionMode(QAbstractItemView.NoSelection)
            top_layout.addWidget(self.top_table)

            layout.addWidget(top_card)
            layout.addStretch()

            self.set_state(None)

        def _table_item(self, text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            return item

        def set_state(self, state: Optional[AnalysisState]) -> None:
            self._state = state
            has_state = state is not None
            self.brreg_button.setEnabled(bool(has_state and (state.header.orgnr or "").strip()))
            self.export_button.setEnabled(bool(has_state))

            if state is None:
                self.file_value.setText("Ingen fil valgt")
                for label in self.header_labels.values():
                    label.setText("—")
                self.brreg_status.setText("Ingen Brreg-data hentet ennå.")
                self.summary_table.setRowCount(0)
                self.top_table.setRowCount(0)
                return

            self.file_value.setText(str(state.path))
            header_values = {
                "company_name": state.header.company_name or "—",
                "orgnr": state.header.orgnr or "—",
                "fiscal_year": state.header.fiscal_year or "—",
                "period_start": state.header.period_start or "—",
                "period_end": state.header.period_end or "—",
                "file_version": state.header.file_version or "—",
            }
            for key, value in header_values.items():
                self.header_labels[key].setText(value)

            if state.brreg_metrics:
                self.brreg_status.setText("Brreg-data hentet – sammenligning vises i tabellen.")
            else:
                self.brreg_status.setText("Brreg-data er ikke hentet. Klikk på \"Hent Brreg-data\" for å sammenligne.")

            self.summary_table.setRowCount(len(SUMMARY_FIELDS))
            for row, (key, label) in enumerate(SUMMARY_FIELDS):
                saft_value = state.summary.get(key)
                brreg_value = (state.brreg_metrics or {}).get(key) if state.brreg_metrics else None
                self.summary_table.setItem(row, 0, self._table_item(label))
                self.summary_table.setItem(row, 1, self._table_item(format_currency(saft_value)))
                self.summary_table.setItem(row, 2, self._table_item(format_currency(brreg_value)))
                diff_text = (
                    format_difference(saft_value, brreg_value)
                    if saft_value is not None and brreg_value is not None
                    else "—"
                )
                self.summary_table.setItem(row, 3, self._table_item(diff_text))

            top_df = state.top_customers
            display_df = top_df.head(15) if not top_df.empty else top_df
            self.top_table.setRowCount(len(display_df))
            for row, (_, record) in enumerate(display_df.iterrows()):
                navn = (record.get("Navn") or "").strip() or "(uten navn)"
                customer_id = str(record.get("CustomerID") or "")
                omsetning = format_currency(record.get("OmsetningEksMva"))
                fakturaer = record.get("Fakturaer")
                fakturaer_text = "—"
                if pd.notna(fakturaer):
                    try:
                        fakturaer_text = str(int(fakturaer))
                    except Exception:
                        fakturaer_text = str(fakturaer)
                ar_netto = format_currency(record.get("AR_Netto"))
                values = [navn, customer_id, omsetning, fakturaer_text, ar_netto]
                for col, value in enumerate(values):
                    self.top_table.setItem(row, col, self._table_item(value))


    class NavigationPanel(QFrame):
        """Venstremeny med fasestruktur."""

        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("NavigationPanel")
            layout = QVBoxLayout(self)
            layout.setSpacing(16)
            layout.setContentsMargins(20, 24, 20, 24)

            title = QLabel(APP_TITLE)
            title.setObjectName("AppTitle")
            title.setWordWrap(True)
            layout.addWidget(title)

            subtitle = QLabel("Revisjonsplattform")
            subtitle.setObjectName("AppSubtitle")
            layout.addWidget(subtitle)

            layout.addSpacing(6)

            self.tree = QTreeWidget()
            self.tree.setHeaderHidden(True)
            self.tree.setObjectName("NavigationTree")
            self.tree.setFocusPolicy(Qt.NoFocus)
            self.tree.setIndentation(14)
            layout.addWidget(self.tree, stretch=1)

            layout.addStretch()


    class MainWindow(QMainWindow):
        """Hovedvindu for PySide6-grensesnittet."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(APP_TITLE)
            self.resize(1280, 860)
            self.setMinimumSize(1100, 760)

            self._analysis_state: Optional[AnalysisState] = None
            self._analysis_page: Optional[AnalysisPage] = None

            self._setup_palette()
            self._build_layout()

        def _setup_palette(self) -> None:
            font = QFont()
            font.setPointSize(10)
            self.setFont(font)
            self.setStyleSheet(
                """
                QMainWindow { background-color: #f5f7fb; }
                QLabel#AppTitle { font-size: 20px; font-weight: 700; color: #1c2a4b; }
                QLabel#AppSubtitle { font-size: 12px; color: #6b7a99; }
                QFrame#NavigationPanel { background: #ffffff; border-right: 1px solid #e2e6f0; }
                QTreeWidget#NavigationTree { background: transparent; }
                QTreeWidget#NavigationTree::item { padding: 8px 4px; margin: 2px 0; border-radius: 8px; }
                QTreeWidget#NavigationTree::item:selected { background: #eef2ff; color: #3546a5; }
                QTreeWidget#NavigationTree::item:hover { background: #f2f4fa; }
                QLabel#PageTitle { font-size: 24px; font-weight: 600; color: #1c2a4b; }
                QLabel#PageSubtitle { font-size: 13px; color: #60708f; }
                QLabel#BulletText { font-size: 13px; color: #3b4660; }
                QFrame#InfoCard { background: #ffffff; border: 1px solid #e3e7ef; border-radius: 14px; }
                QLabel#InfoCardTitle { font-size: 14px; color: #5e6a85; font-weight: 600; }
                QLabel#InfoCardValue { font-size: 28px; font-weight: 700; color: #1b2559; }
                QLabel#InfoCardBadge { font-size: 12px; color: #425488; background: #eef2ff; padding: 4px 8px; border-radius: 10px; }
                QLabel#InfoCardSubtitle { font-size: 12px; color: #697799; }
                QFrame#PanelCard { background: #ffffff; border: 1px solid #e3e7ef; border-radius: 18px; }
                QLabel#PanelTitle { font-size: 16px; font-weight: 600; color: #1c2a4b; }
                QLabel#MutedValue { color: #4a5a7c; font-weight: 600; }
                QLabel#StatusPill[variant="info"] { background: #e6f0ff; color: #3454d1; border-radius: 12px; padding: 4px 12px; }
                QLabel#StatusPill[variant="warning"] { background: #fff4e5; color: #c76b00; border-radius: 12px; padding: 4px 12px; }
                QLabel#StatusPill[variant="success"] { background: #e5f8f0; color: #1f8a5f; border-radius: 12px; padding: 4px 12px; }
                QPushButton { background: #4055d6; color: white; border-radius: 10px; padding: 10px 18px; font-weight: 600; }
                QPushButton:hover { background: #2f46c1; }
                QPushButton:pressed { background: #263ca6; }
                QComboBox { padding: 8px 12px; border: 1px solid #d5dae3; border-radius: 10px; background: white; }
                QProgressBar { border-radius: 12px; background: #edf1fb; padding: 4px; color: #4055d6; }
                QProgressBar::chunk { border-radius: 10px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4c6ef5, stop:1 #5f87ff); }
                """
            )

        def _build_layout(self) -> None:
            central = QWidget()
            root_layout = QHBoxLayout(central)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)

            self.nav_panel = NavigationPanel()
            self.nav_panel.setFixedWidth(280)
            root_layout.addWidget(self.nav_panel)

            self.stack = QStackedWidget()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setObjectName("MainScrollArea")
            scroll.setStyleSheet("QScrollArea#MainScrollArea { background: transparent; }")

            self._pages_container = QWidget()
            self._pages_layout = QVBoxLayout(self._pages_container)
            self._pages_layout.setContentsMargins(36, 36, 36, 36)
            self._pages_layout.setSpacing(0)

            scroll.setWidget(self._pages_container)
            self.stack.addWidget(scroll)
            root_layout.addWidget(self.stack, stretch=1)

            self.setCentralWidget(central)

            self._populate_navigation()
            self._build_pages()
            self.nav_panel.tree.itemSelectionChanged.connect(self._handle_selection_change)
            # Velg første element
            first_item = self.nav_panel.tree.topLevelItem(0)
            if first_item is not None:
                self.nav_panel.tree.setCurrentItem(first_item)

        def _populate_navigation(self) -> None:
            tree = self.nav_panel.tree
            tree.clear()
            for nav_item in NAV_STRUCTURE:
                parent = self._create_tree_item(nav_item)
                tree.addTopLevelItem(parent)
                if nav_item.children:
                    for child in nav_item.children:
                        parent.addChild(self._create_tree_item(child))
                    parent.setExpanded(True)

        def _create_tree_item(self, item: NavItem) -> QTreeWidgetItem:
            tree_item = QTreeWidgetItem([item.title])
            tree_item.setData(0, Qt.UserRole, item.key)
            if item.subtitle:
                tree_item.setToolTip(0, item.subtitle)
            return tree_item

        def _build_pages(self) -> None:
            # StackedWidget inneholder kun ett scroll-område; vi bytter ut innholdet dynamisk.
            while self._pages_layout.count():
                item = self._pages_layout.takeAt(0)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.deleteLater()

            self._page_widgets: Dict[str, QWidget] = {}
            for item in (nav_item for nav_group in NAV_STRUCTURE for nav_item in nav_group.iter_flat()):
                widget = self._create_page_for_item(item)
                widget.hide()
                self._page_widgets[item.key] = widget
                self._pages_layout.addWidget(widget)
            self._pages_layout.addStretch()

        def _create_page_for_item(self, item: NavItem) -> QWidget:
            if item.key == "analysis":
                page = AnalysisPage(self)
                self._analysis_page = page
                if self._analysis_state is not None:
                    page.set_state(self._analysis_state)
                return page
            if item.key == "dashboard":
                return DashboardPage()

            descriptions = {
                "analysis": "Importer SAF-T filer, kjør analyser og eksporter resultater.",
                "planning": "Få oversikten over hvilke forberedelser som gjenstår og fordel arbeidet i teamet.",
                "planning_ib": "Verifiser inngående balanser, sammenlign mot foregående periode og dokumenter avvik.",
                "planning_materiality": "Dokumenter vesentlighetsgrenser, delberegninger og revisjonsstrategi.",
                "planning_analysis": "Analyser hovedtall og nøkkeltall basert på importert SAF-T og eksterne kilder.",
                "planning_compilation": "Koble sammen analyser og kommenter avvik før endelig plan godkjennes.",
                "audit": "Oppfølging av detaljtester og revisjonshandlinger for hver prosess.",
                "audit_purchases": "Utfør kontrollhandlinger på leverandørgjeld, avstem reskontro og sjekk avvik.",
                "audit_payroll": "Analysér lønnsgrunnlag, feriepenger og arbeidsgiveravgift mot regnskapet.",
                "audit_cost": "Vurder kostnadskontoer, periodiseringer og uvanlige transaksjoner.",
                "audit_assets": "Følg opp investeringer, avskrivninger og avgang i anleggsmidler.",
                "audit_finance": "Analyser kontantstrøm, låneavtaler og valutaeksponering.",
                "audit_inventory": "Kartlegg varelageret, vurder nedskrivningsbehov og vareforbruk.",
                "audit_sales": "Test salgsprosess, kundefordringer og kredittstyring.",
                "audit_vat": "Avstem MVA-grunnlag, satsbruk og rapporteringsfrister.",
            }
            actions = {
                "planning": [
                    "Opprett revisjonsplan og fordel ansvar",
                    "Importer relevante datasett (SAF-T, ekstern data)",
                    "Gjør klar tidslinje med milepæler",
                ],
                "audit": [
                    "Se status for hver prosess",
                    "Tildel arbeidsoppgaver og overvåk progresjon",
                    "Last opp dokumentasjon for utvalgte tester",
                ],
            }
            return PlaceholderPage(item.title, descriptions.get(item.key, ""), actions.get(item.key))

        def _handle_selection_change(self) -> None:
            items = self.nav_panel.tree.selectedItems()
            if not items:
                return
            key = items[0].data(0, Qt.UserRole)
            widget = self._page_widgets.get(key)
            if not widget:
                return
            for page in self._page_widgets.values():
                page.setVisible(False)
            widget.setVisible(True)
            widget.raise_()

        def prompt_open_saft(self) -> None:
            """Viser en fil-dialog og laster SAF-T filen brukeren velger."""

            path_str, _ = QFileDialog.getOpenFileName(
                self,
                "Velg SAF-T fil",
                str(self._analysis_state.path.parent) if self._analysis_state else str(Path.home()),
                "SAF-T filer (*.xml *.txt);;Alle filer (*.*)",
            )
            if not path_str:
                return
            self._load_saft_file(Path(path_str))

        def _load_saft_file(self, path: Path) -> None:
            try:
                tree = ET.parse(path)
                root = tree.getroot()
            except Exception as exc:  # pragma: no cover - UI interaksjon
                QMessageBox.critical(self, "Kunne ikke åpne SAF-T", f"Feil ved lesing av filen: {exc}")
                return

            header = parse_saft_header(root)
            trial_balance = parse_saldobalanse(root)
            summary = ns4102_summary_from_tb(trial_balance)
            customers = parse_customers(root)

            sales_df = extract_sales_taxbase_by_customer(root)
            if not sales_df.empty:
                sales_df = sales_df.copy()
                sales_df["CustomerID"] = sales_df["CustomerID"].astype(str)
                sales_df["Navn"] = sales_df["CustomerID"].map(lambda cid: customers.get(cid, ""))
                sales_df.sort_values("OmsetningEksMva", ascending=False, inplace=True)
            else:
                sales_df = pd.DataFrame(columns=["CustomerID", "Navn", "OmsetningEksMva", "Fakturaer"])

            ar_df = extract_ar_from_gl(root)
            if not ar_df.empty:
                ar_df = ar_df.copy()
                ar_df["CustomerID"] = ar_df["CustomerID"].astype(str)
                ar_df["Navn"] = ar_df["CustomerID"].map(lambda cid: customers.get(cid, ""))
                ar_df.sort_values("AR_Netto", ascending=False, inplace=True)
            else:
                ar_df = pd.DataFrame(columns=["CustomerID", "Navn", "AR_Netto"])

            if sales_df.empty and ar_df.empty:
                top_customers = pd.DataFrame(
                    columns=["CustomerID", "Navn", "OmsetningEksMva", "Fakturaer", "AR_Netto"]
                )
            else:
                top_customers = pd.merge(
                    sales_df[["CustomerID", "Navn", "OmsetningEksMva", "Fakturaer"]],
                    ar_df[["CustomerID", "AR_Netto"]],
                    on="CustomerID",
                    how="outer",
                )
                if "Navn_x" in top_customers.columns:
                    top_customers["Navn"] = top_customers["Navn_x"].fillna(top_customers.get("Navn_y"))
                    top_customers.drop(columns=[col for col in ["Navn_x", "Navn_y"] if col in top_customers], inplace=True)
                top_customers["Navn"] = top_customers["Navn"].fillna("")
                top_customers["OmsetningEksMva"] = top_customers["OmsetningEksMva"].fillna(0.0)
                if "Fakturaer" in top_customers:
                    top_customers["Fakturaer"] = top_customers["Fakturaer"].fillna(0)
                top_customers["AR_Netto"] = top_customers["AR_Netto"].fillna(0.0)
                top_customers.sort_values(
                    ["OmsetningEksMva", "AR_Netto"], ascending=[False, False], inplace=True
                )

            self._analysis_state = AnalysisState(
                path=path,
                header=header,
                trial_balance=trial_balance,
                summary=summary,
                customers=customers,
                sales_by_customer=sales_df,
                ar_by_customer=ar_df,
                top_customers=top_customers,
                brreg_json=None,
                brreg_metrics=None,
            )

            if self._analysis_page is not None:
                self._analysis_page.set_state(self._analysis_state)

            QMessageBox.information(self, "SAF-T importert", f"Lastet {path.name}")

        def fetch_brreg_data(self) -> None:
            if not self._analysis_state:
                QMessageBox.warning(self, "Ingen SAF-T", "Last inn en SAF-T fil først.")
                return

            orgnr = (self._analysis_state.header.orgnr or "").strip()
            digits = "".join(ch for ch in orgnr if ch.isdigit())
            if not digits:
                QMessageBox.warning(
                    self,
                    "Organisasjonsnummer mangler",
                    "SAF-T filen inneholder ikke organisasjonsnummer. Oppdater filen eller hent manuelt.",
                )
                return

            try:
                brreg_json = fetch_brreg(digits)
            except Exception as exc:  # pragma: no cover - nettverkskall
                QMessageBox.critical(self, "Brreg", f"Kunne ikke hente data fra Brreg: {exc}")
                return

            metrics = map_brreg_metrics(brreg_json)
            self._analysis_state.brreg_json = brreg_json
            self._analysis_state.brreg_metrics = metrics

            if self._analysis_page is not None:
                self._analysis_page.set_state(self._analysis_state)

            QMessageBox.information(self, "Brreg", "Brreg-data hentet og nøkkeltall oppdatert.")

        def export_analysis(self) -> None:
            if not self._analysis_state:
                QMessageBox.warning(self, "Ingen SAF-T", "Last inn en SAF-T fil før du eksporterer.")
                return

            default_name = self._analysis_state.path.with_suffix(".xlsx")
            path_str, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Lagre analyse",
                str(default_name),
                "Excel-arbeidsbok (*.xlsx);;CSV (*.csv)",
            )
            if not path_str:
                return

            output_path = Path(path_str)
            if output_path.suffix.lower() not in {".xlsx", ".csv"}:
                if "csv" in selected_filter.lower():
                    output_path = output_path.with_suffix(".csv")
                else:
                    output_path = output_path.with_suffix(".xlsx")

            try:
                if output_path.suffix.lower() == ".csv":
                    self._analysis_state.trial_balance.to_csv(output_path, index=False)
                else:
                    with pd.ExcelWriter(output_path) as writer:
                        self._analysis_state.trial_balance.to_excel(writer, sheet_name="Saldobalanse", index=False)
                        summary_rows = [
                            {
                                "Nøkkeltall": label,
                                "SAF-T": self._analysis_state.summary.get(key),
                                "Brreg": (self._analysis_state.brreg_metrics or {}).get(key),
                            }
                            for key, label in SUMMARY_FIELDS
                        ]
                        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Nøkkeltall", index=False)
                        self._analysis_state.sales_by_customer.to_excel(
                            writer, sheet_name="Omsetning_kunder", index=False
                        )
                        self._analysis_state.ar_by_customer.to_excel(
                            writer, sheet_name="Reskontro_kunder", index=False
                        )
                        if not self._analysis_state.top_customers.empty:
                            self._analysis_state.top_customers.to_excel(
                                writer, sheet_name="Toppkunder", index=False
                            )
                        if self._analysis_state.brreg_json:
                            pd.json_normalize(self._analysis_state.brreg_json).to_excel(
                                writer, sheet_name="Brreg_raw", index=False
                            )
            except Exception as exc:  # pragma: no cover - filsysteminteraksjon
                QMessageBox.critical(self, "Eksport", f"Kunne ikke lagre filen: {exc}")
                return

            QMessageBox.information(self, "Eksport", f"Analysen er lagret til {output_path}")


    def run() -> None:
        """Starter PySide6-applikasjonen."""

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        app.exec()


else:

    class MainWindow:  # pragma: no cover - brukes ikke uten PySide
        """Plassholder når PySide6 mangler."""

        pass


    def run() -> None:  # pragma: no cover - avhenger av miljøet
        """Informerer brukeren om manglende PySide6."""

        raise ImportError(
            "PySide6 er påkrevd for Nordlys sitt grensesnitt. Installer pakken med 'pip install PySide6'."
        ) from _IMPORT_ERROR
