"""Håndterer navigasjon og datasettsvitsjing i hovedvinduet."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from .data_controller import SaftDataController
from .data_manager import SaftDatasetStore
from .page_manager import PageManager
from .responsive import ResponsiveLayoutController


class NavigationController:
    """Koordinerer navigasjonshendelser og datasettskifter."""

    def __init__(
        self,
        header_bar,
        stack,
        responsive: ResponsiveLayoutController,
        info_card=None,
    ) -> None:
        self._header_bar = header_bar
        self._stack = stack
        self._responsive = responsive
        self._info_card = info_card
        self._page_manager: Optional[PageManager] = None
        self._dataset_store: Optional[SaftDatasetStore] = None
        self._data_controller: Optional[SaftDataController] = None
        header_bar.dataset_changed.connect(self._on_dataset_changed)

    def set_page_manager(self, page_manager: PageManager) -> None:
        """Oppdater referansen slik at navigasjon kan laste sider."""

        self._page_manager = page_manager

    def update_data_context(
        self, dataset_store: SaftDatasetStore, data_controller: SaftDataController
    ) -> None:
        """Lagrer datastrukturer som trengs for sidebytte og dataskifte."""

        self._dataset_store = dataset_store
        self._data_controller = data_controller

    def connect_navigation(self, nav_panel) -> None:
        """Koble navigasjonstreet til controllerens hendelser."""

        nav_panel.currentItemChanged.connect(self.handle_navigation_change)

    def handle_navigation_change(
        self,
        current: Optional[QTreeWidgetItem],
        previous: Optional[QTreeWidgetItem],
    ) -> None:
        """Offentlig inngang for signalet fra navigasjonen."""

        self._on_navigation_changed(current, previous)

    def _on_dataset_changed(self, key: str) -> None:
        if not isinstance(key, str):
            return
        if self._data_controller is None or self._dataset_store is None:
            return
        if key == self._dataset_store.current_key:
            return
        self._data_controller.activate_dataset(key)

    def _on_navigation_changed(
        self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]
    ) -> None:
        if self._page_manager is None or current is None:
            return
        key = current.data(0, Qt.UserRole)
        if not key:
            return
        widget = self._page_manager.ensure_page(key)
        if widget is None:
            return
        self._stack.setCurrentWidget(widget)
        self._header_bar.set_title(current.text(0))
        if self._info_card is not None:
            self._info_card.setVisible(key in {"dashboard", "import"})
        self._responsive.schedule_update()
