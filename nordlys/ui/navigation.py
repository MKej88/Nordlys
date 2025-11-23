"""Reusable navigasjonskomponenter for Nordlys sitt UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .config import PRIMARY_UI_FONT_FAMILY, icon_for_navigation

__all__ = ["NavigationItem", "NavigationPanel"]

LOGO_ICON_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "icons" / "nordlys-logo.svg"
)


@dataclass
class NavigationItem:
    """Knytter en unik nøkkel til et ttk-element i navigasjonen."""

    key: str
    item: QTreeWidgetItem


class NavigationPanel(QFrame):
    """Sidepanel med navigasjonstreet som brukes av hovedvinduet."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("navPanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setMinimumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(24)

        logo_container = self._create_logo_section()
        layout.addWidget(logo_container)

        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(12)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setTextElideMode(Qt.ElideNone)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.tree, 1)

    def add_root(self, title: str, key: str | None = None) -> NavigationItem:
        item = QTreeWidgetItem([title])
        if key:
            item.setData(0, Qt.UserRole, key)
            font = item.font(0)
            font.setFamily(PRIMARY_UI_FONT_FAMILY)
            font.setPointSize(font.pointSize() + 1)
            font.setWeight(QFont.DemiBold)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#f8fafc")))
            icon = icon_for_navigation(key)
            if icon:
                item.setIcon(0, icon)
        else:
            font = item.font(0)
            font.setFamily(PRIMARY_UI_FONT_FAMILY)
            font.setPointSize(max(font.pointSize() - 1, 9))
            font.setWeight(QFont.DemiBold)
            font.setCapitalization(QFont.AllUppercase)
            font.setLetterSpacing(QFont.PercentageSpacing, 115)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#94a3b8")))
            item.setFlags(
                item.flags()
                & ~Qt.ItemIsSelectable
                & ~Qt.ItemIsDragEnabled
                & ~Qt.ItemIsDropEnabled
            )
        self.tree.addTopLevelItem(item)
        self.tree.expandItem(item)
        return NavigationItem(key or title.lower(), item)

    def add_child(self, parent: NavigationItem, title: str, key: str) -> NavigationItem:
        item = QTreeWidgetItem([title])
        item.setData(0, Qt.UserRole, key)
        font = item.font(0)
        font.setFamily(PRIMARY_UI_FONT_FAMILY)
        font.setWeight(QFont.Medium)
        item.setFont(0, font)
        item.setForeground(0, QBrush(QColor("#e2e8f0")))
        icon = icon_for_navigation(key)
        if icon:
            item.setIcon(0, icon)
        parent.item.addChild(item)
        parent.item.setExpanded(True)
        return NavigationItem(key, item)

    def _create_logo_section(self) -> QFrame:
        logo_frame = QFrame()
        logo_frame.setObjectName("logoContainer")
        logo_layout = QHBoxLayout(logo_frame)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(12)

        logo_icon = QLabel()
        logo_icon.setObjectName("logoMark")
        logo_icon.setFixedSize(44, 44)

        icon = self._load_logo_icon()
        if icon:
            logo_icon.setPixmap(icon.pixmap(44, 44))
            logo_icon.setScaledContents(True)
        else:
            logo_icon.setText("✦")
            logo_icon.setAlignment(Qt.AlignCenter)

        self.logo_label = QLabel("Nordlys")
        self.logo_label.setObjectName("logoLabel")
        logo_font = self.logo_label.font()
        logo_font.setFamily(PRIMARY_UI_FONT_FAMILY)
        self.logo_label.setFont(logo_font)

        logo_layout.addWidget(logo_icon)
        logo_layout.addWidget(self.logo_label)
        logo_layout.addStretch()
        return logo_frame

    def _load_logo_icon(self) -> QIcon | None:
        if not LOGO_ICON_PATH.exists():
            return None

        icon = QIcon(str(LOGO_ICON_PATH))
        if icon.isNull():
            return None

        test_pixmap = icon.pixmap(44, 44)
        if test_pixmap.isNull():
            return None

        return icon
