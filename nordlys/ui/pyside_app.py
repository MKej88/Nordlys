"""PySide6-basert GUI for Nordlys."""

from __future__ import annotations

import sys
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QTreeWidgetItem

try:
    from PySide6.QtWidgets import QWIDGETSIZE_MAX
except ImportError:  # PySide6 < 6.7
    QWIDGETSIZE_MAX = 16777215

from ..constants import APP_TITLE
from ..core.task_runner import TaskRunner
from .data_controller import SaftDataController
from .data_manager import SaftAnalytics, SaftDatasetStore
from .import_export import ImportExportController
from .page_manager import PageManager
from .page_registry import PageRegistry
from .navigation_builder import NavigationBuilder
from .responsive import ResponsiveLayoutController
from .styles import APPLICATION_STYLESHEET
from .window_layout import WindowComponents, setup_main_window

class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        self._init_window_geometry()
        self._init_data_services()
        self._init_ui_components()
        self._apply_styles()
        self._init_responsive_controller()
        self._init_data_controller()
        self._init_page_system()
        self._init_import_export()

    def _init_window_geometry(self) -> None:
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

    def _init_data_services(self) -> None:
        self._dataset_store = SaftDatasetStore()
        self._analytics = SaftAnalytics(self._dataset_store)
        self._task_runner = TaskRunner(self)

    def _init_ui_components(self) -> None:
        components: WindowComponents = setup_main_window(self)
        self.nav_panel = components.nav_panel
        self._content_layout = components.content_layout
        self.header_bar = components.header_bar
        self.header_bar.dataset_changed.connect(self._on_dataset_changed)
        self.info_card = components.info_card
        self.lbl_company = components.lbl_company
        self.lbl_orgnr = components.lbl_orgnr
        self.lbl_period = components.lbl_period
        self.stack = components.stack
        self._status_progress_label = components.progress_label
        self._status_progress_bar = components.progress_bar

    def _init_responsive_controller(self) -> None:
        self._responsive = ResponsiveLayoutController(
            self,
            self.stack,
            self._content_layout,
            self.nav_panel,
        )
        self.stack.currentChanged.connect(lambda _: self._responsive.schedule_update())

    def _init_data_controller(self) -> None:
        self._data_controller = SaftDataController(
            dataset_store=self._dataset_store,
            analytics=self._analytics,
            header_bar=self.header_bar,
            status_bar=self.statusBar(),
            parent=self,
            schedule_responsive_update=self._responsive.schedule_update,
            update_header_fields=self._update_header_fields,
        )

    def _init_page_system(self) -> None:
        self._page_manager = PageManager(
            self,
            self.stack,
            self._data_controller.apply_page_state,
        )
        self._page_registry = PageRegistry(self._page_manager, self._data_controller)
        self._page_registry.register_all()
        NavigationBuilder(self.nav_panel).populate(self._on_navigation_changed)

    def _init_import_export(self) -> None:
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
        self._import_controller.register_status_widgets(
            self._status_progress_label, self._status_progress_bar
        )
        self.header_bar.open_requested.connect(self._import_controller.handle_open)
        self.header_bar.export_requested.connect(self._import_controller.handle_export)

    # region UI
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
