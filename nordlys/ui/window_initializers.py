"""Hjelpefunksjoner for å sette opp hovedvinduet."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from PySide6.QtWidgets import QApplication, QMainWindow, QStatusBar, QTreeWidgetItem

from ..constants import APP_TITLE
from ..core.task_runner import TaskRunner
from .data_controller import SaftDataController
from .data_manager import SaftAnalytics, SaftDatasetStore
from .import_export import ImportExportController
from .navigation_builder import NavigationBuilder
from .page_manager import PageManager
from .page_registry import PageRegistry
from .responsive import ResponsiveLayoutController
from .window_layout import WindowComponents, setup_main_window


def configure_window_geometry(window: QMainWindow) -> None:
    """Sett størrelse og tittel på hovedvinduet."""

    window.setWindowTitle(APP_TITLE)
    screen = QApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        width = max(1100, int(available.width() * 0.82))
        height = max(720, int(available.height() * 0.82))
        window.resize(width, height)
    else:
        window.resize(1460, 940)
    window.setMinimumSize(1024, 680)
    window.setMaximumSize(16777215, 16777215)


def create_dataset_services(
    parent: QMainWindow,
) -> Tuple[SaftDatasetStore, SaftAnalytics, TaskRunner]:
    """Opprett datastrukturer og bakgrunnsarbeider."""

    dataset_store = SaftDatasetStore()
    analytics = SaftAnalytics(dataset_store)
    task_runner = TaskRunner(parent)
    return dataset_store, analytics, task_runner


def setup_components(window: QMainWindow) -> WindowComponents:
    """Bygg hovedvinduets komponenter."""

    return setup_main_window(window)


def create_responsive_controller(
    window: QMainWindow,
    stack,
    content_layout,
    nav_panel,
) -> ResponsiveLayoutController:
    """Opprett controller som håndterer responsiv layout."""

    controller = ResponsiveLayoutController(window, stack, content_layout, nav_panel)
    stack.currentChanged.connect(lambda _: controller.schedule_update())
    return controller


def create_data_controller(
    dataset_store: SaftDatasetStore,
    analytics: SaftAnalytics,
    header_bar,
    status_bar: QStatusBar,
    parent: QMainWindow,
    schedule_responsive_update: Callable[[], None],
    update_header_fields: Callable[[], None],
) -> SaftDataController:
    """Sett opp datakontrolleren for hovedvinduet."""

    return SaftDataController(
        dataset_store=dataset_store,
        analytics=analytics,
        header_bar=header_bar,
        status_bar=status_bar,
        parent=parent,
        schedule_responsive_update=schedule_responsive_update,
        update_header_fields=update_header_fields,
    )


def initialize_pages(
    window: QMainWindow,
    stack,
    data_controller: SaftDataController,
) -> Tuple[PageManager, PageRegistry]:
    """Opprett og registrer alle sidene i applikasjonen."""

    page_manager = PageManager(window, stack, data_controller.apply_page_state)
    page_registry = PageRegistry(page_manager, data_controller)
    page_registry.register_all()
    return page_manager, page_registry


def populate_navigation(
    nav_panel,
    callback: Callable[[Optional[QTreeWidgetItem], Optional[QTreeWidgetItem]], None],
) -> None:
    """Fyll navigasjonen med alle registrerte sider."""

    NavigationBuilder(nav_panel).populate(callback)


def create_import_controller(
    window: QMainWindow,
    dataset_store: SaftDatasetStore,
    task_runner: TaskRunner,
    data_controller: SaftDataController,
) -> ImportExportController:
    """Lag en import/eksport-kontroller for hovedvinduet."""

    controller = ImportExportController(
        parent=window,
        data_manager=dataset_store,
        task_runner=task_runner,
        apply_results=data_controller.apply_saft_batch,
        set_loading_state=data_controller.set_loading_state,
        status_callback=window.statusBar().showMessage,
        log_import_event=data_controller.log_import_event,
        load_error_handler=data_controller.on_load_error,
    )
    return controller
