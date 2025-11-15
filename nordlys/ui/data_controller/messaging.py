"""Håndterer statusmeldinger til bruker og importloggen."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .context import ControllerContext


class ImportMessenger:
    """Sender meldinger til statuslinjen og importfanen."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def log_import_event(self, message: str, *, reset: bool = False) -> None:
        page = self._context.pages.import_page
        if not page:
            return
        if reset:
            page.reset_log()
            page.reset_errors()
        page.append_log(message)

    def record_import_error(self, message: str) -> None:
        page = self._context.pages.import_page
        if page:
            page.record_error(message)

    def handle_load_error(self, message: str) -> None:
        self.log_import_event(f"Feil ved lesing av SAF-T: {message}")
        self.record_import_error(f"Lesing av SAF-T: {message}")
        QMessageBox.critical(self._context.parent, "Feil ved lesing av SAF-T", message)
