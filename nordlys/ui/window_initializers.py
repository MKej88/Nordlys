"""Hjelpefunksjoner for å sette opp hovedvinduet."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ScreenProfile:
    width: int
    height: int
    scale_factor: float


def detect_screen_profile() -> ScreenProfile:
    """Kartlegg skjermstørrelse og foreslå en skaleringsfaktor."""

    screen = QApplication.primaryScreen()
    if screen is None:
        return ScreenProfile(width=1460, height=940, scale_factor=1.0)

    available = screen.availableGeometry()
    width = available.width()
    height = available.height()

    if width <= 1500:
        scale_factor = 0.9
    elif width <= 1900:
        scale_factor = 0.95
    elif width >= 2500:
        scale_factor = 1.05
    else:
        scale_factor = 1.0

    return ScreenProfile(width=width, height=height, scale_factor=scale_factor)


def configure_window_geometry(window: QMainWindow) -> ScreenProfile:
    """Sett størrelse og tittel på hovedvinduet."""

    window.setWindowTitle(APP_TITLE)
    profile = detect_screen_profile()
    width = max(int(1100 * profile.scale_factor), int(profile.width * 0.82))
    height = max(int(720 * profile.scale_factor), int(profile.height * 0.82))
    window.resize(width, height)
    min_width = max(900, int(1024 * profile.scale_factor))
    min_height = max(620, int(680 * profile.scale_factor))
    window.setMinimumSize(min_width, min_height)
    window.setMaximumSize(16777215, 16777215)
    return profile


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
    scale_factor: float = 1.0,
) -> ResponsiveLayoutController:
    """Opprett controller som håndterer responsiv layout."""

    controller = ResponsiveLayoutController(
        window, stack, content_layout, nav_panel, scale_factor
    )
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
