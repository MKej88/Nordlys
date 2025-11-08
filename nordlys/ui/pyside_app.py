"""Oppstartspunkt for PySide6-applikasjonen til Nordlys."""
from __future__ import annotations

import sys
from typing import Tuple

from PySide6.QtWidgets import QApplication

from .adaptive_window import AdaptiveMainWindow


NordlysWindow = AdaptiveMainWindow


def create_app() -> Tuple[QApplication, AdaptiveMainWindow]:
    """Oppretter QApplication og hovedvindu."""

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = AdaptiveMainWindow()
    return app, window


def run_app(initial_size: Tuple[int, int] | None = (1400, 900)) -> int:
    """Starter GUI-et og returnerer Qt sin exit-kode."""

    app, window = create_app()
    if initial_size and not window.isVisible():
        width, height = initial_size
        window.resize(width, height)
    window.show()
    return app.exec()


def run() -> None:
    """Tidligere inngangspunkt som nå videresender til run_app."""

    sys.exit(run_app())


__all__ = ["AdaptiveMainWindow", "NordlysWindow", "create_app", "run", "run_app"]
