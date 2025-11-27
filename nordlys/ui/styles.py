"""Samler applikasjonens hoved-stilark."""

from __future__ import annotations

import re
from pathlib import Path
from string import Template
from typing import Match

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon_path(filename: str) -> str:
    """Returner ikonets fil-URI slik at Qt alltid finner det."""

    return (_ICON_DIR / filename).as_uri()


_APPLICATION_STYLESHEET_TEMPLATE = Template(
    """
QWidget { font-family: 'Roboto', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 14px; color: #0f172a; }
QMainWindow { background-color: #e9effb; }
#navPanel { background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #0b1120, stop:1 #0f172a); color: #e2e8f0; border-right: 1px solid rgba(148, 163, 184, 0.08); border-top-right-radius: 22px; border-bottom-right-radius: 22px; }
#logoLabel { font-size: 26px; font-weight: 700; letter-spacing: 0.6px; color: #f8fafc; }
#navTree { background: transparent; border: none; color: #dbeafe; font-size: 14px; }
#navTree:focus { outline: none; border: none; }
QTreeWidget::item:focus { outline: none; }
#navTree::item { height: 34px; padding: 6px 8px 6px 6px; border-radius: 10px; margin: 1px 0; }
#navTree::item:selected { background-color: rgba(59, 130, 246, 0.35); color: #f8fafc; font-weight: 600; }
#navTree::item:hover { background-color: rgba(59, 130, 246, 0.18); }
QPushButton { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #1d4ed8); color: #f8fafc; border-radius: 10px; padding: 10px 20px; font-weight: 600; letter-spacing: 0.2px; }
QPushButton:focus { outline: none; }
QPushButton:disabled { background-color: #94a3b8; color: #e5e7eb; }
QPushButton:hover:!disabled { background-color: #1e40af; }
QPushButton:pressed { background-color: #1d4ed8; }
QPushButton#approveButton { background-color: #16a34a; }
QPushButton#approveButton:hover:!disabled { background-color: #15803d; }
QPushButton#approveButton:pressed { background-color: #166534; }
QPushButton#rejectButton { background-color: #dc2626; }
QPushButton#rejectButton:hover:!disabled { background-color: #b91c1c; }
QPushButton#rejectButton:pressed { background-color: #991b1b; }
QPushButton#navButton { background-color: #0ea5e9; }
QPushButton#navButton:hover:!disabled { background-color: #0284c7; }
QPushButton#navButton:pressed { background-color: #0369a1; }
QPushButton#exportPdfButton { background-color: #f97316; }
QPushButton#exportPdfButton:hover:!disabled { background-color: #ea580c; }
QPushButton#exportPdfButton:pressed { background-color: #c2410c; }
#card { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f8fbff); border-radius: 20px; border: 1px solid rgba(148, 163, 184, 0.32); }
#cardTitle { font-size: 20px; font-weight: 700; color: #0f172a; letter-spacing: 0.2px; }
#cardSubtitle { color: #475569; font-size: 13px; line-height: 1.5; }
#taskProgressDialog { background-color: rgba(15, 23, 42, 0.95); border-radius: 28px; }
#taskProgressPanel { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f1f5ff); border-radius: 22px; border: 1px solid rgba(148, 163, 184, 0.28); }
#taskProgressTitle { font-size: 18px; font-weight: 700; color: #0f172a; }
#taskProgressDetail { color: #475569; font-size: 13px; line-height: 1.5; }
QProgressBar#taskProgressBar { background-color: rgba(15, 23, 42, 0.55); border: none; border-radius: 12px; height: 18px; padding: 4px 10px; color: #f8fafc; font-weight: 700; letter-spacing: 0.4px; }
QProgressBar#taskProgressBar::chunk { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #1d4ed8); border-radius: 10px; }
QFrame#logListContainer {
    background-color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 16px;
    padding: 0;
}
QListWidget#logList {
    background: transparent;
    border: none;
    padding: 0;
}
QListWidget#logList::item {
    padding: 12px 16px;
    margin: 0;
    border: none;
    border-bottom: 1px solid rgba(148, 163, 184, 0.2);
    background-color: transparent;
}
QListWidget#logList::item:selected {
    background-color: rgba(37, 99, 235, 0.15);
    color: #0f172a;
}
QPlainTextEdit#logText {
    background-color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 14px;
    padding: 8px 10px;
    font-size: 13px;
    color: #0f172a;
}
#analysisSectionTitle { font-size: 16px; font-weight: 700; color: #0f172a; letter-spacing: 0.2px; border-bottom: 2px solid rgba(37, 99, 235, 0.35); padding-bottom: 6px; }
#analysisSectionTitle[tightSpacing="true"] { padding-bottom: 0px; margin-bottom: 0px; }
#pageTitle { font-size: 30px; font-weight: 800; color: #0f172a; letter-spacing: 0.6px; }
QLabel#pageSubtitle { color: #1e293b; font-size: 15px; }
#statusLabel { color: #1f2937; font-size: 14px; line-height: 1.6; }
QLabel[meta='true'] { font-weight: 600; }
QLabel#statusLabel[statusState='approved'] {
    color: #166534;
    font-weight: 700;
}
QLabel#statusLabel[statusState='rejected'] {
    color: #b91c1c;
    font-weight: 700;
}
QLabel#statusLabel[statusState='pending'] {
    color: #64748b;
    font-weight: 500;
}
#emptyState { background-color: rgba(148, 163, 184, 0.12); border-radius: 18px; border: 1px dashed rgba(148, 163, 184, 0.4); }
#emptyStateIcon { font-size: 32px; }
#emptyStateTitle { font-size: 17px; font-weight: 600; color: #0f172a; }
#emptyStateDescription { color: #475569; font-size: 13px; max-width: 420px; }
#cardTable { border: none; gridline-color: rgba(148, 163, 184, 0.35); background-color: transparent; alternate-background-color: #f8fafc; }
QTableWidget { background-color: transparent; alternate-background-color: #f8fafc; }
QTableWidget::item { padding: 1px 8px; }
QTableWidget::item:selected { background-color: rgba(37, 99, 235, 0.22); color: #0f172a; }
QHeaderView::section { background-color: rgba(148, 163, 184, 0.12); border: none; font-weight: 700; color: #0f172a; padding: 10px 6px; text-transform: uppercase; letter-spacing: 0.8px; }
QHeaderView::section:horizontal { border-bottom: 2px solid rgba(37, 99, 235, 0.35); }
QListWidget#checklist { border: none; }
QListWidget#checklist::item { padding: 12px 16px; margin: 6px 0; border-radius: 12px; }
QListWidget#checklist::item:selected { background-color: rgba(37, 99, 235, 0.18); color: #0f172a; font-weight: 600; }
QListWidget#checklist::item:hover { background-color: rgba(15, 23, 42, 0.08); }
#statBadge { background-color: #f8fafc; border: 1px solid rgba(148, 163, 184, 0.35); border-radius: 16px; }
#statTitle { font-size: 12px; font-weight: 600; color: #475569; text-transform: uppercase; letter-spacing: 1.2px; }
#statValue { font-size: 26px; font-weight: 700; color: #0f172a; }
#statDescription { font-size: 12px; color: #64748b; }
QStatusBar { background: transparent; color: #475569; padding-right: 24px; border-top: 1px solid rgba(148, 163, 184, 0.3); }
QComboBox, QSpinBox { background-color: #ffffff; border: 1px solid rgba(148, 163, 184, 0.5); border-radius: 10px; padding: 8px 12px; min-height: 32px; }
QComboBox QAbstractItemView { border-radius: 8px; padding: 6px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: none; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { border: none; background: transparent; width: 0; height: 0; margin: 0; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: none; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: none; }
QToolTip { background-color: #0f172a; color: #f8fafc; border: none; padding: 8px 10px; border-radius: 8px; }
QTabWidget::pane { border: 1px solid rgba(148, 163, 184, 0.32); border-radius: 14px; background: #f4f7ff; margin-top: 12px; padding: 12px; }
QTabWidget::tab-bar { left: 12px; }
QTabWidget#fixedAssetTabs::pane { border: none; background: transparent; margin-top: 12px; padding: 0; }
QTabBar::tab { background: rgba(148, 163, 184, 0.18); color: #0f172a; padding: 10px 20px; border-radius: 10px; margin-right: 8px; font-weight: 600; }
QTabBar::tab:selected { background: #2563eb; color: #f8fafc; }
QTabBar::tab:hover { background: rgba(37, 99, 235, 0.35); color: #0f172a; }
QTabBar::tab:!selected { border: 1px solid rgba(148, 163, 184, 0.35); }
#analysisDivider { background-color: rgba(148, 163, 184, 0.45); border-radius: 2px; margin: 4px 0; }
QLineEdit, QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid rgba(148, 163, 184, 0.5);
    border-radius: 10px;
    padding: 10px 12px;
    color: #0f172a;
    selection-background-color: rgba(37, 99, 235, 0.25);
    selection-color: #0f172a;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: #2563eb;
    background-color: #ffffff;
}
QPlainTextEdit#commentInput {
    min-height: 100px;
}
QScrollBar:vertical { background: rgba(148, 163, 184, 0.18); width: 12px; margin: 8px 2px 8px 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #2563eb; min-height: 24px; border-radius: 6px; }
QScrollBar::handle:vertical:hover { background: #1d4ed8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: rgba(148, 163, 184, 0.18); height: 12px; margin: 0 8px 2px 8px; border-radius: 6px; }
QScrollBar::handle:horizontal { background: #2563eb; min-width: 24px; border-radius: 6px; }
QScrollBar::handle:horizontal:hover { background: #1d4ed8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""
)

def _scale_stylesheet(stylesheet: str, scale_factor: float) -> str:
    """Skaler px-verdier i stilarket for å tilpasse ulike skjermstørrelser."""

    if abs(scale_factor - 1.0) < 0.01:
        return stylesheet

    bounded_scale = max(0.85, min(scale_factor, 1.1))

    def _replace_px(match: Match[str]) -> str:
        value = int(match.group(1))
        scaled = max(1, round(value * bounded_scale))
        return f"{scaled}px"

    return re.sub(r"(\d+)px", _replace_px, stylesheet)


def build_stylesheet(scale_factor: float = 1.0) -> str:
    """Returner hoved-stilarket med valgfri skalering av px-verdier."""

    stylesheet = _APPLICATION_STYLESHEET_TEMPLATE.substitute(
        {
            "up_icon": _icon_path("chevron-up.svg"),
            "down_icon": _icon_path("chevron-down.svg"),
        }
    )
    return _scale_stylesheet(stylesheet, scale_factor)


APPLICATION_STYLESHEET = build_stylesheet()

__all__ = ["APPLICATION_STYLESHEET", "build_stylesheet"]
