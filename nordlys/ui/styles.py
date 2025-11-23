"""Samler applikasjonens hoved-stilark."""

from __future__ import annotations

from pathlib import Path
from string import Template

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon_path(filename: str) -> str:
    """Returner ikonets fil-URI slik at Qt alltid finner det."""

    return (_ICON_DIR / filename).as_uri()


_APPLICATION_STYLESHEET_TEMPLATE = Template(
    """
QWidget {
    font-family: 'Roboto', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    color: #0b1224;
}

QMainWindow {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #eef2ff,
        stop:0.6 #e0f2fe,
        stop:1 #e2e8f0
    );
}

#navPanel {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:0,
        stop:0 #0f172a,
        stop:0.55 #1e3a8a,
        stop:1 #312e81
    );
    color: #e2e8f0;
    border-right: 1px solid rgba(148, 163, 184, 0.1);
    border-top-right-radius: 22px;
    border-bottom-right-radius: 22px;
}

#logoLabel {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: #f8fafc;
}

#navTree {
    background: transparent;
    border: none;
    color: #e0f2fe;
    font-size: 14px;
}

#navTree:focus { outline: none; border: none; }
QTreeWidget::item:focus { outline: none; }

#navTree::item {
    height: 34px;
    padding: 6px 8px 6px 6px;
    border-radius: 10px;
    margin: 1px 0;
}

#navTree::item:selected {
    background-color: rgba(94, 234, 212, 0.26);
    color: #f8fafc;
    font-weight: 600;
    border: 1px solid rgba(125, 211, 252, 0.38);
}

#navTree::item:hover {
    background-color: rgba(129, 140, 248, 0.24);
}

QPushButton {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #2563eb,
        stop:1 #7c3aed
    );
    color: #f8fafc;
    border-radius: 12px;
    padding: 10px 20px;
    font-weight: 700;
    letter-spacing: 0.2px;
    border: 1px solid rgba(255, 255, 255, 0.12);
}

QPushButton:focus {
    outline: none;
    border: 1px solid rgba(129, 140, 248, 0.75);
}

QPushButton:disabled {
    background: #cbd5e1;
    color: #e2e8f0;
    border-color: #cbd5e1;
}

QPushButton:hover:!disabled {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #1d4ed8,
        stop:1 #6d28d9
    );
}

QPushButton:pressed {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #1e40af,
        stop:1 #5b21b6
    );
}

QPushButton#approveButton {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #16a34a,
        stop:1 #22c55e
    );
    border-color: rgba(34, 197, 94, 0.4);
}

QPushButton#approveButton:hover:!disabled {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #15803d,
        stop:1 #16a34a
    );
}

QPushButton#approveButton:pressed {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #166534,
        stop:1 #15803d
    );
}

QPushButton#rejectButton {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #dc2626,
        stop:1 #f97316
    );
    border-color: rgba(239, 68, 68, 0.45);
}

QPushButton#rejectButton:hover:!disabled {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #b91c1c,
        stop:1 #ea580c
    );
}

QPushButton#rejectButton:pressed {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #991b1b,
        stop:1 #c2410c
    );
}

QPushButton#navButton {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #14b8a6,
        stop:1 #0ea5e9
    );
    border-color: rgba(14, 165, 233, 0.42);
}

QPushButton#navButton:hover:!disabled {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #0d9488,
        stop:1 #0284c7
    );
}

QPushButton#navButton:pressed {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #0f766e,
        stop:1 #0369a1
    );
}

QPushButton#exportPdfButton {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #f59e0b,
        stop:1 #f97316
    );
    border-color: rgba(249, 115, 22, 0.4);
}

QPushButton#exportPdfButton:hover:!disabled {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #ea580c,
        stop:1 #f59e0b
    );
}

QPushButton#exportPdfButton:pressed {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #c2410c,
        stop:1 #d97706
    );
}

#card {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #ffffff,
        stop:1 #f4f5ff
    );
    border-radius: 20px;
    border: 1px solid rgba(148, 163, 184, 0.36);
}

#cardTitle {
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: 0.2px;
}

#cardSubtitle {
    color: #475569;
    font-size: 13px;
    line-height: 1.6;
}

#taskProgressDialog {
    background-color: rgba(15, 23, 42, 0.96);
    border-radius: 28px;
}

#taskProgressPanel {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #ffffff,
        stop:1 #eef2ff
    );
    border-radius: 22px;
    border: 1px solid rgba(148, 163, 184, 0.28);
}

#taskProgressTitle {
    font-size: 18px;
    font-weight: 700;
    color: #0f172a;
}

#taskProgressDetail {
    color: #475569;
    font-size: 13px;
    line-height: 1.5;
}

QProgressBar#taskProgressBar {
    background-color: rgba(15, 23, 42, 0.6);
    border: none;
    border-radius: 12px;
    height: 18px;
    padding: 4px 10px;
    color: #f8fafc;
    font-weight: 700;
    letter-spacing: 0.4px;
}

QProgressBar#taskProgressBar::chunk {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #22d3ee,
        stop:1 #6366f1
    );
    border-radius: 10px;
}

QFrame#logListContainer {
    background: #f8fafc;
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
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    background-color: transparent;
}

QListWidget#logList::item:selected {
    background-color: rgba(94, 234, 212, 0.25);
    color: #0f172a;
}

QPlainTextEdit#logText {
    background: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 14px;
    padding: 8px 10px;
    font-size: 13px;
    color: #0f172a;
}

#analysisSectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: 0.2px;
    border-bottom: 2px solid rgba(99, 102, 241, 0.35);
    padding-bottom: 6px;
}

#analysisSectionTitle[tightSpacing="true"] {
    padding-bottom: 0px;
    margin-bottom: 0px;
}

#pageTitle {
    font-size: 30px;
    font-weight: 800;
    color: #0b1224;
    letter-spacing: 0.6px;
}

QLabel#pageSubtitle { color: #1f2937; font-size: 15px; }
#statusLabel { color: #1f2937; font-size: 14px; line-height: 1.6; }
QLabel[meta='true'] { font-weight: 600; }

QLabel#statusLabel[statusState='approved'] {
    color: #15803d;
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

#emptyState {
    background-color: rgba(148, 163, 184, 0.12);
    border-radius: 18px;
    border: 1px dashed rgba(148, 163, 184, 0.4);
}

#emptyStateIcon { font-size: 32px; }
#emptyStateTitle { font-size: 17px; font-weight: 600; color: #0f172a; }
#emptyStateDescription { color: #475569; font-size: 13px; max-width: 420px; }

#cardTable {
    border: none;
    gridline-color: rgba(148, 163, 184, 0.35);
    background-color: transparent;
    alternate-background-color: #f8fafc;
}

QTableWidget {
    background-color: transparent;
    alternate-background-color: #f8fafc;
}

QTableWidget::item { padding: 1px 8px; }

QTableWidget::item:selected {
    background-color: rgba(99, 102, 241, 0.22);
    color: #0f172a;
    border: 1px solid rgba(99, 102, 241, 0.4);
}

QHeaderView::section {
    background-color: rgba(148, 163, 184, 0.14);
    border: none;
    font-weight: 700;
    color: #0f172a;
    padding: 10px 6px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

QHeaderView::section:horizontal {
    border-bottom: 2px solid rgba(99, 102, 241, 0.35);
}

QListWidget#checklist { border: none; }
QListWidget#checklist::item { padding: 12px 16px; margin: 6px 0; border-radius: 12px; }

QListWidget#checklist::item:selected {
    background-color: rgba(99, 102, 241, 0.2);
    color: #0f172a;
    font-weight: 600;
}

QListWidget#checklist::item:hover { background-color: rgba(15, 23, 42, 0.08); }

#statBadge {
    background-color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 16px;
}

#statTitle {
    font-size: 12px;
    font-weight: 600;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 1.2px;
}

#statValue {
    font-size: 26px;
    font-weight: 700;
    color: #0f172a;
}

#statDescription { font-size: 12px; color: #64748b; }

QStatusBar {
    background: rgba(255, 255, 255, 0.7);
    color: #475569;
    padding-right: 24px;
    border-top: 1px solid rgba(148, 163, 184, 0.28);
}

QComboBox, QSpinBox {
    background-color: #ffffff;
    border: 1px solid rgba(148, 163, 184, 0.5);
    border-radius: 12px;
    padding: 10px 14px;
    min-height: 32px;
}

QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: rgba(99, 102, 241, 0.85);
}

QComboBox QAbstractItemView {
    border-radius: 8px;
    padding: 6px;
    background: #f8fafc;
    selection-background-color: rgba(99, 102, 241, 0.18);
}

QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url(${down_icon}); width: 14px; height: 14px; }
QComboBox::down-arrow:on { image: url(${up_icon}); }

QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    border: none;
    background: transparent;
    width: 0;
    height: 0;
    margin: 0;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: none; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: none; }

QToolTip {
    background-color: #0f172a;
    color: #f8fafc;
    border: none;
    padding: 8px 10px;
    border-radius: 8px;
}

QTabWidget::pane {
    border: 1px solid rgba(148, 163, 184, 0.32);
    border-radius: 14px;
    background: #f4f7ff;
    margin-top: 12px;
    padding: 12px;
}

QTabWidget::tab-bar { left: 12px; }

QTabBar::tab {
    background: rgba(148, 163, 184, 0.2);
    color: #0f172a;
    padding: 10px 20px;
    border-radius: 10px;
    margin-right: 8px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background: qlineargradient(
        spread:pad,
        x1:0,
        y1:0,
        x2:1,
        y2:1,
        stop:0 #2563eb,
        stop:1 #6366f1
    );
    color: #f8fafc;
}

QTabBar::tab:hover {
    background: rgba(99, 102, 241, 0.35);
    color: #0f172a;
}

QTabBar::tab:!selected {
    border: 1px solid rgba(148, 163, 184, 0.35);
}

#analysisDivider {
    background-color: rgba(148, 163, 184, 0.45);
    border-radius: 2px;
    margin: 4px 0;
}

QLineEdit, QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid rgba(148, 163, 184, 0.5);
    border-radius: 12px;
    padding: 10px 12px;
    color: #0f172a;
    selection-background-color: rgba(99, 102, 241, 0.25);
    selection-color: #0f172a;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border-color: rgba(99, 102, 241, 0.85);
    background-color: #ffffff;
}

QPlainTextEdit#commentInput { min-height: 100px; }

QScrollBar:vertical {
    background: rgba(148, 163, 184, 0.18);
    width: 12px;
    margin: 8px 2px 8px 0;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #6366f1;
    min-height: 24px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover { background: #4f46e5; }

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: rgba(148, 163, 184, 0.18);
    height: 12px;
    margin: 0 8px 2px 8px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background: #6366f1;
    min-width: 24px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover { background: #4f46e5; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""
)

APPLICATION_STYLESHEET = _APPLICATION_STYLESHEET_TEMPLATE.substitute(
    {
        "up_icon": _icon_path("chevron-up.svg"),
        "down_icon": _icon_path("chevron-down.svg"),
    }
)

__all__ = ["APPLICATION_STYLESHEET"]
