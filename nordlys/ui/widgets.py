from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "TaskProgressDialog",
    "CardFrame",
    "EmptyStateWidget",
    "StatBadge",
]


class TaskProgressDialog(QDialog):
    """Lite hjelpevindu som viser fremdrift for bakgrunnsoppgaver."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setObjectName("taskProgressDialog")
        self.setWindowTitle("Laster data …")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(360)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(16, 16, 16, 16)

        container = QFrame(self)
        container.setObjectName("taskProgressPanel")
        container.setAttribute(Qt.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(container)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(15, 23, 42, 40))
        container.setGraphicsEffect(shadow)
        outer_layout.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(14)

        self._status_label = QLabel("Forbereder …")
        self._status_label.setObjectName("taskProgressTitle")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("taskProgressBar")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

        self._detail_label = QLabel()
        self._detail_label.setObjectName("taskProgressDetail")
        self._detail_label.setWordWrap(True)
        self._detail_label.setVisible(False)
        layout.addWidget(self._detail_label)

        layout.addStretch(1)

    def update_status(self, message: str, percent: int) -> None:
        text = message.strip() if message else ""
        self._status_label.setText(text or "Arbeid pågår …")
        clamped = max(0, min(100, int(percent)))
        self._progress_bar.setValue(clamped)

    def set_files(self, file_paths: Sequence[str]) -> None:
        if not file_paths:
            self._detail_label.clear()
            self._detail_label.setVisible(False)
            return
        names = [Path(path).name for path in file_paths]
        bullet_lines = "\n".join(f"• {name}" for name in names)
        self._detail_label.setText(f"Filer som lastes:\n{bullet_lines}")
        self._detail_label.setVisible(True)


class CardFrame(QFrame):
    """Visuelt kort med tittel og valgfritt innhold."""

    def __init__(self, title: str, subtitle: Optional[str] = None) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setAttribute(Qt.WA_StyledBackground, True)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(15, 23, 42, 32))
        self.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(0)
        layout.setSizeConstraint(QLayout.SetMinimumSize)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            subtitle_label.setContentsMargins(0, 4, 0, 0)
            layout.addWidget(subtitle_label)
            layout.addSpacing(8)
        else:
            layout.addSpacing(6)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(3)
        self.body_layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.addLayout(self.body_layout)

        self._has_body_stretch = True
        self.body_layout.addStretch(1)

    def _body_insert_index(self) -> int:
        if self._has_body_stretch and self.body_layout.count() > 0:
            return self.body_layout.count() - 1
        return self.body_layout.count()

    def _maybe_mark_expanding_widget(self, widget: QWidget) -> None:
        policy = widget.sizePolicy()
        vertical_policy = policy.verticalPolicy()
        if isinstance(widget, QLabel):
            return
        if vertical_policy in (
            QSizePolicy.Expanding,
            QSizePolicy.MinimumExpanding,
            QSizePolicy.Ignored,
        ):
            self.body_layout.setStretchFactor(widget, 100)

    def _maybe_mark_expanding_layout(
        self, sub_layout: QHBoxLayout | QVBoxLayout | QGridLayout
    ) -> None:
        if sub_layout.sizeConstraint() == QLayout.SetFixedSize:
            return
        if sub_layout.expandingDirections() & Qt.Vertical:
            self.body_layout.setStretchFactor(sub_layout, 100)

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.insertWidget(self._body_insert_index(), widget)
        self._maybe_mark_expanding_widget(widget)

    def add_layout(self, sub_layout: QHBoxLayout | QVBoxLayout | QGridLayout) -> None:
        self.body_layout.insertLayout(self._body_insert_index(), sub_layout)
        self._maybe_mark_expanding_layout(sub_layout)


class EmptyStateWidget(QFrame):
    """En vennlig tomtilstand som forklarer hva brukeren kan gjøre."""

    def __init__(self, title: str, description: str = "", icon: str = "🗂️") -> None:
        super().__init__()
        self.setObjectName("emptyState")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel(icon)
        self.icon_label.setObjectName("emptyStateIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("emptyStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.description_label = QLabel(description)
        self.description_label.setObjectName("emptyStateDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.description_label)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_description(self, description: str) -> None:
        self.description_label.setText(description)

    def set_icon(self, icon: str) -> None:
        self.icon_label.setText(icon)


class StatBadge(QFrame):
    """Kompakt komponent for presentasjon av et nøkkeltall."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        self.setObjectName("statBadge")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        layout.addWidget(self.title_label)

        self.value_label = QLabel("–")
        self.value_label.setObjectName("statValue")
        layout.addWidget(self.value_label)

        self.description_label = QLabel(description)
        self.description_label.setObjectName("statDescription")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
