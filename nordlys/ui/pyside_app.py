"""PySide6-basert GUI for Nordlys."""

from __future__ import annotations

import sys
from typing import Tuple, TYPE_CHECKING

import os

from PySide6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMainWindow

from ..saft.periods import format_header_period
from .import_export_manager import ImportExportManager
from .navigation_controller import NavigationController
from .startup_controller import StartupController
from .styles import APPLICATION_STYLESHEET
from .window_layout import WindowComponents
from .window_initializers import (
    configure_window_geometry,
    create_responsive_controller,
    setup_components,
)

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    from ..core.task_runner import TaskRunner
    from .data_controller import SaftDataController
    from .data_manager import SaftAnalytics, SaftDatasetStore
    from .page_manager import PageManager
    from .page_registry import PageRegistry


class NordlysWindow(QMainWindow):
    """Hovedvindu for PySide6-applikasjonen."""

    def __init__(self) -> None:
        super().__init__()
        configure_window_geometry(self)
        components = setup_components(self)
        self._bind_components(components)
        self._apply_styles()
        self._responsive = create_responsive_controller(
            self,
            self.stack,
            self._content_layout,
            self.nav_panel,
        )
        self._navigation = NavigationController(
            header_bar=self.header_bar,
            stack=self.stack,
            responsive=self._responsive,
            info_card=self.info_card,
        )
        self._startup = StartupController(
            window=self,
            header_bar=self.header_bar,
            status_bar=self.statusBar(),
            nav_panel=self.nav_panel,
            stack=self.stack,
            responsive=self._responsive,
            navigation=self._navigation,
            update_header_fields=self._update_header_fields,
        )
        self._import_manager = ImportExportManager(
            window=self,
            status_label=self._status_progress_label,
            status_progress_bar=self._status_progress_bar,
            startup=self._startup,
        )
        self.header_bar.open_requested.connect(self._import_manager.handle_open)
        self.header_bar.export_requested.connect(self._import_manager.handle_export)
        self.header_bar.export_pdf_requested.connect(
            self._import_manager.handle_export_pdf
        )

    def _bind_components(self, components: WindowComponents) -> None:
        self.nav_panel = components.nav_panel
        self._content_layout = components.content_layout
        self.header_bar = components.header_bar
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
        self._startup.schedule_startup()
        self._responsive.schedule_update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._responsive.schedule_update()

    # endregion

    # region Hjelpere
    def _update_header_fields(self) -> None:
        dataset_store = self._startup.dataset_store
        header = dataset_store.header if dataset_store is not None else None
        company = header.company_name if header else None
        orgnr = header.orgnr if header else None
        period = format_header_period(header) if header else None
        self.lbl_company.setText(f"Selskap: {company or '–'}")
        self.lbl_orgnr.setText(f"Org.nr: {orgnr or '–'}")
        self.lbl_period.setText(f"Periode: {period or '–'}")
    # endregion

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
