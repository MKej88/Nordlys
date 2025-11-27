"""Håndterer oppstartssekvensen for hovedvinduet."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow

from ..core.task_runner import TaskRunner
from .data_controller import SaftDataController
from .data_manager import SaftAnalytics, SaftDatasetStore
from .navigation_controller import NavigationController
from .page_manager import PageManager
from .page_registry import PageRegistry
from .responsive import ResponsiveLayoutController
from .window_initializers import (
    create_data_controller,
    create_dataset_services,
    initialize_pages,
    populate_navigation,
)


class StartupController:
    """Koordinerer deferred oppstart av datasett, sider og navigasjon."""

    def __init__(
        self,
        window: QMainWindow,
        header_bar,
        status_bar,
        nav_panel,
        stack,
        responsive: ResponsiveLayoutController,
        navigation: NavigationController,
        update_header_fields: Callable[[], None],
    ) -> None:
        self._window = window
        self._header_bar = header_bar
        self._status_bar = status_bar
        self._nav_panel = nav_panel
        self._stack = stack
        self._responsive = responsive
        self._navigation = navigation
        self._update_header_fields = update_header_fields
        self._startup_done = False
        self._startup_timer: Optional[QTimer] = None
        self._dataset_store: Optional[SaftDatasetStore] = None
        self._analytics: Optional[SaftAnalytics] = None
        self._task_runner: Optional[TaskRunner] = None
        self._data_controller: Optional[SaftDataController] = None
        self._page_manager: Optional[PageManager] = None
        self._page_registry: Optional[PageRegistry] = None

    @property
    def dataset_store(self) -> Optional[SaftDatasetStore]:
        return self._dataset_store

    @property
    def task_runner(self) -> Optional[TaskRunner]:
        return self._task_runner

    @property
    def data_controller(self) -> Optional[SaftDataController]:
        return self._data_controller

    def schedule_startup(self) -> None:
        if self._startup_done:
            return
        if self._startup_timer is None:
            self._startup_timer = QTimer(self._window)
            self._startup_timer.setSingleShot(True)
            self._startup_timer.timeout.connect(self._finish_startup)
        if not self._startup_timer.isActive():
            self._startup_timer.start(0)

    def ensure_startup_completed(self) -> None:
        if not self._startup_done:
            self._finish_startup()

    def _finish_startup(self) -> None:
        if self._startup_done:
            return
        if self._startup_timer is not None and self._startup_timer.isActive():
            self._startup_timer.stop()
        (
            self._dataset_store,
            self._analytics,
            self._task_runner,
        ) = create_dataset_services(self._window)
        self._data_controller = create_data_controller(
            dataset_store=self._dataset_store,
            analytics=self._analytics,
            header_bar=self._header_bar,
            status_bar=self._status_bar,
            parent=self._window,
            schedule_responsive_update=self._responsive.schedule_update,
            update_header_fields=self._update_header_fields,
        )
        self._navigation.update_data_context(
            self._dataset_store, self._data_controller
        )
        self._page_manager, self._page_registry = initialize_pages(
            self._window,
            self._stack,
            self._data_controller,
        )
        self._navigation.set_page_manager(self._page_manager)
        populate_navigation(self._nav_panel, self._navigation.handle_navigation_change)
        self._startup_done = True

    def get_startup_results(
        self,
    ) -> Tuple[
        Optional[SaftDatasetStore],
        Optional[SaftAnalytics],
        Optional[TaskRunner],
        Optional[SaftDataController],
        Optional[PageManager],
        Optional[PageRegistry],
    ]:
        return (
            self._dataset_store,
            self._analytics,
            self._task_runner,
            self._data_controller,
            self._page_manager,
            self._page_registry,
        )
