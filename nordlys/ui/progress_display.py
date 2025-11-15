"""Hjelpeklasse for å vise fremdrift i GUI-et."""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtWidgets import QLabel, QProgressBar, QWidget

from .widgets import TaskProgressDialog


class ImportProgressDisplay:
    """Samlet kontroll over statusetikett, fremdriftsbar og dialog."""

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._label: Optional[QLabel] = None
        self._bar: Optional[QProgressBar] = None
        self._dialog: Optional[TaskProgressDialog] = None
        self._files: List[str] = []

    def register_widgets(self, label: QLabel, progress_bar: QProgressBar) -> None:
        self._label = label
        self._bar = progress_bar

    def set_files(self, files: Sequence[str]) -> None:
        self._files = list(files)
        if self._dialog is not None:
            self._dialog.set_files(self._files)

    def show_progress(self, message: str, value: int) -> None:
        if self._label is not None:
            self._label.setText(message)
            self._label.setVisible(True)
        if self._bar is not None:
            clamped = max(0, min(100, int(value)))
            self._bar.setValue(clamped)
            self._bar.setVisible(True)
        self._update_dialog(message, value)

    def hide(self) -> None:
        if self._label is not None:
            self._label.clear()
            self._label.setVisible(False)
        if self._bar is not None:
            self._bar.setValue(0)
            self._bar.setVisible(False)
        self._close_dialog()

    def _ensure_dialog(self) -> TaskProgressDialog:
        if self._dialog is None:
            self._dialog = TaskProgressDialog(self._parent)
            self._dialog.set_files(self._files)
        return self._dialog

    def _update_dialog(self, message: str, value: int) -> None:
        dialog = self._ensure_dialog()
        dialog.update_status(message, value)
        if not dialog.isVisible():
            dialog.show()
        dialog.raise_()

    def _close_dialog(self) -> None:
        if self._dialog is None:
            return
        dialog = self._dialog
        self._dialog = None
        dialog.hide()
        dialog.deleteLater()
