"""PySide6-basert GUI for Nordlys."""

from __future__ import annotations

import sys
from typing import Optional, Tuple

import os

from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMainWindow, QTreeWidgetItem

from ..saft.periods import format_header_period
from .import_export import ImportExportController
from .styles import APPLICATION_STYLESHEET
from .window_layout import WindowComponents
from .window_initializers import (
    configure_window_geometry,
    create_data_controller,
    create_dataset_services,
    create_import_controller,
    create_responsive_controller,
    initialize_pages,
    populate_navigation,
    setup_components,
)


class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        configure_window_geometry(self)
        (
            self._dataset_store,
            self._analytics,
            self._task_runner,
        ) = create_dataset_services(self)
        components = setup_components(self)
        self._bind_components(components)
        self._apply_styles()
        self._responsive = create_responsive_controller(
            self,
            self.stack,
            self._content_layout,
            self.nav_panel,
        )
        self._data_controller = create_data_controller(
            dataset_store=self._dataset_store,
            analytics=self._analytics,
            header_bar=self.header_bar,
            status_bar=self.statusBar(),
            parent=self,
            schedule_responsive_update=self._responsive.schedule_update,
            update_header_fields=self._update_header_fields,
        )
        self._page_manager, self._page_registry = initialize_pages(
            self,
            self.stack,
            self._data_controller,
        )
        populate_navigation(self.nav_panel, self._on_navigation_changed)
        self._import_controller: Optional[ImportExportController] = None
        self.header_bar.open_requested.connect(self._handle_open_requested)
        self.header_bar.export_requested.connect(self._handle_export_requested)
        self.header_bar.export_pdf_requested.connect(self._handle_export_pdf_requested)

    def _bind_components(self, components: WindowComponents) -> None:
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
        company = header.company_name if header else None
        orgnr = header.orgnr if header else None
        period = format_header_period(header) if header else None
        self.lbl_company.setText(f"Selskap: {company or '–'}")
        self.lbl_orgnr.setText(f"Org.nr: {orgnr or '–'}")
        self.lbl_period.setText(f"Periode: {period or '–'}")

    def _ensure_import_controller(self) -> ImportExportController:
        if self._import_controller is None:
            controller = create_import_controller(
                self,
                self._dataset_store,
                self._task_runner,
                self._data_controller,
            )
            controller.register_status_widgets(
                self._status_progress_label, self._status_progress_bar
            )
            self._import_controller = controller
        return self._import_controller

    def _handle_open_requested(self) -> None:
        controller = self._ensure_import_controller()
        controller.handle_open()

    def _handle_export_requested(self) -> None:
        controller = self._ensure_import_controller()
        controller.handle_export()

    def _handle_export_pdf_requested(self) -> None:
        controller = self._ensure_import_controller()
        controller.handle_export_pdf()

    # endregion


def create_app() -> Tuple[QApplication, NordlysWindow]:
    """Fabrikkfunksjon for å opprette QApplication og hovedvindu."""
    app = QApplication.instance()
    _install_qt_warning_filter()
    if app is None:
        # Enkel failsafe: tving programvaren til å bruke raster-basert renderering
        # i tilfeller der GPU-driver eller OpenGL skaper problemer.
        os.environ.setdefault("QT_OPENGL", "software")
        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
        app = QApplication(sys.argv)
    window = NordlysWindow()
    return app, window


def _install_qt_warning_filter() -> None:
    """Fjerner støyende QPainter-advarsler fra konsollen."""

    ignored = (
        "qpaint device returned engine",
        "painter not active",
    )

    def _handler(
        _mode: QtMsgType,
        _context,  # type: ignore[override]
        message: str,
    ) -> None:
        if any(fragment in message.lower() for fragment in ignored):
            return
        sys.stderr.write(f"{message}\n")

    try:
        qInstallMessageHandler(_handler)  # type: ignore[arg-type]
    except Exception:
        return


def run() -> None:
    """Start GUI-applikasjonen."""

    app, window = create_app()
    window.show()
    sys.exit(app.exec())
