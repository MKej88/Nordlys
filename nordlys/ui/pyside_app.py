"""PySide6-basert GUI for Nordlys."""

from __future__ import annotations

import sys
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
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
from .data_controller import SaftDataController
from .data_manager import SaftAnalytics, SaftDatasetStore
from .header_bar import HeaderBar
from .import_export import ImportExportController
from .navigation import NavigationPanel
from .pages import (
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
from .page_manager import PageManager
from .responsive import ResponsiveLayoutController
from .styles import APPLICATION_STYLESHEET
from .widgets import CardFrame

TOP_BORDER_ROLE = Qt.UserRole + 41
BOTTOM_BORDER_ROLE = Qt.UserRole + 42


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

        self._dataset_store = SaftDatasetStore()
        self._analytics = SaftAnalytics(self._dataset_store)

        self._task_runner = TaskRunner(self)

        self._status_progress_label: Optional[QLabel] = None
        self._status_progress_bar: Optional[QProgressBar] = None

        self._navigation_initialized = False
        self._content_layout: Optional[QVBoxLayout] = None

        self._setup_ui()
        self._apply_styles()

        self._responsive = ResponsiveLayoutController(
            self,
            self.stack,
            self._content_layout,
            self.nav_panel,
        )
        self.stack.currentChanged.connect(lambda _: self._responsive.schedule_update())

        self._data_controller = SaftDataController(
            dataset_store=self._dataset_store,
            analytics=self._analytics,
            header_bar=self.header_bar,
            status_bar=self.statusBar(),
            parent=self,
            schedule_responsive_update=self._responsive.schedule_update,
            update_header_fields=self._update_header_fields,
        )

        self._page_manager = PageManager(
            self,
            self.stack,
            self._data_controller.apply_page_state,
        )

        self._create_pages()

        self._import_controller = ImportExportController(
            parent=self,
            data_manager=self._dataset_store,
            task_runner=self._task_runner,
            apply_results=self._data_controller.apply_saft_batch,
            set_loading_state=self._data_controller.set_loading_state,
            status_callback=self.statusBar().showMessage,
            log_import_event=self._data_controller.log_import_event,
            load_error_handler=self._data_controller.on_load_error,
        )
        if self._status_progress_label and self._status_progress_bar:
            self._import_controller.register_status_widgets(
                self._status_progress_label, self._status_progress_bar
            )
        self.header_bar.open_requested.connect(self._import_controller.handle_open)
        self.header_bar.export_requested.connect(self._import_controller.handle_export)

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

        self.header_bar = HeaderBar()
        self.header_bar.dataset_changed.connect(self._on_dataset_changed)
        content_layout.addWidget(self.header_bar)

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
        self._page_manager.register_page("import", import_page, attr="import_page")

        self._page_manager.register_lazy_page(
            "dashboard", self._build_dashboard_page, attr="dashboard_page"
        )
        self._page_manager.register_lazy_page(
            "plan.saldobalanse",
            self._build_saldobalanse_page,
            attr="saldobalanse_page",
        )
        self._page_manager.register_lazy_page(
            "plan.kontroll",
            self._build_kontroll_page,
            attr="kontroll_page",
        )
        self._page_manager.register_lazy_page(
            "plan.regnskapsanalyse",
            self._build_regnskap_page,
            attr="regnskap_page",
        )
        self._page_manager.register_lazy_page(
            "plan.vesentlighet",
            self._build_vesentlig_page,
            attr="vesentlig_page",
        )
        self._page_manager.register_lazy_page(
            "plan.sammenstilling",
            self._build_sammenstilling_page,
            attr="sammenstilling_page",
        )

        revision_definitions = {
            "rev.innkjop": (
                "Innkjøp og leverandørgjeld",
                "Fokuser på varekjøp, kredittider og periodisering.",
            ),
            "rev.lonn": (
                "Lønn",
                "Kontroll av lønnskjøringer, skatt og arbeidsgiveravgift.",
            ),
            "rev.kostnad": ("Kostnad", "Analyse av driftskostnader og periodisering."),
            "rev.driftsmidler": (
                "Driftsmidler",
                "Verifikasjon av investeringer og avskrivninger.",
            ),
            "rev.finans": (
                "Finans og likvid",
                "Bank, finansielle instrumenter og kontantstrøm.",
            ),
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
                self._page_manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_sales_page(
                        title, subtitle
                    ),
                    attr="sales_ar_page",
                )
            elif key == "rev.innkjop":
                self._page_manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_purchases_page(
                        title, subtitle
                    ),
                    attr="purchases_ap_page",
                )
            elif key == "rev.kostnad":
                self._page_manager.register_lazy_page(
                    key,
                    lambda title=title, subtitle=subtitle: self._build_cost_page(
                        title, subtitle
                    ),
                    attr="cost_review_page",
                )
            else:
                self._page_manager.register_lazy_page(
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

    def _build_dashboard_page(self) -> "DashboardPage":
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

    def _build_regnskap_page(self) -> "RegnskapsanalysePage":
        return RegnskapsanalysePage()

    def _build_vesentlig_page(self) -> SummaryPage:
        return SummaryPage(
            "Vesentlighetsvurdering",
            "Nøkkeltall som understøtter fastsettelse av vesentlighetsgrenser.",
        )

    def _build_sammenstilling_page(self) -> "SammenstillingsanalysePage":
        return SammenstillingsanalysePage()

    def _build_sales_page(self, title: str, subtitle: str) -> SalesArPage:
        return SalesArPage(title, subtitle, self._data_controller.on_calc_top_customers)

    def _build_purchases_page(self, title: str, subtitle: str) -> "PurchasesApPage":
        return PurchasesApPage(
            title, subtitle, self._data_controller.on_calc_top_suppliers
        )

    def _build_cost_page(self, title: str, subtitle: str) -> "CostVoucherReviewPage":
        return CostVoucherReviewPage(title, subtitle)

    def _build_checklist_page(
        self, _key: str, title: str, subtitle: str
    ) -> ChecklistPage:
        return ChecklistPage(title, subtitle)

    def _apply_styles(self) -> None:
        self.setStyleSheet(APPLICATION_STYLESHEET)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._responsive.schedule_update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._responsive.schedule_update()

    # endregion

    # region Datasett
    def _on_dataset_changed(self, key: str) -> None:
        if not isinstance(key, str):
            return
        if key == self._dataset_store.current_key:
            return
        self._data_controller.activate_dataset(key)

    # endregion

    # region Navigasjon
    def _on_navigation_changed(
        self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]
    ) -> None:
        if current is None:
            return
        key = current.data(0, Qt.UserRole)
        if not key:
            return
        widget = self._page_manager.ensure_page(key)
        if widget is None:
            return
        self.stack.setCurrentWidget(widget)
        self.header_bar.set_title(current.text(0))
        if hasattr(self, "info_card"):
            self.info_card.setVisible(key in {"dashboard", "import"})
        self._responsive.schedule_update()

    # endregion

    # region Hjelpere
    def _update_header_fields(self) -> None:
        header = self._dataset_store.header
        if not header:
            return
        self.lbl_company.setText(f"Selskap: {header.company_name or '–'}")
        self.lbl_orgnr.setText(f"Org.nr: {header.orgnr or '–'}")
        per = f"{header.fiscal_year or '–'} P{header.period_start or '?'}–P{header.period_end or '?'}"
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
