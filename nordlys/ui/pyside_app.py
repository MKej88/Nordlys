"""PySide6-basert GUI for Nordlys SAF-T analysator."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
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


class NavigationIds:
    """Konstanter for side-identifikatorer."""

    DASHBOARD = "dashboard"
    PLAN_KONTROLL = "plan_kontroll"
    PLAN_VESENTLIGHET = "plan_vesentlig"
    PLAN_REGNSKAP = "plan_regnskap"
    PLAN_SAMMENSTILLING = "plan_sammenstilling"
    REV_INNKJOP = "rev_innkjop"
    REV_LONN = "rev_lonn"
    REV_KOSTNAD = "rev_kostnad"
    REV_DRIFT = "rev_driftsmidler"
    REV_FINANS = "rev_finans"
    REV_VARELAGER = "rev_varelager"
    REV_SALG = "rev_salg"
    REV_MVA = "rev_mva"


class MainWindow(QMainWindow):
    """Hovedapplikasjonen basert på PySide6."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1440, 900)
        self.setMinimumSize(1280, 780)

        # Datafelt
        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional[SaftHeader] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._cust_map: Dict[str, str] = {}
        self._sales_agg: Optional[pd.DataFrame] = None
        self._ar_agg: Optional[pd.DataFrame] = None

        # UI-elementer som må være tilgjengelige
        self.navigation: QTreeWidget
        self.stack: QStackedWidget
        self.page_map: Dict[str, QWidget] = {}
        self.lbl_company: QLabel
        self.lbl_orgnr: QLabel
        self.lbl_period: QLabel
        self.metric_labels: Dict[str, QLabel] = {}
        self.table_tb: QTableWidget
        self.table_ns: QTableWidget
        self.text_json: QTextEdit
        self.table_map: QTableWidget
        self.table_cmp: QTableWidget
        self.cmb_source: QComboBox
        self.spn_topn: QSpinBox
        self.table_top: QTableWidget
        self.btn_calc_top: QPushButton

        self._setup_style()
        self._create_ui()

    # region Oppsett
    def _setup_style(self) -> None:
        """Definerer applikasjonens overordnede stil."""

        font = QFont()
        font.setPointSize(10)
        app = QApplication.instance()
        if app is not None:
            app.setFont(font)
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #f5f7fb;
            }
            QTreeWidget {
                background-color: #0f1a2a;
                color: #f5f7fb;
                border: none;
                padding: 16px 8px;
            }
            QTreeWidget::item {
                height: 34px;
            }
            QTreeWidget::item:selected {
                background-color: #2d63ff;
                color: white;
            }
            QTreeWidget::item:hover {
                background-color: #1e2f49;
            }
            QToolBar {
                background-color: white;
                border: none;
                padding: 12px 18px;
                spacing: 18px;
            }
            QToolBar QToolButton {
                background-color: #2d63ff;
                border-radius: 8px;
                padding: 8px 16px;
                color: white;
                font-weight: 600;
            }
            QToolBar QToolButton:disabled {
                background-color: #6f7b91;
                color: rgba(255, 255, 255, 140);
            }
            QStatusBar {
                background-color: white;
                border-top: 1px solid #d9dfe8;
                padding: 6px 16px;
            }
            QGroupBox {
                border: 1px solid #d9dfe8;
                border-radius: 12px;
                margin-top: 18px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 14px;
                color: #334155;
                font-weight: 600;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #d9dfe8;
                border-radius: 10px;
                gridline-color: #e5e9f1;
                alternate-background-color: #f7f9fc;
                selection-background-color: #2d63ff;
                selection-color: white;
            }
            QLabel.metric-title {
                color: #6b7280;
                font-size: 14px;
            }
            QLabel.metric-value {
                color: #111827;
                font-size: 28px;
                font-weight: 700;
            }
            QTextEdit {
                border: 1px solid #d9dfe8;
                border-radius: 10px;
                background-color: white;
            }
            QPushButton.accent {
                background-color: #2d63ff;
                color: white;
                border-radius: 8px;
                padding: 8px 18px;
                font-weight: 600;
            }
            QPushButton.accent:disabled {
                background-color: #93a0bf;
                color: rgba(255, 255, 255, 180);
            }
            QComboBox, QSpinBox {
                border: 1px solid #d9dfe8;
                border-radius: 8px;
                padding: 6px 10px;
                background-color: white;
            }
            """
        )

    def _create_ui(self) -> None:
        """Setter opp verktøylinje, navigasjon og hovedinnhold."""

        # Verktøylinje
        toolbar = QToolBar("Hurtigtilgang", self)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        self.act_open = QAction("Åpne SAF-T …", self)
        self.act_open.triggered.connect(self.on_open)
        toolbar.addAction(self.act_open)

        self.act_brreg = QAction("Hent Regnskapsregisteret", self)
        self.act_brreg.setEnabled(False)
        self.act_brreg.triggered.connect(self.on_brreg)
        toolbar.addAction(self.act_brreg)

        self.act_export = QAction("Eksporter rapport", self)
        self.act_export.setEnabled(False)
        self.act_export.triggered.connect(self.on_export)
        toolbar.addAction(self.act_export)

        # Statuslinje
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage("Klar.")

        # Hovedoppsett
        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.navigation = QTreeWidget(central)
        self.navigation.setHeaderHidden(True)
        self.navigation.setIndentation(16)
        self.navigation.setMinimumWidth(240)
        self.navigation.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.navigation.itemSelectionChanged.connect(self._on_navigation_selection)

        nav_items = self._build_navigation()

        self.stack = QStackedWidget(central)
        self._create_pages()

        central_layout.addWidget(self.navigation)
        central_layout.addWidget(self.stack, 1)

        self.setCentralWidget(central)

        # Velg dashboard som standard
        self.navigation.setCurrentItem(nav_items[NavigationIds.DASHBOARD])

    def _build_navigation(self) -> Dict[str, QTreeWidgetItem]:
        """Oppretter navigasjonsstrukturen."""

        items: Dict[str, QTreeWidgetItem] = {}

        dashboard = QTreeWidgetItem(["Dashboard"])
        dashboard.setData(0, Qt.UserRole, NavigationIds.DASHBOARD)
        self.navigation.addTopLevelItem(dashboard)
        items[NavigationIds.DASHBOARD] = dashboard

        plan = QTreeWidgetItem(["Planlegging"])
        self.navigation.addTopLevelItem(plan)
        plan.setExpanded(True)

        for title, page_id in [
            ("Kontroll IB", NavigationIds.PLAN_KONTROLL),
            ("Vesentlighetsvurdering", NavigationIds.PLAN_VESENTLIGHET),
            ("Regnskapsanalyse", NavigationIds.PLAN_REGNSKAP),
            ("Sammenstillingsanalyse", NavigationIds.PLAN_SAMMENSTILLING),
        ]:
            child = QTreeWidgetItem([title])
            child.setData(0, Qt.UserRole, page_id)
            plan.addChild(child)
            items[page_id] = child

        revisjon = QTreeWidgetItem(["Revisjon"])
        self.navigation.addTopLevelItem(revisjon)
        revisjon.setExpanded(True)

        for title, page_id in [
            ("Innkjøp og leverandørgjeld", NavigationIds.REV_INNKJOP),
            ("Lønn", NavigationIds.REV_LONN),
            ("Kostnad", NavigationIds.REV_KOSTNAD),
            ("Driftsmidler", NavigationIds.REV_DRIFT),
            ("Finans og likvid", NavigationIds.REV_FINANS),
            ("Varelager og varekjøp", NavigationIds.REV_VARELAGER),
            ("Salg og kundefordringer", NavigationIds.REV_SALG),
            ("MVA", NavigationIds.REV_MVA),
        ]:
            child = QTreeWidgetItem([title])
            child.setData(0, Qt.UserRole, page_id)
            revisjon.addChild(child)
            items[page_id] = child

        return items

    def _create_pages(self) -> None:
        """Oppretter innholdssidene og registrerer dem i stacken."""

        self.page_map[NavigationIds.DASHBOARD] = self._create_dashboard_page()
        self.page_map[NavigationIds.PLAN_KONTROLL] = self._create_table_page(
            "Saldobalanse", "Kontroll av inngående balanse basert på SAF-T." , table_attr="table_tb"
        )
        self.page_map[NavigationIds.PLAN_VESENTLIGHET] = self._create_table_page(
            "Vesentlighetsvurdering", "NS 4102-oppsummering for å vurdere vesentlighet.", table_attr="table_ns"
        )
        self.page_map[NavigationIds.PLAN_REGNSKAP] = self._create_regnskapsanalyse_page()
        self.page_map[NavigationIds.PLAN_SAMMENSTILLING] = self._create_table_page(
            "Sammenstilling", "SAF-T mot Regnskapsregisteret for å identifisere avvik.", table_attr="table_cmp"
        )

        # Revisjonssider
        self.page_map[NavigationIds.REV_INNKJOP] = self._create_revision_placeholder(
            "Innkjøp og leverandørgjeld",
            "Fokus på leverandørreskontro, periodisering og avstemminger.",
        )
        self.page_map[NavigationIds.REV_LONN] = self._create_revision_placeholder(
            "Lønn",
            "Analysér lønnsjournaler, arbeidsgiveravgift og ansatte registrert i SAF-T.",
        )
        self.page_map[NavigationIds.REV_KOSTNAD] = self._create_revision_placeholder(
            "Kostnad",
            "Kartlegg driftskostnader og kontroller periodisering av vesentlige poster.",
        )
        self.page_map[NavigationIds.REV_DRIFT] = self._create_revision_placeholder(
            "Driftsmidler",
            "Overvåk investeringer, avskrivninger og salg av anleggsmidler.",
        )
        self.page_map[NavigationIds.REV_FINANS] = self._create_revision_placeholder(
            "Finans og likvid",
            "Vurder finansposter, kontantstrømmer og likviditetsreserve.",
        )
        self.page_map[NavigationIds.REV_VARELAGER] = self._create_revision_placeholder(
            "Varelager og varekjøp",
            "Analyser varelagerbevegelser og kontrollér varekostnad.",
        )
        self.page_map[NavigationIds.REV_SALG] = self._create_sales_page()
        self.page_map[NavigationIds.REV_MVA] = self._create_revision_placeholder(
            "MVA",
            "Følg opp MVA-oppgaver og kontroller at SAF-T samsvarer med innsendt rapportering.",
        )

        for page in self.page_map.values():
            self.stack.addWidget(page)

    def _create_dashboard_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(24, 24, 24, 24)
        header_layout.setSpacing(24)
        header_frame.setObjectName("dashboardHeader")
        header_frame.setStyleSheet(
            "#dashboardHeader { background-color: white; border-radius: 16px; border: 1px solid #d9dfe8; }"
        )

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)
        title = QLabel("Selskap")
        title.setStyleSheet("color: #6b7280; font-size: 14px;")
        self.lbl_company = QLabel("—")
        self.lbl_company.setStyleSheet("font-size: 22px; font-weight: 600; color: #111827;")
        self.lbl_orgnr = QLabel("Org.nr: –")
        self.lbl_orgnr.setStyleSheet("color: #374151; font-size: 16px;")
        self.lbl_period = QLabel("Periode: –")
        self.lbl_period.setStyleSheet("color: #374151; font-size: 16px;")
        info_layout.addWidget(title)
        info_layout.addWidget(self.lbl_company)
        info_layout.addWidget(self.lbl_orgnr)
        info_layout.addWidget(self.lbl_period)

        header_layout.addLayout(info_layout)
        header_layout.addStretch(1)

        layout.addWidget(header_frame)

        metrics_group = QGroupBox("Nøkkeltall")
        metrics_layout = QGridLayout(metrics_group)
        metrics_layout.setContentsMargins(24, 24, 24, 24)
        metrics_layout.setHorizontalSpacing(24)
        metrics_layout.setVerticalSpacing(16)

        for index, (key, label) in enumerate(
            [
                ("driftsinntekter", "Driftsinntekter"),
                ("ebit", "EBIT"),
                ("arsresultat", "Årsresultat"),
                ("eiendeler", "Eiendeler (UB)"),
                ("egenkapital", "Egenkapital (UB)"),
                ("balanse_diff", "Balanseavvik"),
            ]
        ):
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(4)
            title_label = QLabel(label)
            title_label.setObjectName(f"metric_title_{key}")
            title_label.setProperty("class", "metric-title")
            title_label.setStyleSheet("color: #6b7280; font-size: 14px;")
            value_label = QLabel("—")
            value_label.setObjectName(f"metric_value_{key}")
            value_label.setProperty("class", "metric-value")
            value_label.setStyleSheet("color: #111827; font-size: 28px; font-weight: 700;")
            container_layout.addWidget(title_label)
            container_layout.addWidget(value_label)
            metrics_layout.addWidget(container, index // 3, index % 3)
            self.metric_labels[key] = value_label

        layout.addWidget(metrics_group)
        layout.addStretch(1)

        return widget

    def _create_table_page(self, title: str, description: str, *, table_attr: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #6b7280; font-size: 14px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        table = self._create_table()
        setattr(self, table_attr, table)
        layout.addWidget(table, 1)

        return widget

    def _create_regnskapsanalyse_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title_label = QLabel("Regnskapsanalyse")
        title_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Detaljert innsyn i data fra Regnskapsregisteret samt mapping til SAF-T-nøkler."
        )
        desc_label.setStyleSheet("color: #6b7280; font-size: 14px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        splitter = QSplitter(Qt.Horizontal)
        self.text_json = QTextEdit()
        self.text_json.setReadOnly(True)
        self.text_json.setPlaceholderText("Last inn SAF-T og hent Regnskapsregisteret for å se data.")
        splitter.addWidget(self.text_json)

        self.table_map = self._create_table()
        splitter.addWidget(self.table_map)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter, 1)
        return widget

    def _create_sales_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title_label = QLabel("Salg og kundefordringer")
        title_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Utfør analyser på kunder ved hjelp av SAF-T (faktura) eller reskontrodata."
        )
        desc_label.setStyleSheet("color: #6b7280; font-size: 14px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        source_label = QLabel("Kilde:")
        source_label.setStyleSheet("color: #374151;")
        controls.addWidget(source_label)

        self.cmb_source = QComboBox()
        self.cmb_source.addItems(["faktura", "reskontro"])
        controls.addWidget(self.cmb_source)

        count_label = QLabel("Antall toppkunder:")
        count_label.setStyleSheet("color: #374151;")
        controls.addWidget(count_label)

        self.spn_topn = QSpinBox()
        self.spn_topn.setRange(1, 100)
        self.spn_topn.setValue(10)
        controls.addWidget(self.spn_topn)

        controls.addStretch(1)

        self.btn_calc_top = QPushButton("Beregn toppkunder")
        self.btn_calc_top.setProperty("class", "accent")
        self.btn_calc_top.setEnabled(False)
        self.btn_calc_top.clicked.connect(self.on_calc_top_customers)
        controls.addWidget(self.btn_calc_top)

        layout.addLayout(controls)

        self.table_top = self._create_table()
        layout.addWidget(self.table_top, 1)

        return widget

    def _create_revision_placeholder(self, title: str, description: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #6b7280; font-size: 15px;")
        layout.addWidget(desc_label)

        card = QFrame()
        card.setStyleSheet(
            "background-color: white; border: 1px dashed #bfc6d8; border-radius: 16px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 48, 32, 48)
        card_layout.setSpacing(12)

        headline = QLabel("Modul under utvikling")
        headline.setStyleSheet("font-size: 20px; font-weight: 600; color: #1f2937;")
        headline.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(headline)

        message = QLabel(
            "Denne delen er reservert for fremtidige revisjonstester og analyser."
        )
        message.setStyleSheet("color: #6b7280; font-size: 15px;")
        message.setAlignment(Qt.AlignCenter)
        message.setWordWrap(True)
        card_layout.addWidget(message)

        layout.addWidget(card, 1)
        return widget

    def _create_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(False)
        return table

    # endregion

    # region Navigasjonshendelser
    def _on_navigation_selection(self) -> None:
        selected_items = self.navigation.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        page_id = item.data(0, Qt.UserRole)
        if page_id is None and item.childCount() > 0:
            self.navigation.setCurrentItem(item.child(0))
            return
        if page_id not in self.page_map:
            return
        widget = self.page_map[page_id]
        self.stack.setCurrentWidget(widget)

    # endregion

    # region Handlinger
    def on_open(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Åpne SAF-T-fil",
            "",
            "SAF-T XML (*.xml);;Alle filer (*.*)",
        )
        if not filename:
            return
        try:
            root = ET.parse(filename).getroot()
            self._header = parse_saft_header(root)
            df = parse_saldobalanse(root)
            self._cust_map = parse_customers(root)
            self._sales_agg = extract_sales_taxbase_by_customer(root)
            self._ar_agg = extract_ar_from_gl(root)
            self._saft_df = df
            self._saft_summary = ns4102_summary_from_tb(df)
            self._update_header_fields()
            self._populate_summary()
            self._fill_table_from_dataframe(self.table_tb, df)
            self.statusBar().showMessage(
                "SAF-T lest. Klart for videre analyser og eksport."
            )
            self.act_brreg.setEnabled(True)
            self.act_export.setEnabled(True)
            self.btn_calc_top.setEnabled(True)
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved lesing av SAF-T", str(exc))
            self.statusBar().showMessage("Feil ved lesing av SAF-T.")

    def on_brreg(self) -> None:
        if not self._header or not self._header.orgnr:
            QMessageBox.warning(self, "Mangler org.nr", "Fant ikke organisasjonsnummer i SAF-T-headeren.")
            return
        orgnr = self._header.orgnr
        try:
            js = fetch_brreg(orgnr)
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved henting fra Regnskapsregisteret", str(exc))
            return
        self._brreg_json = js
        self.text_json.setPlainText(json.dumps(js, indent=2, ensure_ascii=False))
        self._brreg_map = map_brreg_metrics(js)
        rows: List[tuple[str, str]] = []

        def add_row(label: str, prefer_keys: Iterable[str]) -> None:
            disallow = ['egenkapitalOgGjeld'] if 'sumEgenkapital' in prefer_keys else None
            hit = find_first_by_exact_endkey(js, prefer_keys, disallow_contains=disallow)
            if not hit and 'sumEiendeler' in prefer_keys:
                hit = find_first_by_exact_endkey(js, ['sumEgenkapitalOgGjeld'])
            rows.append((label, f"{hit[0]} = {hit[1]}" if hit else "—"))

        add_row('Eiendeler (UB)', ['sumEiendeler'])
        add_row('Egenkapital (UB)', ['sumEgenkapital'])
        add_row('Gjeld (UB)', ['sumGjeld'])
        add_row('Driftsinntekter', ['driftsinntekter', 'sumDriftsinntekter', 'salgsinntekter'])
        add_row('EBIT', ['driftsresultat', 'ebit', 'driftsresultatFoerFinans'])
        add_row('Årsresultat', ['arsresultat', 'resultat', 'resultatEtterSkatt'])

        self._fill_table_rows(
            self.table_map,
            ["Felt", "Sti = Verdi"],
            rows,
        )

        if self._saft_summary:
            cmp_rows: List[tuple[str, str, str, str]] = []

            def add_cmp(label: str, saf_v: Optional[float], br_v: Optional[float]) -> None:
                cmp_rows.append(
                    (
                        label,
                        format_currency(saf_v),
                        format_currency(br_v),
                        format_difference(saf_v, br_v),
                    )
                )

            add_cmp(
                "Driftsinntekter",
                self._saft_summary['driftsinntekter'],
                self._brreg_map.get('driftsinntekter') if self._brreg_map else None,
            )
            add_cmp(
                "EBIT",
                self._saft_summary['ebit'],
                self._brreg_map.get('ebit') if self._brreg_map else None,
            )
            add_cmp(
                "Årsresultat",
                self._saft_summary['arsresultat'],
                self._brreg_map.get('arsresultat') if self._brreg_map else None,
            )
            add_cmp(
                "Eiendeler (UB)",
                self._saft_summary['eiendeler_UB_brreg'],
                self._brreg_map.get('eiendeler_UB') if self._brreg_map else None,
            )
            add_cmp(
                "Egenkapital (UB)",
                self._saft_summary['egenkapital_UB'],
                self._brreg_map.get('egenkapital_UB') if self._brreg_map else None,
            )
            add_cmp(
                "Gjeld (UB)",
                self._saft_summary['gjeld_UB_brreg'],
                self._brreg_map.get('gjeld_UB') if self._brreg_map else None,
            )

            self._fill_table_rows(
                self.table_cmp,
                ["Nøkkel", "SAF-T (Brreg-tilpasset)", "Brreg (siste år)", "Avvik"],
                cmp_rows,
                money_cols=[1, 2, 3],
            )
        self.statusBar().showMessage("Data hentet fra Regnskapsregisteret.")

    def on_calc_top_customers(self) -> None:
        source = self.cmb_source.currentText()
        topn = self.spn_topn.value()
        if source == "faktura":
            if self._sales_agg is None or self._sales_agg.empty:
                QMessageBox.information(
                    self,
                    "Ingen fakturaer",
                    "Fant ingen SalesInvoices med CustomerID/TaxBase/NetTotal i SAF-T. Prøv 'reskontro'.",
                )
                return
            data = self._sales_agg.copy()
            data['Kundenavn'] = data['CustomerID'].map(self._cust_map).fillna('')
            data = data.sort_values('OmsetningEksMva', ascending=False).head(topn)
            rows = [
                (
                    row['CustomerID'],
                    row['Kundenavn'],
                    int(row['Fakturaer']),
                    float(row['OmsetningEksMva']),
                )
                for _, row in data.iterrows()
            ]
            self._fill_table_rows(
                self.table_top,
                ["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"],
                rows,
                money_cols=[3],
            )
            self.statusBar().showMessage(f"Topp kunder (faktura) beregnet (N={topn}).")
            return

        if self._ar_agg is None or self._ar_agg.empty:
            QMessageBox.information(
                self,
                "Ingen reskontro",
                "Fant ikke kunde-ID på reskontro (1500–1599) i SAF-T.",
            )
            return

        data = self._ar_agg.copy()
        data['Kundenavn'] = data['CustomerID'].map(self._cust_map).fillna('')
        data['OmsetningEksMva'] = data['AR_Debit']
        data['Fakturaer'] = None
        data = data.sort_values('AR_Debit', ascending=False).head(topn)
        rows = [
            (
                row['CustomerID'],
                row['Kundenavn'],
                int(row['Fakturaer']) if row['Fakturaer'] is not None else 0,
                float(row['OmsetningEksMva']),
            )
            for _, row in data.iterrows()
        ]
        self._fill_table_rows(
            self.table_top,
            ["KundeID", "Kundenavn", "Fakturaer", "Omsetning (eks. mva)"],
            rows,
            money_cols=[3],
        )
        self.statusBar().showMessage(f"Topp kunder (reskontro) beregnet (N={topn}).")

    def on_export(self) -> None:
        if self._saft_df is None:
            QMessageBox.warning(self, "Ingenting å eksportere", "Last inn en SAF-T-fil først.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Eksporter rapport",
            "SAFT_rapport.xlsx",
            "Excel (*.xlsx)",
        )
        if not filename:
            return
        try:
            with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
                self._saft_df.to_excel(writer, sheet_name='Saldobalanse', index=False)
                if self._saft_summary:
                    summary_df = pd.DataFrame([self._saft_summary]).T.reset_index()
                    summary_df.columns = ['Nøkkel', 'Beløp']
                    summary_df.to_excel(writer, sheet_name='NS4102_Sammendrag', index=False)
                if self._sales_agg is not None:
                    self._sales_agg.to_excel(writer, sheet_name='Sales_by_customer', index=False)
                if self._ar_agg is not None:
                    self._ar_agg.to_excel(writer, sheet_name='AR_agg', index=False)
                if self._brreg_json:
                    pd.json_normalize(self._brreg_json).to_excel(writer, sheet_name='Brreg_JSON', index=False)
                if self._brreg_map:
                    map_df = pd.DataFrame(list(self._brreg_map.items()), columns=['Felt', 'Verdi'])
                    map_df.to_excel(writer, sheet_name='Brreg_Mapping', index=False)
            self.statusBar().showMessage(f"Eksportert rapport: {filename}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            QMessageBox.critical(self, "Feil ved eksport", str(exc))

    # endregion

    # region Oppdateringshjelpere
    def _update_header_fields(self) -> None:
        if not self._header:
            return
        self.lbl_company.setText(self._header.company_name or "—")
        self.lbl_orgnr.setText(f"Org.nr: {self._header.orgnr or '–'}")
        period = (
            f"{self._header.fiscal_year or '–'} P{self._header.period_start or '?'}–P{self._header.period_end or '?'}"
        )
        self.lbl_period.setText(f"Periode: {period}")

    def _populate_summary(self) -> None:
        if not self._saft_summary:
            return
        mapping = {
            "driftsinntekter": self._saft_summary['driftsinntekter'],
            "ebit": self._saft_summary['ebit'],
            "arsresultat": self._saft_summary['arsresultat'],
            "eiendeler": self._saft_summary['eiendeler_UB'],
            "egenkapital": self._saft_summary['egenkapital_UB'],
            "balanse_diff": self._saft_summary['balanse_diff_brreg'],
        }
        for key, value in mapping.items():
            label = self.metric_labels.get(key)
            if not label:
                continue
            label.setText(format_currency(value) or "—")

        rows = [
            ("Driftsinntekter (3xxx)", self._saft_summary['driftsinntekter']),
            ("Varekostnad (4xxx)", self._saft_summary['varekostnad']),
            ("Lønn (5xxx)", self._saft_summary['lonn']),
            ("Andre driftskostnader", self._saft_summary['andre_drift']),
            ("EBITDA", self._saft_summary['ebitda']),
            ("Avskrivninger", self._saft_summary['avskrivninger']),
            ("EBIT", self._saft_summary['ebit']),
            ("Netto finans", self._saft_summary['finans_netto']),
            ("Skatt", self._saft_summary['skattekostnad']),
            ("Årsresultat", self._saft_summary['arsresultat']),
            ("Eiendeler (UB)", self._saft_summary['eiendeler_UB']),
            ("Gjeld (UB)", self._saft_summary['gjeld_UB']),
            ("Balanseavvik (netto)", self._saft_summary['balanse_diff']),
            ("Eiendeler (UB) – Brreg", self._saft_summary['eiendeler_UB_brreg']),
            ("Gjeld (UB) – Brreg", self._saft_summary['gjeld_UB_brreg']),
            (
                "Reklassifisering (21xx–29xx)",
                self._saft_summary['liab_debet_21xx_29xx'],
            ),
        ]
        self._fill_table_rows(
            self.table_ns,
            ["Linje", "Beløp"],
            rows,
            money_cols=[1],
        )

    def _fill_table_from_dataframe(self, table: QTableWidget, df: pd.DataFrame) -> None:
        table.clear()
        columns = list(df.columns)
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(df))
        for row_index, (_, row) in enumerate(df.iterrows()):
            for col_index, column in enumerate(columns):
                value = row[column]
                display = value
                if isinstance(value, (int, float)):
                    try:
                        display = f"{float(value):,.2f}"
                    except Exception:
                        display = value
                item = QTableWidgetItem("" if display is None else str(display))
                if isinstance(value, (int, float)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, col_index, item)

    def _fill_table_rows(
        self,
        table: QTableWidget,
        columns: Sequence[str],
        rows: Iterable[Sequence[object]],
        *,
        money_cols: Optional[Sequence[int]] = None,
    ) -> None:
        table.clear()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        rows_list = list(rows)
        table.setRowCount(len(rows_list))
        money_cols = money_cols or []
        for row_index, row in enumerate(rows_list):
            for col_index, value in enumerate(row):
                display = value
                if col_index in money_cols:
                    try:
                        display = format_currency(float(value))
                    except Exception:
                        display = value
                item = QTableWidgetItem("" if display is None else str(display))
                alignment = Qt.AlignLeft | Qt.AlignVCenter
                if col_index in money_cols:
                    alignment = Qt.AlignRight | Qt.AlignVCenter
                item.setTextAlignment(alignment)
                table.setItem(row_index, col_index, item)

    # endregion


def create_app() -> MainWindow:
    """Fabrikkfunksjon for hovedvinduet."""

    return MainWindow()


def run() -> None:
    """Starter PySide6-applikasjonen."""

    app = QApplication.instance()
    owns_app = False
    if app is None:
        app = QApplication(sys.argv)
        owns_app = True
    app.setApplicationName(APP_TITLE)
    window = create_app()
    window.show()
    if owns_app:
        sys.exit(app.exec())


__all__ = ["MainWindow", "create_app", "run"]
