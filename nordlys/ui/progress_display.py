"""Hjelpeklasse for å vise fremdrift i GUI-et."""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel, QProgressBar, QWidget

from .widgets import TaskProgressDialog


class _ProgressAnimator(QObject):
    """Gir fremdriftsbaren en jevn og aldri-stoppende animasjon."""

    def __init__(self, on_value_changed: Callable[[int], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._on_value_changed = on_value_changed
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._on_tick)
        self._display_value = 0
        self._reported_target = 0
        self._floating_target = 0
        self._last_report_time = time.monotonic()
        self._idle_seconds = 1.6

    def report_progress(self, percent: int) -> None:
        clamped = max(0, min(100, int(percent)))
        if clamped > self._reported_target:
            self._reported_target = clamped
            self._floating_target = max(self._floating_target, clamped)
        if clamped == 100:
            self._floating_target = 100
        self._last_report_time = time.monotonic()
        if self._display_value == 0 and clamped == 0:
            self._on_value_changed(0)
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._display_value = 0
        self._reported_target = 0
        self._floating_target = 0
        self._last_report_time = time.monotonic()

    def _on_tick(self) -> None:
        if self._floating_target < 99 and self._should_increase_floating_target():
            self._floating_target = min(99, self._floating_target + 1)

        target = max(self._floating_target, self._reported_target)
        if target == 0 and self._display_value == 0:
            self._timer.stop()
            return
        if self._display_value >= target:
            if target >= 100:
                self._timer.stop()
            return

        step = max(1, (target - self._display_value) // 4)
        self._display_value = min(target, self._display_value + step)
        self._on_value_changed(self._display_value)

        if self._display_value >= 100:
            self._timer.stop()

    def _should_increase_floating_target(self) -> bool:
        return (time.monotonic() - self._last_report_time) > self._idle_seconds


class ImportProgressDisplay:
    """Samlet kontroll over statusetikett, fremdriftsbar og dialog."""

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._label: Optional[QLabel] = None
        self._bar: Optional[QProgressBar] = None
        self._dialog: Optional[TaskProgressDialog] = None
        self._files: List[str] = []
        self._last_message: str = "Laster data …"
        self._animator = _ProgressAnimator(self._apply_progress, parent)

    def register_widgets(self, label: QLabel, progress_bar: QProgressBar) -> None:
        self._label = label
        self._bar = progress_bar

    def set_files(self, files: Sequence[str]) -> None:
        self._files = list(files)
        if self._dialog is not None:
            self._dialog.set_files(self._files)

    def show_progress(self, message: str, value: int) -> None:
        clean_message = message.strip() if message else ""
        self._last_message = clean_message or "Laster data …"
        if self._label is not None:
            self._label.setText(self._last_message)
            self._label.setVisible(True)
        if self._bar is not None:
            self._bar.setVisible(True)
        self._animator.report_progress(value)

    def hide(self) -> None:
        self._animator.stop()
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

    def _apply_progress(self, value: int) -> None:
        if self._label is not None:
            self._label.setText(self._last_message)
            self._label.setVisible(True)
        if self._bar is not None:
            self._bar.setValue(value)
            self._bar.setVisible(True)
        self._update_dialog(value)

    def _update_dialog(self, value: int) -> None:
        dialog = self._ensure_dialog()
        dialog.update_status(self._last_message, value)
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
