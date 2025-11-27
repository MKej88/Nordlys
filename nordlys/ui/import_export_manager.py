"""Håndterer import/eksport-knapper for hovedvinduet."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMainWindow, QWidget

from .import_export import ImportExportController
from .startup_controller import StartupController
from .window_initializers import create_import_controller


class ImportExportManager:
    """Sørger for at import/eksport-kontrolleren opprettes når den trengs."""

    def __init__(
        self,
        window: QMainWindow,
        status_label: QWidget,
        status_progress_bar: QWidget,
        startup: StartupController,
    ) -> None:
        self._window = window
        self._status_label = status_label
        self._status_progress_bar = status_progress_bar
        self._startup = startup
        self._controller: Optional[ImportExportController] = None

    def handle_open(self) -> None:
        controller = self._ensure_controller()
        controller.handle_open()

    def handle_export(self) -> None:
        controller = self._ensure_controller()
        controller.handle_export()

    def handle_export_pdf(self) -> None:
        controller = self._ensure_controller()
        controller.handle_export_pdf()

    def _ensure_controller(self) -> ImportExportController:
        self._startup.ensure_startup_completed()
        dataset_store = self._startup.dataset_store
        task_runner = self._startup.task_runner
        data_controller = self._startup.data_controller
        if dataset_store is None or task_runner is None or data_controller is None:
            raise RuntimeError("Importkontrolleren kan ikke opprettes ennå.")
        if self._controller is None:
            controller = create_import_controller(
                self._window,
                dataset_store,
                task_runner,
                data_controller,
            )
            controller.register_status_widgets(
                self._status_label, self._status_progress_bar
            )
            self._controller = controller
        return self._controller
