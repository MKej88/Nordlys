from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QStyledItemDelegate

__all__ = [
    "TOP_BORDER_ROLE",
    "BOTTOM_BORDER_ROLE",
    "CompactRowDelegate",
    "AnalysisTableDelegate",
]

TOP_BORDER_ROLE = Qt.UserRole + 41
BOTTOM_BORDER_ROLE = Qt.UserRole + 42


class CompactRowDelegate(QStyledItemDelegate):
    """Gir tabellrader som krymper rundt innholdet."""

    def sizeHint(self, option, index):  # type: ignore[override]
        hint = super().sizeHint(option, index)
        metrics = option.fontMetrics
        if metrics is None:
            return hint

        text = index.data(Qt.DisplayRole)
        if isinstance(text, str) and text:
            lines = text.splitlines() or [""]
            content_height = metrics.height() * len(lines)
        else:
            content_height = metrics.height()

        desired_height = max(12, content_height + 2)
        if hint.height() > desired_height:
            hint.setHeight(desired_height)
        else:
            hint.setHeight(max(hint.height(), desired_height))
        return hint


class AnalysisTableDelegate(CompactRowDelegate):
    """Tegner egendefinerte grenser for analysene."""

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        super().paint(painter, option, index)
        if index.data(TOP_BORDER_ROLE):
            painter.save()
            pen = QPen(QColor(15, 23, 42))
            pen.setWidth(2)
            painter.setPen(pen)
            rect = option.rect
            painter.drawLine(rect.topLeft(), rect.topRight())
            painter.restore()
        if index.data(BOTTOM_BORDER_ROLE):
            painter.save()
            pen = QPen(QColor(15, 23, 42))
            pen.setWidth(2)
            painter.setPen(pen)
            rect = option.rect
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            painter.restore()
