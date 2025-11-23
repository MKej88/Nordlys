from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - miljøavhengig
    pytestmark = pytest.mark.skip(reason=f"PySide6 er utilgjengelig: {exc}")
    QIcon = None  # type: ignore[assignment]
    QApplication = None  # type: ignore[assignment]


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_logo_icon_is_available(qt_app: QApplication) -> None:
    icon_path = (
        Path(__file__).resolve().parents[1]
        / "nordlys"
        / "resources"
        / "icons"
        / "nordlys-logo.svg"
    )
    assert icon_path.exists()

    icon = QIcon(str(icon_path))
    assert not icon.isNull()

    pixmap = icon.pixmap(48, 48)
    assert not pixmap.isNull()
