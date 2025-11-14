"""PySide6-basert GUI for Nordlys."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    cast,
)
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWidgets import QWIDGETSIZE_MAX
except ImportError:  # PySide6 < 6.7
    QWIDGETSIZE_MAX = 16777215

from ..constants import APP_TITLE
from ..core.task_runner import TaskRunner
from ..industry_groups import IndustryClassification
from ..saft.loader import SaftLoadResult, load_saft_file, load_saft_files
from ..utils import format_currency, lazy_import, lazy_pandas
from .config import PRIMARY_UI_FONT_FAMILY, REVISION_TASKS, icon_for_navigation
from .pages.analysis_pages import (
    ComparisonPage,
    RegnskapsanalysePage,
    SammenstillingsanalysePage,
    SummaryPage,
)
from .pages.dashboard_page import DashboardPage
from .pages.dataframe_page import DataFramePage, standard_tb_frame
from .pages.import_page import ImportPage
from .pages.revision_pages import (
    ChecklistPage,
    CostVoucherReviewPage,
    PurchasesApPage,
    SalesArPage,
)
from .widgets import CardFrame, TaskProgressDialog

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

pd = lazy_pandas()

saft = lazy_import("nordlys.saft")
saft_customers = lazy_import("nordlys.saft_customers")
regnskap = lazy_import("nordlys.regnskap")




TOP_BORDER_ROLE = Qt.UserRole + 41
BOTTOM_BORDER_ROLE = Qt.UserRole + 42
































@dataclass







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
        logo_font = self.logo_label.font()
        logo_font.setFamily(PRIMARY_UI_FONT_FAMILY)
        self.logo_label.setFont(logo_font)
        layout.addWidget(self.logo_label)

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
            font = item.font(0)
            font.setFamily(PRIMARY_UI_FONT_FAMILY)
            font.setPointSize(font.pointSize() + 1)
            font.setWeight(QFont.DemiBold)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#f8fafc")))
            icon = icon_for_navigation(key)
            if icon:
                item.setIcon(0, icon)
        else:
            font = item.font(0)
            font.setFamily(PRIMARY_UI_FONT_FAMILY)
            font.setPointSize(max(font.pointSize() - 1, 9))
            font.setWeight(QFont.DemiBold)
            font.setCapitalization(QFont.AllUppercase)
            font.setLetterSpacing(QFont.PercentageSpacing, 115)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#94a3b8")))
            item.setFlags(
                item.flags()
                & ~Qt.ItemIsSelectable
                & ~Qt.ItemIsDragEnabled
                & ~Qt.ItemIsDropEnabled
            )
        self.tree.addTopLevelItem(item)
        self.tree.expandItem(item)
        return NavigationItem(key or title.lower(), item)

    def add_child(self, parent: NavigationItem, title: str, key: str) -> NavigationItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, key)
        font = item.font(0)
        font.setFamily(PRIMARY_UI_FONT_FAMILY)
        font.setWeight(QFont.Medium)
        item.setFont(0, font)
        item.setForeground(0, QBrush(QColor("#e2e8f0")))
        icon = icon_for_navigation(key)
        if icon:
            item.setIcon(0, icon)
        parent.item.addChild(item)
        parent.item.setExpanded(True)
        return NavigationItem(key, item)


class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(1100, int(available.width() * 0.82))
            height = max(720, int(available.height() * 0.82))
            self.resize(width, height)
        else:
            self.resize(1460, 940)
        # Sikrer at hovedvinduet kan maksimeres uten Qt-advarsler selv om enkelte
        # underliggende widgets har begrensende størrelseshint.
        self.setMinimumSize(1024, 680)
        self.setMaximumSize(16777215, 16777215)

        self._saft_df: Optional[pd.DataFrame] = None
        self._saft_summary: Optional[Dict[str, float]] = None
        self._header: Optional["saft.SaftHeader"] = None
        self._brreg_json: Optional[Dict[str, object]] = None
        self._brreg_map: Optional[Dict[str, Optional[float]]] = None
        self._customers: Dict[str, "saft.CustomerInfo"] = {}
        self._cust_name_by_nr: Dict[str, str] = {}
        self._cust_id_to_nr: Dict[str, str] = {}
        self._customer_sales: Optional[pd.DataFrame] = None
        self._suppliers: Dict[str, "saft.SupplierInfo"] = {}
        self._sup_name_by_nr: Dict[str, str] = {}
        self._sup_id_to_nr: Dict[str, str] = {}
        self._supplier_purchases: Optional[pd.DataFrame] = None
        self._cost_vouchers: List["saft_customers.CostVoucher"] = []
        self._validation_result: Optional["saft.SaftValidationResult"] = None
        self._industry: Optional[IndustryClassification] = None
        self._industry_error: Optional[str] = None
        self._current_file: Optional[str] = None

        self._dataset_results: Dict[str, SaftLoadResult] = {}
        self._dataset_years: Dict[str, Optional[int]] = {}
        self._dataset_orgnrs: Dict[str, Optional[str]] = {}
        self._dataset_order: List[str] = []
        self._dataset_positions: Dict[str, int] = {}
        self._current_dataset_key: Optional[str] = None
        self._loading_files: List[str] = []

        self._task_runner = TaskRunner(self)
        self._task_runner.sig_started.connect(self._on_task_started)
        self._task_runner.sig_progress.connect(self._on_task_progress)
        self._task_runner.sig_done.connect(self._on_task_done)
        self._task_runner.sig_error.connect(self._on_task_error)

        self._current_task_id: Optional[str] = None
        self._current_task_meta: Dict[str, Any] = {}
        self._status_progress_label: Optional[QLabel] = None
        self._status_progress_bar: Optional[QProgressBar] = None
        self._progress_dialog: Optional[TaskProgressDialog] = None

        self._page_map: Dict[str, QWidget] = {}
        self._page_factories: Dict[str, Callable[[], QWidget]] = {}
        self._page_attributes: Dict[str, str] = {}
        self._latest_comparison_rows: Optional[
            Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ] = None
        self.revision_pages: Dict[str, QWidget] = {}
        self.import_page: Optional['ImportPage'] = None
        self.sales_ar_page: Optional[SalesArPage] = None
        self.purchases_ap_page: Optional['PurchasesApPage'] = None
        self.cost_review_page: Optional['CostVoucherReviewPage'] = None
        self.regnskap_page: Optional['RegnskapsanalysePage'] = None
        self.sammenstilling_page: Optional['SammenstillingsanalysePage'] = None
        self._navigation_initialized = False
        self._content_layout: Optional[QVBoxLayout] = None
        self._responsive_update_pending = False
        self._layout_mode: Optional[str] = None
        self._layout_signature: Optional[Tuple[str, int, int, int, int, int, int]] = None

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
        content_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(24)
        root_layout.addWidget(content_wrapper, 1)
        self._content_layout = content_layout

        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        self.title_label = QLabel("Import")
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label, 1)

        self.dataset_combo = QComboBox()
        self.dataset_combo.setObjectName("datasetCombo")
        self.dataset_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.dataset_combo.setPlaceholderText("Velg datasett")
        self.dataset_combo.setToolTip(
            "Når du har importert flere SAF-T-filer kan du raskt bytte aktive data her."
        )
        self.dataset_combo.setVisible(False)
        self.dataset_combo.currentIndexChanged.connect(self._on_dataset_changed)
        header_layout.addWidget(self.dataset_combo)

        self.btn_open = QPushButton("Åpne SAF-T XML …")
        self.btn_open.clicked.connect(self.on_open)
        header_layout.addWidget(self.btn_open)

        self.btn_export = QPushButton("Eksporter rapport (Excel)")
        self.btn_export.clicked.connect(self.on_export)
        self.btn_export.setEnabled(False)
        header_layout.addWidget(self.btn_export)

        content_layout.addLayout(header_layout)

        self.info_card = CardFrame("Selskapsinformasjon")
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(8)

        self.lbl_company = QLabel("Selskap: –")
        self.lbl_orgnr = QLabel("Org.nr: –")
        self.lbl_period = QLabel("Periode: –")
        info_grid.addWidget(self.lbl_company, 0, 0)
        info_grid.addWidget(self.lbl_orgnr, 0, 1)
        info_grid.addWidget(self.lbl_period, 0, 2)
        self.info_card.add_layout(info_grid)
        content_layout.addWidget(self.info_card)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        self.stack.currentChanged.connect(lambda _: self._schedule_responsive_update())

        self._create_pages()

        status = QStatusBar()
        status.showMessage("Klar.")
        progress_label = QLabel()
        progress_label.setObjectName("statusProgressLabel")
        progress_label.setVisible(False)
        status.addPermanentWidget(progress_label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(False)
        progress_bar.setFixedWidth(180)
        progress_bar.setVisible(False)
        status.addPermanentWidget(progress_bar)
        self._status_progress_label = progress_label
        self._status_progress_bar = progress_bar
        self.setStatusBar(status)

    def _create_pages(self) -> None:
        import_page = ImportPage()
        self._register_page("import", import_page, attr="import_page")

        self._register_lazy_page("dashboard", self._build_dashboard_page, attr="dashboard_page")
        self._register_lazy_page(
            "plan.saldobalanse",
            self._build_saldobalanse_page,
            attr="saldobalanse_page",
        )
        self._register_lazy_page(
            "plan.kontroll",
            self._build_kontroll_page,
            attr="kontroll_page",
        )
        self._register_lazy_page(
            "plan.regnskapsanalyse",
            self._build_regnskap_page,
            attr="regnskap_page",
        )
        self._register_lazy_page(
            "plan.vesentlighet",
            self._build_vesentlig_page,
            attr="vesentlig_page",
        )
        self._register_lazy_page(
            "plan.sammenstilling",
            self._build_sammenstilling_page,
            attr="sammenstilling_page",
        )

        revision_definitions = {
            "rev.innkjop": (
                "Innkjøp og leverandørgjeld",
                "Fokuser på varekjøp, kredittider og periodisering.",
            ),
            "rev.lonn": ("Lønn", "Kontroll av lønnskjøringer, skatt og arbeidsgiveravgift."),
            "rev.kostnad": ("Kostnad", "Analyse av driftskostnader og periodisering."),
            "rev.driftsmidler": (
                "Driftsmidler",
                "Verifikasjon av investeringer og avskrivninger.",
            ),
            "rev.finans": ("Finans og likvid", "Bank, finansielle instrumenter og kontantstrøm."),
            "rev.varelager": (
                "Varelager og varekjøp",
                "Telling, nedskrivninger og bruttomargin.",
            ),
            "rev.salg": (
                "Salg og kundefordringer",
                "Omsetning, cut-off og reskontro.",
            ),
            "rev.mva": ("MVA", "Kontroll av avgiftsbehandling og rapportering."),
        }
        for key, (title, subtitle) in revision_definitions.items():
            if key == "rev.salg":
                self._register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_sales_page(title, subtitle),
                    attr="sales_ar_page",
                )
            elif key == "rev.innkjop":
                self._register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_purchases_page(title, subtitle),
                    attr="purchases_ap_page",
                )
            elif key == "rev.kostnad":
                self._register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_cost_page(title, subtitle),
                    attr="cost_review_page",
                )
            else:
                self._register_lazy_page(
                    key,
                    lambda key=key, title=title, subtitle=subtitle: self._build_checklist_page(
                        key, title, subtitle
                    ),
                )

        QTimer.singleShot(0, self._populate_navigation)

    def _populate_navigation(self) -> None:
        if self._navigation_initialized:
            return
        self._navigation_initialized = True
        nav = self.nav_panel
        import_item = nav.add_root("Import", "import")
        nav.add_root("Dashboard", "dashboard")

        planning_root = nav.add_root("Planlegging")
        nav.add_child(planning_root, "Saldobalanse", "plan.saldobalanse")
        nav.add_child(planning_root, "Kontroll IB", "plan.kontroll")
        nav.add_child(planning_root, "Regnskapsanalyse", "plan.regnskapsanalyse")
        nav.add_child(planning_root, "Vesentlighetsvurdering", "plan.vesentlighet")
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
        nav.tree.setCurrentItem(import_item.item)

    def _register_page(self, key: str, widget: QWidget, *, attr: Optional[str] = None) -> None:
        self._page_map[key] = widget
        if attr:
            self._page_attributes[key] = attr
            setattr(self, attr, widget)
        self.stack.addWidget(widget)
        self._apply_page_state(key, widget)

    def _register_lazy_page(
        self, key: str, factory: Callable[[], QWidget], *, attr: Optional[str] = None
    ) -> None:
        self._page_factories[key] = factory
        if attr:
            self._page_attributes[key] = attr

    def _ensure_page(self, key: str) -> Optional[QWidget]:
        widget = self._page_map.get(key)
        if widget is not None:
            return widget
        return self._materialize_page(key)

    def _materialize_page(self, key: str) -> Optional[QWidget]:
        factory = self._page_factories.get(key)
        if factory is None:
            return None
        widget = factory()
        attr = self._page_attributes.get(key)
        self._register_page(key, widget, attr=attr)
        return widget

    def _apply_page_state(self, key: str, widget: QWidget) -> None:
        if key in REVISION_TASKS:
            self.revision_pages[key] = widget
        if key == "dashboard" and isinstance(widget, DashboardPage):
            widget.update_summary(self._saft_summary)
        elif key == "plan.saldobalanse" and isinstance(widget, DataFramePage):
            widget.set_dataframe(self._saft_df)
        elif key == "plan.kontroll" and isinstance(widget, ComparisonPage):
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.regnskapsanalyse" and isinstance(widget, RegnskapsanalysePage):
            fiscal_year = self._header.fiscal_year if self._header else None
            widget.set_dataframe(self._saft_df, fiscal_year)
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.vesentlighet" and isinstance(widget, SummaryPage):
            widget.update_summary(self._saft_summary)
        elif key == "plan.sammenstilling" and isinstance(widget, SammenstillingsanalysePage):
            fiscal_year = self._header.fiscal_year if self._header else None
            widget.set_dataframe(self._saft_df, fiscal_year)
        elif key == "rev.salg" and isinstance(widget, SalesArPage):
            widget.set_checklist_items(REVISION_TASKS.get(key, []))
            has_data = self._customer_sales is not None and not self._customer_sales.empty
            widget.set_controls_enabled(has_data)
            if not has_data:
                widget.clear_top_customers()
        elif key == "rev.innkjop" and isinstance(widget, PurchasesApPage):
            has_data = self._supplier_purchases is not None and not self._supplier_purchases.empty
            widget.set_controls_enabled(has_data)
            if not has_data:
                widget.clear_top_suppliers()
        elif key == "rev.kostnad" and isinstance(widget, CostVoucherReviewPage):
            widget.set_vouchers(self._cost_vouchers)
        elif key in REVISION_TASKS and isinstance(widget, ChecklistPage):
            widget.set_items(REVISION_TASKS.get(key, []))
        self._schedule_responsive_update()

    def _build_dashboard_page(self) -> 'DashboardPage':
        return DashboardPage()

    def _build_saldobalanse_page(self) -> DataFramePage:
        return DataFramePage(
            "Saldobalanse",
            "Viser saldobalansen slik den er rapportert i SAF-T.",
            frame_builder=standard_tb_frame,
            money_columns=("IB", "Endringer", "UB"),
            header_mode=QHeaderView.ResizeToContents,
            full_window=True,
        )

    def _build_kontroll_page(self) -> ComparisonPage:
        return ComparisonPage(
            "Kontroll av inngående balanse",
            "Sammenligner SAF-T mot Regnskapsregisteret for å avdekke avvik i inngående balanse.",
        )

    def _build_regnskap_page(self) -> 'RegnskapsanalysePage':
        return RegnskapsanalysePage()

    def _build_vesentlig_page(self) -> SummaryPage:
        return SummaryPage(
            "Vesentlighetsvurdering",
            "Nøkkeltall som understøtter fastsettelse av vesentlighetsgrenser.",
        )

    def _build_sammenstilling_page(self) -> 'SammenstillingsanalysePage':
        return SammenstillingsanalysePage()

    def _build_sales_page(self, title: str, subtitle: str) -> SalesArPage:
        page = SalesArPage(title, subtitle, self._on_calc_top_customers)
        page.set_checklist_items(REVISION_TASKS.get("rev.salg", []))
        has_data = self._customer_sales is not None and not self._customer_sales.empty
        page.set_controls_enabled(has_data)
        if not has_data:
            page.clear_top_customers()
        return page

    def _build_purchases_page(self, title: str, subtitle: str) -> 'PurchasesApPage':
        page = PurchasesApPage(title, subtitle, self._on_calc_top_suppliers)
        has_data = self._supplier_purchases is not None and not self._supplier_purchases.empty
        page.set_controls_enabled(has_data)
        if not has_data:
            page.clear_top_suppliers()
        return page

    def _build_cost_page(self, title: str, subtitle: str) -> 'CostVoucherReviewPage':
        page = CostVoucherReviewPage(title, subtitle)
        page.set_vouchers(self._cost_vouchers)
        return page

    def _build_checklist_page(self, key: str, title: str, subtitle: str) -> ChecklistPage:
        page = ChecklistPage(title, subtitle)
        page.set_items(REVISION_TASKS.get(key, []))
        return page

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-family: 'Roboto', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 14px; color: #0f172a; }
            QMainWindow { background-color: #e9effb; }
            #navPanel { background-color: #0b1120; color: #e2e8f0; border-right: 1px solid rgba(148, 163, 184, 0.18); }
            #logoLabel { font-size: 26px; font-weight: 700; letter-spacing: 0.6px; color: #f8fafc; }
            #navTree { background: transparent; border: none; color: #dbeafe; font-size: 14px; }
            #navTree:focus { outline: none; border: none; }
            QTreeWidget::item:focus { outline: none; }
            #navTree::item { height: 34px; padding: 6px 10px; border-radius: 10px; margin: 2px 0; }
            #navTree::item:selected { background-color: rgba(59, 130, 246, 0.35); color: #f8fafc; font-weight: 600; }
            #navTree::item:hover { background-color: rgba(59, 130, 246, 0.18); }
            QPushButton { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #1d4ed8); color: #f8fafc; border-radius: 10px; padding: 10px 20px; font-weight: 600; letter-spacing: 0.2px; }
            QPushButton:focus { outline: none; }
            QPushButton:disabled { background-color: #94a3b8; color: #e5e7eb; }
            QPushButton:hover:!disabled { background-color: #1e40af; }
            QPushButton:pressed { background-color: #1d4ed8; }
            QPushButton#approveButton { background-color: #16a34a; }
            QPushButton#approveButton:hover:!disabled { background-color: #15803d; }
            QPushButton#approveButton:pressed { background-color: #166534; }
            QPushButton#rejectButton { background-color: #dc2626; }
            QPushButton#rejectButton:hover:!disabled { background-color: #b91c1c; }
            QPushButton#rejectButton:pressed { background-color: #991b1b; }
            QPushButton#navButton { background-color: #0ea5e9; }
            QPushButton#navButton:hover:!disabled { background-color: #0284c7; }
            QPushButton#navButton:pressed { background-color: #0369a1; }
            QPushButton#exportPdfButton { background-color: #f97316; }
            QPushButton#exportPdfButton:hover:!disabled { background-color: #ea580c; }
            QPushButton#exportPdfButton:pressed { background-color: #c2410c; }
            #card { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f8fbff); border-radius: 20px; border: 1px solid rgba(148, 163, 184, 0.32); }
            #cardTitle { font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: 0.2px; }
            #cardSubtitle { color: #475569; font-size: 13px; line-height: 1.5; }
            #analysisSectionTitle { font-size: 16px; font-weight: 700; color: #0f172a; letter-spacing: 0.2px; border-bottom: 2px solid rgba(37, 99, 235, 0.35); padding-bottom: 6px; }
            #pageTitle { font-size: 30px; font-weight: 800; color: #0f172a; letter-spacing: 0.6px; }
            QLabel#pageSubtitle { color: #1e293b; font-size: 15px; }
            #statusLabel { color: #1f2937; font-size: 14px; line-height: 1.6; }
            QLabel[statusState='approved'] { color: #166534; font-weight: 600; }
            QLabel[statusState='rejected'] { color: #b91c1c; font-weight: 600; }
            QLabel[statusState='pending'] { color: #64748b; font-weight: 500; }
            #emptyState { background-color: rgba(148, 163, 184, 0.12); border-radius: 18px; border: 1px dashed rgba(148, 163, 184, 0.4); }
            #emptyStateIcon { font-size: 32px; }
            #emptyStateTitle { font-size: 17px; font-weight: 600; color: #0f172a; }
            #emptyStateDescription { color: #475569; font-size: 13px; max-width: 420px; }
            #cardTable { border: none; gridline-color: rgba(148, 163, 184, 0.35); background-color: transparent; alternate-background-color: #f8fafc; }
            QTableWidget { background-color: transparent; alternate-background-color: #f8fafc; }
            QTableWidget::item { padding: 1px 8px; }
            QTableWidget::item:selected { background-color: rgba(37, 99, 235, 0.22); color: #0f172a; }
            QHeaderView::section { background-color: rgba(148, 163, 184, 0.12); border: none; font-weight: 700; color: #0f172a; padding: 10px 6px; text-transform: uppercase; letter-spacing: 0.8px; }
            QHeaderView::section:horizontal { border-bottom: 2px solid rgba(37, 99, 235, 0.35); }
            QListWidget#checklist { border: none; }
            QListWidget#checklist::item { padding: 12px 16px; margin: 6px 0; border-radius: 12px; }
            QListWidget#checklist::item:selected { background-color: rgba(37, 99, 235, 0.18); color: #0f172a; font-weight: 600; }
            QListWidget#checklist::item:hover { background-color: rgba(15, 23, 42, 0.08); }
            #statBadge { background-color: #f8fafc; border: 1px solid rgba(148, 163, 184, 0.35); border-radius: 16px; }
            #statTitle { font-size: 12px; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: 1.2px; }
            #statValue { font-size: 26px; font-weight: 700; color: #0f172a; }
            #statDescription { font-size: 12px; color: #64748b; }
            QStatusBar { background: transparent; color: #475569; padding-right: 24px; border-top: 1px solid rgba(148, 163, 184, 0.3); }
            QComboBox, QSpinBox { background-color: #ffffff; border: 1px solid rgba(148, 163, 184, 0.5); border-radius: 10px; padding: 8px 12px; min-height: 32px; }
            QComboBox QAbstractItemView { border-radius: 8px; padding: 6px; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; }
            QSpinBox::up-button, QSpinBox::down-button { border: none; background: transparent; width: 20px; }
            QToolTip { background-color: #0f172a; color: #f8fafc; border: none; padding: 8px 10px; border-radius: 8px; }
            QTabWidget::pane { border: 1px solid rgba(148, 163, 184, 0.32); border-radius: 14px; background: #f4f7ff; margin-top: 12px; padding: 12px; }
            QTabWidget::tab-bar { left: 12px; }
            QTabBar::tab { background: rgba(148, 163, 184, 0.18); color: #0f172a; padding: 10px 20px; border-radius: 10px; margin-right: 8px; font-weight: 600; }
            QTabBar::tab:selected { background: #2563eb; color: #f8fafc; }
            QTabBar::tab:hover { background: rgba(37, 99, 235, 0.35); color: #0f172a; }
            QTabBar::tab:!selected { border: 1px solid rgba(148, 163, 184, 0.35); }
            #analysisDivider { background-color: rgba(148, 163, 184, 0.45); border-radius: 2px; margin: 4px 0; }
            QScrollBar:vertical { background: rgba(148, 163, 184, 0.18); width: 12px; margin: 8px 2px 8px 0; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #2563eb; min-height: 24px; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background: #1d4ed8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background: rgba(148, 163, 184, 0.18); height: 12px; margin: 0 8px 2px 8px; border-radius: 6px; }
            QScrollBar::handle:horizontal { background: #2563eb; min-width: 24px; border-radius: 6px; }
            QScrollBar::handle:horizontal:hover { background: #1d4ed8; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            """
        )

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._schedule_responsive_update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_responsive_update()

    def _schedule_responsive_update(self) -> None:
        if self._responsive_update_pending:
            return
        self._responsive_update_pending = True
        QTimer.singleShot(0, self._run_responsive_update)

    def _run_responsive_update(self) -> None:
        self._responsive_update_pending = False
        self._update_responsive_layout()

    def _update_responsive_layout(self) -> None:
        if self._content_layout is None:
            return
        available_width = self.centralWidget().width() if self.centralWidget() else self.width()
        width = max(self.width(), available_width)
        if width <= 0:
            return

        if width < 1400:
            mode = "compact"
            nav_width = 210
            margin = 16
            spacing = 16
            card_margin = 18
            card_spacing = 12
            nav_spacing = 18
            header_min = 80
        elif width < 2000:
            mode = "medium"
            nav_width = 250
            margin = 28
            spacing = 22
            card_margin = 24
            card_spacing = 14
            nav_spacing = 22
            header_min = 100
        else:
            mode = "wide"
            nav_width = 300
            margin = 36
            spacing = 28
            card_margin = 28
            card_spacing = 16
            nav_spacing = 24
            header_min = 120

        layout_signature = (mode, nav_width, margin, spacing, card_margin, card_spacing, nav_spacing)
        signature_changed = layout_signature != self._layout_signature

        self._layout_mode = mode

        if signature_changed:
            self.nav_panel.setMinimumWidth(nav_width)
            self.nav_panel.setMaximumWidth(nav_width)
            self._content_layout.setContentsMargins(margin, margin, margin, margin)
            self._content_layout.setSpacing(spacing)

            nav_layout = self.nav_panel.layout()
            if isinstance(nav_layout, QVBoxLayout):
                nav_padding = max(12, margin - 4)
                nav_layout.setContentsMargins(nav_padding, margin, nav_padding, margin)
                nav_layout.setSpacing(nav_spacing)

            for card in self.findChildren(CardFrame):
                layout = card.layout()
                if isinstance(layout, QVBoxLayout):
                    layout.setContentsMargins(card_margin, card_margin, card_margin, card_margin)
                    layout.setSpacing(max(card_spacing, 10))
                body_layout = getattr(card, "body_layout", None)
                if isinstance(body_layout, QVBoxLayout):
                    body_layout.setSpacing(max(card_spacing - 4, 8))

            self._layout_signature = layout_signature

        self._apply_table_sizing(header_min, width)

    def _ensure_visibility_update_hook(self, table: QTableWidget) -> None:
        widget = table.parentWidget()
        while widget is not None:
            if isinstance(widget, (QTabWidget, QStackedWidget)):
                hooks: Set[int] = getattr(widget, "_responsive_update_hooks", set())
                if id(self) not in hooks:
                    widget.currentChanged.connect(
                        lambda *_args, _self=self: _self._schedule_responsive_update()
                    )
                    hooks = set(hooks)
                    hooks.add(id(self))
                    setattr(widget, "_responsive_update_hooks", hooks)
            widget = widget.parentWidget()

    def _apply_table_sizing(self, min_section_size: int, available_width: int) -> None:
        current_widget = getattr(self, "stack", None)
        if isinstance(current_widget, QStackedWidget):
            active = current_widget.currentWidget()
            tables = active.findChildren(QTableWidget) if active is not None else []
        else:
            tables = []

        if not tables:
            tables = self.findChildren(QTableWidget)
        if not tables:
            return

        for table in tables:
            if not table.isVisibleTo(self):
                self._ensure_visibility_update_hook(table)
                continue
            header = table.horizontalHeader()
            if header is None:
                continue
            column_count = header.count()
            if column_count <= 0:
                continue

            sizing_signature = (
                self._layout_mode,
                min_section_size,
                available_width,
                table.rowCount(),
                table.columnCount(),
            )
            if table.property("_responsive_signature") == sizing_signature:
                continue

            header.setStretchLastSection(False)
            header.setMinimumSectionSize(min_section_size)

            for col in range(column_count):
                if header.sectionResizeMode(col) != QHeaderView.ResizeToContents:
                    header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            if table.rowCount() and table.columnCount():
                table.resizeColumnsToContents()
            table.setProperty("_responsive_signature", sizing_signature)

    # endregion

    # region Handlinger
    def on_open(self) -> None:
        if self._current_task_id is not None:
            QMessageBox.information(
                self,
                "Laster allerede",
                "En SAF-T-jobb kjører allerede i bakgrunnen. Vent til prosessen er ferdig.",
            )
            return
        file_names, _ = QFileDialog.getOpenFileNames(
            self,
            "Åpne SAF-T XML",
            str(Path.home()),
            "SAF-T XML (*.xml);;Alle filer (*)",
        )
        if not file_names:
            return
        self._loading_files = list(file_names)
        summary = (
            "Starter import av 1 SAF-T-fil"
            if len(file_names) == 1
            else f"Starter import av {len(file_names)} SAF-T-filer"
        )
        self._log_import_event(summary, reset=True)
        for name in file_names:
            self._log_import_event(f"Forbereder: {Path(name).name}")
        description = "Importer SAF-T"
        task_id = self._task_runner.run(
            load_saft_files,
            file_names,
            description=description,
        )
        self._current_task_id = task_id
        self._current_task_meta = {
            "type": "saft_import",
            "files": list(file_names),
            "description": description,
        }

    def _show_status_progress(self, message: str, value: int) -> None:
        if self._status_progress_label is not None:
            self._status_progress_label.setText(message)
            self._status_progress_label.setVisible(True)
        if self._status_progress_bar is not None:
            clamped = max(0, min(100, int(value)))
            self._status_progress_bar.setValue(clamped)
            self._status_progress_bar.setVisible(True)
        self._update_progress_dialog(message, value)

    def _hide_status_progress(self) -> None:
        if self._status_progress_label is not None:
            self._status_progress_label.clear()
            self._status_progress_label.setVisible(False)
        if self._status_progress_bar is not None:
            self._status_progress_bar.setValue(0)
            self._status_progress_bar.setVisible(False)
        self._close_progress_dialog()

    def _ensure_progress_dialog(self) -> TaskProgressDialog:
        if self._progress_dialog is None:
            self._progress_dialog = TaskProgressDialog(self)
        return self._progress_dialog

    def _update_progress_dialog(self, message: str, value: int) -> None:
        dialog = self._ensure_progress_dialog()
        dialog.set_files(self._loading_files)
        dialog.update_status(message, value)
        if not dialog.isVisible():
            dialog.show()
        dialog.raise_()

    def _close_progress_dialog(self) -> None:
        if self._progress_dialog is None:
            return
        dialog = self._progress_dialog
        self._progress_dialog = None
        dialog.hide()
        dialog.deleteLater()

    def _set_loading_state(self, loading: bool, status_message: Optional[str] = None) -> None:
        self.btn_open.setEnabled(not loading)
        has_data = self._saft_df is not None
        self.btn_export.setEnabled(False if loading else has_data)
        if hasattr(self, "dataset_combo"):
            if loading:
                self.dataset_combo.setEnabled(False)
            else:
                self.dataset_combo.setEnabled(bool(self._dataset_order))
        if self.sales_ar_page:
            if loading:
                self.sales_ar_page.set_controls_enabled(False)
            else:
                has_customer_data = (
                    self._customer_sales is not None and not self._customer_sales.empty
                )
                self.sales_ar_page.set_controls_enabled(has_customer_data)
        if self.purchases_ap_page:
            if loading:
                self.purchases_ap_page.set_controls_enabled(False)
            else:
                has_supplier_data = (
                    self._supplier_purchases is not None and not self._supplier_purchases.empty
                )
                self.purchases_ap_page.set_controls_enabled(has_supplier_data)
        if status_message:
            self.statusBar().showMessage(status_message)

    def _log_import_event(self, message: str, *, reset: bool = False) -> None:
        if not getattr(self, "import_page", None):
            return
        if reset:
            self.import_page.reset_log()
            self.import_page.reset_errors()
        self.import_page.append_log(message)

    def _finalize_loading(self, status_message: Optional[str] = None) -> None:
        self._hide_status_progress()
        self._set_loading_state(False)
        if status_message:
            self.statusBar().showMessage(status_message)
        else:
            self.statusBar().showMessage("Klar.")
        self._loading_files = []
        self._current_task_id = None
        self._current_task_meta = {}

    @Slot(str)
    def _on_task_started(self, task_id: str) -> None:
        if task_id != self._current_task_id:
            return
        if len(self._loading_files) == 1:
            message = f"Laster SAF-T: {Path(self._loading_files[0]).name} …"
        elif len(self._loading_files) > 1:
            message = f"Laster {len(self._loading_files)} SAF-T-filer …"
        else:
            message = "Laster SAF-T …"
        self._set_loading_state(True, message)
        self._show_status_progress(message, 0)

    @Slot(str, int, str)
    def _on_task_progress(self, task_id: str, percent: int, message: str) -> None:
        if task_id != self._current_task_id:
            return
        clean_message = message.strip() if message else ""
        if not clean_message:
            clean_message = self._current_task_meta.get("description", "Arbeid pågår …")
        self._show_status_progress(clean_message, percent)
        self.statusBar().showMessage(clean_message)

    @Slot(str, object)
    def _on_task_done(self, task_id: str, result: object) -> None:
        if task_id != self._current_task_id:
            return
        task_type = self._current_task_meta.get("type")
        if task_type == "saft_import":
            self._on_load_finished(result)
        else:
            self._finalize_loading()

    @Slot(str, str)
    def _on_task_error(self, task_id: str, exc_str: str) -> None:
        if task_id != self._current_task_id:
            return
        message = self._format_task_error(exc_str)
        task_type = self._current_task_meta.get("type")
        if task_type == "saft_import":
            self._on_load_error(message)
        else:
            self._finalize_loading(message)

    def _format_task_error(self, exc_str: str) -> str:
        text = exc_str.strip()
        if not text:
            return "Ukjent feil"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "Ukjent feil"
        return lines[-1]

    @Slot(object)
    def _on_load_finished(self, result_obj: object) -> None:
        results: List[SaftLoadResult]
        if isinstance(result_obj, list):
            results = [cast(SaftLoadResult, item) for item in result_obj]
        else:
            results = [cast(SaftLoadResult, result_obj)]
        self._apply_saft_batch(results)
        self._finalize_loading()

    def _apply_saft_batch(self, results: Sequence[SaftLoadResult]) -> None:
        if not results:
            self._dataset_results = {}
            self._dataset_years = {}
            self._dataset_orgnrs = {}
            self._dataset_order = []
            self._dataset_positions = {}
            self._current_dataset_key = None
            self._update_dataset_selector()
            if getattr(self, "import_page", None):
                self.import_page.update_invoice_count(None)
                self.import_page.update_misc_info(None)
            return

        self._dataset_results = {res.file_path: res for res in results}
        self._dataset_positions = {res.file_path: idx for idx, res in enumerate(results)}
        self._dataset_years = {
            res.file_path: self._resolve_dataset_year(res) for res in results
        }
        self._dataset_orgnrs = {
            res.file_path: self._resolve_dataset_orgnr(res) for res in results
        }
        self._dataset_order = self._sorted_dataset_keys()
        default_key = self._select_default_dataset_key()
        self._current_dataset_key = default_key
        self._update_dataset_selector()

        if default_key is None:
            return

        self._activate_dataset(default_key, log_event=True)
        if len(results) > 1:
            self._log_import_event(
                "Alle filer er lastet inn. Bruk årvelgeren for å bytte datasett."
            )

    def _resolve_dataset_year(self, result: SaftLoadResult) -> Optional[int]:
        if result.analysis_year is not None:
            return result.analysis_year
        header = result.header
        if header and header.fiscal_year:
            try:
                return int(str(header.fiscal_year).strip())
            except (TypeError, ValueError):
                return None
        return None

    def _resolve_dataset_orgnr(self, result: SaftLoadResult) -> Optional[str]:
        header = result.header
        if not header or not header.orgnr:
            return None
        raw_orgnr = str(header.orgnr).strip()
        if not raw_orgnr:
            return None
        normalized = "".join(ch for ch in raw_orgnr if ch.isdigit())
        if normalized:
            return normalized
        return raw_orgnr

    def _sorted_dataset_keys(self) -> List[str]:
        def sort_key(key: str) -> Tuple[int, int]:
            year = self._dataset_years.get(key)
            year_value = year if year is not None else 9999
            position = self._dataset_positions.get(key, 0)
            return (year_value, position)

        return sorted(self._dataset_results.keys(), key=sort_key)

    def _select_default_dataset_key(self) -> Optional[str]:
        if not self._dataset_order:
            return None
        for key in reversed(self._dataset_order):
            year = self._dataset_years.get(key)
            if year is not None:
                return key
        return self._dataset_order[-1]

    def _update_dataset_selector(self) -> None:
        if not hasattr(self, "dataset_combo"):
            return
        combo = self.dataset_combo
        combo.blockSignals(True)
        combo.clear()
        if not self._dataset_order:
            combo.setVisible(False)
            combo.blockSignals(False)
            return
        for key in self._dataset_order:
            result = self._dataset_results.get(key)
            if result is None:
                continue
            combo.addItem(self._dataset_label(result), userData=key)
        combo.setVisible(True)
        combo.setEnabled(bool(self._dataset_order))
        if self._current_dataset_key in self._dataset_order:
            combo.setCurrentIndex(self._dataset_order.index(self._current_dataset_key))
        combo.blockSignals(False)

    def _dataset_label(self, result: SaftLoadResult) -> str:
        year = self._dataset_years.get(result.file_path)
        if year is None and result.analysis_year is not None:
            year = result.analysis_year
        if year is not None:
            return str(year)
        header = result.header
        if header and header.fiscal_year and str(header.fiscal_year).strip():
            return str(header.fiscal_year).strip()
        position = self._dataset_positions.get(result.file_path)
        if position is not None:
            return str(position + 1)
        return "1"

    def _find_previous_dataset_key(self, current_key: str) -> Optional[str]:
        current_year = self._dataset_years.get(current_key)
        current_org = self._dataset_orgnrs.get(current_key)
        if current_year is None or not current_org:
            return None
        exact_year = current_year - 1
        for key, year in self._dataset_years.items():
            if key == current_key or year is None:
                continue
            if year == exact_year and self._dataset_orgnrs.get(key) == current_org:
                return key
        closest_key: Optional[str] = None
        closest_year: Optional[int] = None
        for key, year in self._dataset_years.items():
            if key == current_key or year is None:
                continue
            if self._dataset_orgnrs.get(key) != current_org:
                continue
            if year < current_year and (closest_year is None or year > closest_year):
                closest_key = key
                closest_year = year
        return closest_key

    def _prepare_dataframe_with_previous(
        self,
        current_df: pd.DataFrame,
        previous_df: Optional[pd.DataFrame],
    ) -> pd.DataFrame:
        work = current_df.copy()
        if previous_df is None:
            return work
        if "Konto" not in work.columns or "UB_netto" not in previous_df.columns:
            return work

        def _konto_key(value: object) -> str:
            if value is None:
                return ""
            try:
                if pd.isna(value):  # type: ignore[arg-type]
                    return ""
            except Exception:
                pass
            return str(value).strip()

        prev_work = previous_df.copy()
        if "Konto" not in prev_work.columns:
            return work
        prev_work["_konto_key"] = prev_work["Konto"].map(_konto_key)
        mapping = (
            prev_work.loc[prev_work["_konto_key"] != ""]
            .drop_duplicates("_konto_key")
            .set_index("_konto_key")["UB_netto"]
            .fillna(0.0)
        )

        work["forrige"] = work["Konto"].map(_konto_key).map(mapping).fillna(0.0)
        return work

    def _activate_dataset(self, key: str, *, log_event: bool = False) -> None:
        result = self._dataset_results.get(key)
        if result is None:
            return
        previous_key = self._find_previous_dataset_key(key)
        previous_result = (
            self._dataset_results.get(previous_key) if previous_key else None
        )
        self._current_dataset_key = key
        if hasattr(self, "dataset_combo") and key in self._dataset_order:
            combo = self.dataset_combo
            combo.blockSignals(True)
            combo.setCurrentIndex(self._dataset_order.index(key))
            combo.blockSignals(False)
        self._apply_saft_result(result, previous_result, log_event=log_event)
        if not log_event:
            self._log_import_event(f"Viser datasett: {self._dataset_label(result)}")

    def _on_dataset_changed(self, index: int) -> None:
        if index < 0 or index >= self.dataset_combo.count():
            return
        key = self.dataset_combo.itemData(index)
        if not isinstance(key, str):
            return
        if key == self._current_dataset_key:
            return
        self._activate_dataset(key)

    def _apply_saft_result(
        self,
        result: SaftLoadResult,
        previous_result: Optional[SaftLoadResult] = None,
        *,
        log_event: bool = False,
    ) -> None:
        self._header = result.header
        previous_df = previous_result.dataframe if previous_result is not None else None
        self._saft_df = self._prepare_dataframe_with_previous(result.dataframe, previous_df)
        self._saft_summary = result.summary
        self._validation_result = result.validation
        self._current_file = result.file_path

        self._ingest_customers(result.customers)
        self._ingest_suppliers(result.suppliers)
        self._customer_sales = (
            result.customer_sales.copy() if result.customer_sales is not None else None
        )
        self._supplier_purchases = (
            result.supplier_purchases.copy()
            if result.supplier_purchases is not None
            else None
        )
        self._cost_vouchers = list(result.cost_vouchers)
        if getattr(self, "import_page", None):
            self.import_page.update_invoice_count(len(self._cost_vouchers))

        if self._customer_sales is not None and not self._customer_sales.empty:
            if "Kundenavn" in self._customer_sales.columns:
                mask = self._customer_sales["Kundenavn"].astype(str).str.strip() == ""
                if mask.any():
                    self._customer_sales.loc[mask, "Kundenavn"] = self._customer_sales.loc[mask, "Kundenr"].apply(
                        lambda value: self._lookup_customer_name(value, value) or value
                    )
            else:
                self._customer_sales["Kundenavn"] = self._customer_sales["Kundenr"].apply(
                    lambda value: self._lookup_customer_name(value, value) or value
                )
            ordered_cols = ["Kundenr", "Kundenavn", "Omsetning eks mva"]
            ordered_cols += [col for col in ["Transaksjoner"] if col in self._customer_sales.columns]
            remaining = [col for col in self._customer_sales.columns if col not in ordered_cols]
            self._customer_sales = self._customer_sales.loc[:, ordered_cols + remaining]

        if self._supplier_purchases is not None and not self._supplier_purchases.empty:
            if "Leverandørnavn" in self._supplier_purchases.columns:
                mask = self._supplier_purchases["Leverandørnavn"].astype(str).str.strip() == ""
                if mask.any():
                    self._supplier_purchases.loc[mask, "Leverandørnavn"] = self._supplier_purchases.loc[
                        mask, "Leverandørnr"
                    ].apply(lambda value: self._lookup_supplier_name(value, value) or value)
            else:
                self._supplier_purchases["Leverandørnavn"] = self._supplier_purchases["Leverandørnr"].apply(
                    lambda value: self._lookup_supplier_name(value, value) or value
                )
            ordered_sup_cols = ["Leverandørnr", "Leverandørnavn", "Innkjøp eks mva"]
            ordered_sup_cols += [
                col for col in ["Transaksjoner"] if col in self._supplier_purchases.columns
            ]
            remaining_sup = [
                col for col in self._supplier_purchases.columns if col not in ordered_sup_cols
            ]
            self._supplier_purchases = self._supplier_purchases.loc[
                :, ordered_sup_cols + remaining_sup
            ]

        df = self._saft_df if self._saft_df is not None else result.dataframe
        self._update_header_fields()
        saldobalanse_page = cast(Optional[DataFramePage], getattr(self, "saldobalanse_page", None))
        if saldobalanse_page:
            saldobalanse_page.set_dataframe(df)
        self._latest_comparison_rows = None
        kontroll_page = cast(Optional[ComparisonPage], getattr(self, "kontroll_page", None))
        if kontroll_page:
            kontroll_page.update_comparison(None)
        dashboard_page = cast(Optional[DashboardPage], getattr(self, "dashboard_page", None))
        if dashboard_page:
            dashboard_page.update_summary(self._saft_summary)

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
        dataset_label = self._dataset_label(result)
        status_bits = [
            company or "Ukjent selskap",
            f"Org.nr: {orgnr}" if orgnr else "Org.nr: –",
            f"Periode: {period}" if period else None,
            f"{account_count} konti analysert",
            f"Driftsinntekter: {revenue_txt}",
        ]
        if dataset_label:
            status_bits.append(f"Datasett: {dataset_label}")
        status_message = " · ".join(bit for bit in status_bits if bit)
        if getattr(self, "import_page", None):
            misc_entries: List[Tuple[str, str]] = [
                ("Datasett", dataset_label or Path(result.file_path).name),
                ("Filnavn", Path(result.file_path).name),
                ("Konti analysert", str(account_count)),
            ]
            if company:
                misc_entries.append(("Selskap", company))
            if orgnr:
                misc_entries.append(("Org.nr", str(orgnr)))
            if period:
                misc_entries.append(("Periode", period))
            if revenue_txt and revenue_txt != "—":
                misc_entries.append(("Driftsinntekter", revenue_txt))
            misc_entries.append(("Oppdatert", datetime.now().strftime("%d.%m.%Y %H:%M")))
            self.import_page.update_misc_info(misc_entries)
            self.import_page.update_status(status_message)
        if log_event:
            self._log_import_event(
                f"{dataset_label or Path(result.file_path).name}: SAF-T lesing fullført. {account_count} konti analysert."
            )

        validation = result.validation
        if getattr(self, "import_page", None):
            self.import_page.update_validation_status(validation)
        if log_event:
            if validation.is_valid is True:
                self._log_import_event("XSD-validering fullført: OK.")
            elif validation.is_valid is False:
                self._log_import_event("XSD-validering feilet.")
            elif validation.is_valid is None and validation.details:
                self._log_import_event("XSD-validering: detaljer tilgjengelig, se importstatus.")
        if validation.is_valid is False:
            if getattr(self, "import_page", None):
                detail = (
                    validation.details.strip().splitlines()[0]
                    if validation.details and validation.details.strip()
                    else "Valideringen mot XSD feilet."
                )
                self.import_page.record_error(f"XSD-validering: {detail}")
            QMessageBox.warning(
                self,
                "XSD-validering feilet",
                validation.details or "Valideringen mot XSD feilet. Se Import-siden for detaljer.",
            )
        elif validation.is_valid is None and validation.details:
            QMessageBox.information(self, "XSD-validering", validation.details)

        if self.sales_ar_page:
            has_customer_data = (
                self._customer_sales is not None and not self._customer_sales.empty
            )
            self.sales_ar_page.set_controls_enabled(has_customer_data)
            self.sales_ar_page.clear_top_customers()
        if self.purchases_ap_page:
            has_supplier_data = (
                self._supplier_purchases is not None and not self._supplier_purchases.empty
            )
            self.purchases_ap_page.set_controls_enabled(has_supplier_data)
            self.purchases_ap_page.clear_top_suppliers()
        if self.cost_review_page:
            self.cost_review_page.set_vouchers(self._cost_vouchers)

        vesentlig_page = cast(Optional[SummaryPage], getattr(self, "vesentlig_page", None))
        if vesentlig_page:
            vesentlig_page.update_summary(self._saft_summary)
        regnskap_page = cast(Optional[RegnskapsanalysePage], getattr(self, "regnskap_page", None))
        if regnskap_page:
            fiscal_year = self._header.fiscal_year if self._header else None
            regnskap_page.set_dataframe(df, fiscal_year)
        sammenstilling_page = cast(
            Optional[SammenstillingsanalysePage], getattr(self, "sammenstilling_page", None)
        )
        if sammenstilling_page:
            fiscal_year = self._header.fiscal_year if self._header else None
            sammenstilling_page.set_dataframe(df, fiscal_year)
        brreg_status = self._process_brreg_result(result)

        self.btn_export.setEnabled(True)
        status_parts = [f"Datasett aktivt: {dataset_label or Path(result.file_path).name}."]
        if len(self._dataset_order) > 1:
            status_parts.append(f"{len(self._dataset_order)} filer tilgjengelig.")
        if brreg_status:
            status_parts.append(brreg_status)
        self.statusBar().showMessage(" ".join(status_parts))

    def _process_brreg_result(self, result: SaftLoadResult) -> str:
        """Oppdaterer interne strukturer med data fra Regnskapsregisteret."""

        self._industry = result.industry
        self._industry_error = result.industry_error
        if getattr(self, "import_page", None):
            self.import_page.update_industry(result.industry, result.industry_error)

        self._brreg_json = result.brreg_json
        self._brreg_map = result.brreg_map

        if result.brreg_json is None:
            self._update_comparison_tables(None)
            if result.brreg_error:
                error_text = str(result.brreg_error).strip()
                if "\n" in error_text:
                    error_text = error_text.splitlines()[0]
                message = f"Regnskapsregister: import feilet ({error_text})."
            elif result.header and result.header.orgnr:
                message = "Regnskapsregister: import feilet."
            else:
                message = "Regnskapsregister: ikke tilgjengelig (mangler org.nr.)."
            if getattr(self, "import_page", None):
                self.import_page.update_brreg_status(message)
                self.import_page.record_error(message)
            self._log_import_event(message)
            return message

        if not self._saft_summary:
            self._update_comparison_tables(None)
            message = "Regnskapsregister: import vellykket, men ingen SAF-T-oppsummering å sammenligne."
            if getattr(self, "import_page", None):
                self.import_page.update_brreg_status(message)
            self._log_import_event(message)
            return message

        comparison_rows = self._build_brreg_comparison_rows()
        self._update_comparison_tables(comparison_rows)
        message = "Regnskapsregister: import vellykket."
        if getattr(self, "import_page", None):
            self.import_page.update_brreg_status(message)
        self._log_import_event(message)
        return message

    def _update_comparison_tables(
        self,
        rows: Optional[Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]],
    ) -> None:
        """Oppdaterer tabellene som sammenligner SAF-T med Regnskapsregisteret."""

        self._latest_comparison_rows = list(rows) if rows is not None else None
        kontroll_page = cast(Optional[ComparisonPage], getattr(self, "kontroll_page", None))
        if kontroll_page:
            kontroll_page.update_comparison(rows)
        regnskap_page = cast(Optional[RegnskapsanalysePage], getattr(self, "regnskap_page", None))
        if regnskap_page:
            regnskap_page.update_comparison(rows)

    def _build_brreg_comparison_rows(
        self,
    ) -> Optional[List[Tuple[str, Optional[float], Optional[float], Optional[float]]]]:
        """Konstruerer rader for sammenligning mot Regnskapsregisteret."""

        if not self._saft_summary or not self._brreg_map:
            return None

        return [
            (
                "Driftsinntekter",
                self._saft_summary.get("driftsinntekter"),
                self._brreg_map.get("driftsinntekter"),
                None,
            ),
            (
                "EBIT",
                self._saft_summary.get("ebit"),
                self._brreg_map.get("ebit"),
                None,
            ),
            (
                "Årsresultat",
                self._saft_summary.get("arsresultat"),
                self._brreg_map.get("arsresultat"),
                None,
            ),
            (
                "Eiendeler (UB)",
                self._saft_summary.get("eiendeler_UB_brreg"),
                self._brreg_map.get("eiendeler_UB"),
                None,
            ),
            (
                "Egenkapital (UB)",
                self._saft_summary.get("egenkapital_UB"),
                self._brreg_map.get("egenkapital_UB"),
                None,
            ),
            (
                "Gjeld (UB)",
                self._saft_summary.get("gjeld_UB_brreg"),
                self._brreg_map.get("gjeld_UB"),
                None,
            ),
        ]

    def _on_load_error(self, message: str) -> None:
        self._finalize_loading("Feil ved lesing av SAF-T.")
        self._log_import_event(f"Feil ved lesing av SAF-T: {message}")
        if getattr(self, "import_page", None):
            self.import_page.record_error(f"Lesing av SAF-T: {message}")
        QMessageBox.critical(self, "Feil ved lesing av SAF-T", message)

    def _normalize_identifier(self, value: object) -> Optional[str]:
        if value is None:
            return None
        try:
            if pd.isna(value):  # type: ignore[arg-type]
                return None
        except Exception:
            pass
        text = str(value).strip()
        return text or None

    def _normalize_customer_key(self, value: object) -> Optional[str]:
        return self._normalize_identifier(value)

    def _normalize_supplier_key(self, value: object) -> Optional[str]:
        return self._normalize_identifier(value)

    def _ingest_customers(
        self, customers: Dict[str, "saft.CustomerInfo"]
    ) -> None:
        self._customers = {}
        self._cust_name_by_nr = {}
        self._cust_id_to_nr = {}
        for info in customers.values():
            name = (info.name or '').strip()
            raw_id = info.customer_id
            raw_number = info.customer_number or info.customer_id
            norm_id = self._normalize_customer_key(raw_id)
            norm_number = self._normalize_customer_key(raw_number)
            resolved_number = norm_number or norm_id or self._normalize_customer_key(raw_id)
            if not resolved_number and isinstance(raw_number, str) and raw_number.strip():
                resolved_number = raw_number.strip()
            if not resolved_number and isinstance(raw_id, str) and raw_id.strip():
                resolved_number = raw_id.strip()

            customer_key = norm_id or (raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None)
            if customer_key:
                self._customers[customer_key] = saft.CustomerInfo(
                    customer_id=customer_key,
                    customer_number=resolved_number or customer_key,
                    name=name,
                )

            keys = {
                raw_id,
                norm_id,
                raw_number,
                norm_number,
                resolved_number,
            }
            keys = {key for key in keys if isinstance(key, str) and key}

            if resolved_number:
                norm_resolved = self._normalize_customer_key(resolved_number)
                all_number_keys = set(keys)
                if norm_resolved:
                    all_number_keys.add(norm_resolved)
                all_number_keys.add(resolved_number)
                for key in all_number_keys:
                    norm_key = self._normalize_customer_key(key)
                    if norm_key:
                        self._cust_id_to_nr[norm_key] = resolved_number
                    self._cust_id_to_nr[key] = resolved_number

            if name:
                for key in keys:
                    norm_key = self._normalize_customer_key(key)
                    if norm_key:
                        self._cust_name_by_nr[norm_key] = name
                    self._cust_name_by_nr[key] = name

    def _ingest_suppliers(
        self, suppliers: Dict[str, "saft.SupplierInfo"]
    ) -> None:
        self._suppliers = {}
        self._sup_name_by_nr = {}
        self._sup_id_to_nr = {}
        for info in suppliers.values():
            name = (info.name or "").strip()
            raw_id = info.supplier_id
            raw_number = info.supplier_number or info.supplier_id
            norm_id = self._normalize_supplier_key(raw_id)
            norm_number = self._normalize_supplier_key(raw_number)
            resolved_number = norm_number or norm_id or self._normalize_supplier_key(raw_id)
            if not resolved_number and isinstance(raw_number, str) and raw_number.strip():
                resolved_number = raw_number.strip()
            if not resolved_number and isinstance(raw_id, str) and raw_id.strip():
                resolved_number = raw_id.strip()

            supplier_key = norm_id or (raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None)
            if supplier_key:
                self._suppliers[supplier_key] = saft.SupplierInfo(
                    supplier_id=supplier_key,
                    supplier_number=resolved_number or supplier_key,
                    name=name,
                )

            keys = {raw_id, norm_id, raw_number, norm_number, resolved_number}
            keys = {key for key in keys if isinstance(key, str) and key}

            if resolved_number:
                norm_resolved = self._normalize_supplier_key(resolved_number)
                all_number_keys = set(keys)
                if norm_resolved:
                    all_number_keys.add(norm_resolved)
                all_number_keys.add(resolved_number)
                for key in all_number_keys:
                    norm_key = self._normalize_supplier_key(key)
                    if norm_key:
                        self._sup_id_to_nr[norm_key] = resolved_number
                    self._sup_id_to_nr[key] = resolved_number

            if name:
                for key in keys:
                    norm_key = self._normalize_supplier_key(key)
                    if norm_key:
                        self._sup_name_by_nr[norm_key] = name
                    self._sup_name_by_nr[key] = name

    def _lookup_customer_name(self, number: object, customer_id: object) -> Optional[str]:
        number_key = self._normalize_customer_key(number)
        if number_key:
            name = self._cust_name_by_nr.get(number_key)
            if name:
                return name
        cid_key = self._normalize_customer_key(customer_id)
        if cid_key:
            info = self._customers.get(cid_key)
            if info and info.name:
                return info.name
            name = self._cust_name_by_nr.get(cid_key)
            if name:
                return name
        return None

    def _lookup_supplier_name(self, number: object, supplier_id: object) -> Optional[str]:
        number_key = self._normalize_supplier_key(number)
        if number_key:
            name = self._sup_name_by_nr.get(number_key)
            if name:
                return name
        sid_key = self._normalize_supplier_key(supplier_id)
        if sid_key:
            info = self._suppliers.get(sid_key)
            if info and info.name:
                return info.name
            name = self._sup_name_by_nr.get(sid_key)
            if name:
                return name
        return None

    def _safe_float(self, value: object) -> float:
        try:
            if pd.isna(value):  # type: ignore[arg-type]
                return 0.0
        except Exception:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _on_calc_top_customers(self, source: str, topn: int) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source  # kilde er alltid 3xxx-transaksjoner
        if self._customer_sales is None or self._customer_sales.empty:
            QMessageBox.information(
                self,
                "Ingen inntektslinjer",
                "Fant ingen inntektslinjer på 3xxx-konti i SAF-T-filen.",
            )
            return None
        data = self._customer_sales.copy()
        data = data.sort_values("Omsetning eks mva", ascending=False).head(topn)
        rows: List[Tuple[str, str, int, float]] = []
        for _, row in data.iterrows():
            number = row.get("Kundenr")
            number_text = self._normalize_customer_key(number)
            if not number_text and isinstance(number, str):
                number_text = number.strip() or None
            name = row.get("Kundenavn") or self._lookup_customer_name(number, number)
            count_val = row.get("Transaksjoner", 0)
            try:
                count_int = int(count_val)
            except (TypeError, ValueError):
                count_int = 0
            rows.append(
                (
                    number_text or "—",
                    (name or "").strip() or "—",
                    count_int,
                    self._safe_float(row.get("Omsetning eks mva")),
                )
            )
        self.statusBar().showMessage(f"Topp kunder (3xxx) beregnet. N={topn}.")
        return rows

    def _on_calc_top_suppliers(self, source: str, topn: int) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source  # kilde er alltid kostnadskonti
        if self._supplier_purchases is None or self._supplier_purchases.empty:
            QMessageBox.information(
                self,
                "Ingen innkjøpslinjer",
                "Fant ingen innkjøpslinjer på kostnadskonti (4xxx–8xxx) i SAF-T-filen.",
            )
            return None
        data = self._supplier_purchases.copy()
        data = data.sort_values("Innkjøp eks mva", ascending=False).head(topn)
        rows: List[Tuple[str, str, int, float]] = []
        for _, row in data.iterrows():
            number = row.get("Leverandørnr")
            number_text = self._normalize_supplier_key(number)
            if not number_text and isinstance(number, str):
                number_text = number.strip() or None
            name = row.get("Leverandørnavn") or self._lookup_supplier_name(number, number)
            count_val = row.get("Transaksjoner", 0)
            try:
                count_int = int(count_val)
            except (TypeError, ValueError):
                count_int = 0
            rows.append(
                (
                    number_text or "—",
                    (name or "").strip() or "—",
                    count_int,
                    self._safe_float(row.get("Innkjøp eks mva")),
                )
            )
        self.statusBar().showMessage(
            f"Innkjøp per leverandør (kostnadskonti 4xxx–8xxx) beregnet. N={topn}."
        )
        return rows

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
                if self._customer_sales is not None:
                    self._customer_sales.to_excel(writer, sheet_name="Sales_by_customer", index=False)
                if self._brreg_json:
                    pd.json_normalize(self._brreg_json).to_excel(writer, sheet_name="Brreg_JSON", index=False)
                if self._brreg_map:
                    map_df = pd.DataFrame(list(self._brreg_map.items()), columns=["Felt", "Verdi"])
                    map_df.to_excel(writer, sheet_name="Brreg_Mapping", index=False)
            self.statusBar().showMessage(f"Eksportert: {file_name}")
            self._log_import_event(f"Rapport eksportert: {Path(file_name).name}")
        except Exception as exc:  # pragma: no cover - vises i GUI
            self._log_import_event(f"Feil ved eksport: {exc}")
            QMessageBox.critical(self, "Feil ved eksport", str(exc))

    # endregion

    # region Navigasjon
    def _on_navigation_changed(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        if current is None:
            return
        key = current.data(0, Qt.UserRole)
        if not key:
            return
        widget = self._ensure_page(key)
        if widget is None:
            return
        self.stack.setCurrentWidget(widget)
        self.title_label.setText(current.text(0))
        if hasattr(self, "info_card"):
            self.info_card.setVisible(key in {"dashboard", "import"})
        self._schedule_responsive_update()

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
