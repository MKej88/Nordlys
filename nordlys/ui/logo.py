"""Enkel logo-komponent for navigasjonen.

Logoen tegnes med QPainter slik at vi slipper eksterne bildefiler. Den bruker
graderte farger som minner om nordlys og enkle buede streker for å gi et
distinkt, men lettvint uttrykk i sidepanelet.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy

__all__ = ["LogoWidget"]


class LogoWidget(QFrame):
    """Tegner Nordlys-logoen direkte i Qt.

    Widgeten har fast størrelse og gjennomsiktig bakgrunn slik at den passer
    inn i navigasjonspanelet uten ekstra padding eller filer.
    """

    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("logoBadge")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(96, 96)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:  # pragma: no cover - enkel Qt-størrelse
        return QSize(96, 96)

    def paintEvent(self, event: object) -> None:  # pragma: no cover - ren GUI
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        badge_rect = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        gradient = QLinearGradient(badge_rect.topLeft(), badge_rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#22d3ee"))
        gradient.setColorAt(0.5, QColor("#7c3aed"))
        gradient.setColorAt(1.0, QColor("#0ea5e9"))

        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 26, 26)

        glow_rect = badge_rect.adjusted(6, 6, -6, -6)
        painter.setBrush(QColor(255, 255, 255, 24))
        painter.drawRoundedRect(glow_rect, 22, 22)

        aurora_pen = QPen(QColor("#f8fafc"), 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(aurora_pen)
        painter.drawPath(self._aurora_path(badge_rect))

        accent_pen = QPen(QColor("#a5f3fc"), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(accent_pen)
        painter.drawPath(self._accent_path(badge_rect))

    def _aurora_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath(QPointF(rect.left() + 10, rect.bottom() - 26))
        control_y = rect.top() + rect.height() * 0.35
        path.cubicTo(
            QPointF(rect.left() + rect.width() * 0.3, control_y),
            QPointF(rect.left() + rect.width() * 0.55, control_y + 22),
            QPointF(rect.right() - 12, rect.top() + rect.height() * 0.45),
        )
        path.cubicTo(
            QPointF(rect.right() - 24, rect.top() + rect.height() * 0.62),
            QPointF(rect.left() + rect.width() * 0.35, rect.bottom() - 18),
            QPointF(rect.left() + 14, rect.bottom() - 16),
        )
        return path

    def _accent_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath(QPointF(rect.left() + 18, rect.top() + rect.height() * 0.38))
        path.cubicTo(
            QPointF(rect.left() + rect.width() * 0.32, rect.top() + rect.height() * 0.28),
            QPointF(rect.left() + rect.width() * 0.52, rect.top() + rect.height() * 0.36),
            QPointF(rect.right() - 18, rect.top() + rect.height() * 0.32),
        )
        path.cubicTo(
            QPointF(rect.right() - 26, rect.top() + rect.height() * 0.46),
            QPointF(rect.left() + rect.width() * 0.46, rect.top() + rect.height() * 0.52),
            QPointF(rect.left() + rect.width() * 0.28, rect.top() + rect.height() * 0.48),
        )
        return path
