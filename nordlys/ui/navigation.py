"""Reusable navigasjonskomponenter for Nordlys sitt UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QLabel,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .config import PRIMARY_UI_FONT_FAMILY, icon_for_navigation

__all__ = ["NavigationItem", "NavigationPanel"]


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

        self.logo_label = QLabel("Nordlys")
        self.logo_label.setObjectName("logoLabel")
        logo_font = self.logo_label.font()
        logo_font.setFamily(PRIMARY_UI_FONT_FAMILY)
        self.logo_label.setFont(logo_font)

        logo_row = QFrame()
        logo_row.setObjectName("logoRow")
        logo_layout = QHBoxLayout(logo_row)
        logo_layout.setContentsMargins(12, 10, 12, 10)
        logo_layout.setSpacing(10)

        self.logo_icon = QLabel()
        self.logo_icon.setObjectName("logoIcon")
        pixmap = self._load_logo_pixmap()
        if pixmap is not None:
            self.logo_icon.setPixmap(pixmap)
            self.logo_icon.setFixedSize(pixmap.size())
        else:
            self.logo_icon.setText("✦")
            self.logo_icon.setAlignment(Qt.AlignCenter)
            self.logo_icon.setFixedSize(36, 36)

        logo_layout.addWidget(self.logo_icon)
        logo_layout.addWidget(self.logo_label)
        logo_layout.addStretch(1)

        layout.addWidget(logo_row)

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

    def _load_logo_pixmap(self) -> QPixmap | None:
        """Last inn applikasjonens logo dersom filen finnes."""

        logo_path = (
            Path(__file__).resolve().parent.parent
            / "resources"
            / "icons"
            / "nordlys-logo.svg"
        )
        if not logo_path.exists():
            return None

        icon = QIcon(str(logo_path))
        if icon.isNull():
            return None

        pixmap = icon.pixmap(36, 36)
        return pixmap if not pixmap.isNull() else None
