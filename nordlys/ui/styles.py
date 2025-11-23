"""Samler applikasjonens hoved-stilark."""

from __future__ import annotations

from pathlib import Path
from string import Template
from textwrap import dedent

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon_path(filename: str) -> str:
    """Returner ikonets fil-URI slik at Qt alltid finner det."""

    return (_ICON_DIR / filename).as_uri()


_APPLICATION_STYLESHEET_TEMPLATE = Template(
    dedent(
        """
        QWidget {
            font-family: 'Roboto', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            font-size: 14px;
            color: #0e1624;
        }

        QMainWindow {
            background-color: #f2f4f8;
        }

        #navPanel {
            background: #0c1424;
            color: #e6eaf2;
            border-right: 1px solid rgba(148, 163, 184, 0.12);
            border-top-right-radius: 18px;
            border-bottom-right-radius: 18px;
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
            color: #d6e3ff;
            font-size: 14px;
        }

        #navTree:focus,
        QTreeWidget::item:focus {
            outline: none;
            border: none;
        }

        #navTree::item {
            height: 34px;
            padding: 6px 8px 6px 6px;
            border-radius: 10px;
            margin: 1px 0;
        }

        #navTree::item:selected {
            background-color: rgba(59, 130, 246, 0.32);
            color: #f8fafc;
            font-weight: 600;
        }

        #navTree::item:hover {
            background-color: rgba(59, 130, 246, 0.14);
        }

        QPushButton {
            background-color: #1d4ed8;
            color: #f8fafc;
            border-radius: 10px;
            padding: 10px 20px;
            font-weight: 600;
            letter-spacing: 0.2px;
        }

        QPushButton:focus {
            outline: none;
        }

        QPushButton:disabled {
            background-color: #94a3b8;
            color: #e5e7eb;
        }

        QPushButton:hover:!disabled {
            background-color: #173fae;
        }

        QPushButton:pressed {
            background-color: #142f88;
        }

        QPushButton#approveButton {
            background-color: #15803d;
        }

        QPushButton#approveButton:hover:!disabled {
            background-color: #166534;
        }

        QPushButton#approveButton:pressed {
            background-color: #14532d;
        }

        QPushButton#rejectButton {
            background-color: #b91c1c;
        }

        QPushButton#rejectButton:hover:!disabled {
            background-color: #991b1b;
        }

        QPushButton#rejectButton:pressed {
            background-color: #7f1d1d;
        }

        QPushButton#navButton {
            background-color: #0ea5e9;
        }

        QPushButton#navButton:hover:!disabled {
            background-color: #0284c7;
        }

        QPushButton#navButton:pressed {
            background-color: #0369a1;
        }

        QPushButton#exportPdfButton {
            background-color: #f97316;
        }

        QPushButton#exportPdfButton:hover:!disabled {
            background-color: #ea580c;
        }

        QPushButton#exportPdfButton:pressed {
            background-color: #c2410c;
        }

        #card {
            background-color: #ffffff;
            border-radius: 18px;
            border: 1px solid rgba(15, 23, 42, 0.08);
        }

        #cardTitle {
            font-size: 20px;
            font-weight: 700;
            color: #0e1624;
            letter-spacing: 0.2px;
        }

        #cardSubtitle {
            color: #475569;
            font-size: 13px;
            line-height: 1.5;
        }

        #taskProgressDialog {
            background-color: rgba(15, 23, 42, 0.92);
            border-radius: 24px;
        }

        #taskProgressPanel {
            background-color: #ffffff;
            border-radius: 18px;
            border: 1px solid rgba(148, 163, 184, 0.28);
        }

        #taskProgressTitle {
            font-size: 18px;
            font-weight: 700;
            color: #0e1624;
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
            background-color: #1d4ed8;
            border-radius: 10px;
        }

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
            color: #0e1624;
        }

        QPlainTextEdit#logText {
            background-color: #f8fafc;
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 14px;
            padding: 8px 10px;
            font-size: 13px;
            color: #0e1624;
        }

        #analysisSectionTitle {
            font-size: 16px;
            font-weight: 700;
            color: #0e1624;
            letter-spacing: 0.2px;
            border-bottom: 2px solid rgba(37, 99, 235, 0.35);
            padding-bottom: 6px;
        }

        #analysisSectionTitle[tightSpacing="true"] {
            padding-bottom: 0px;
            margin-bottom: 0px;
        }

        #pageTitle {
            font-size: 30px;
            font-weight: 800;
            color: #0e1624;
            letter-spacing: 0.6px;
        }

        QLabel#pageSubtitle {
            color: #1f2937;
            font-size: 15px;
        }

        #statusLabel {
            color: #1f2937;
            font-size: 14px;
            line-height: 1.6;
        }

        QLabel[meta='true'] {
            font-weight: 600;
        }

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

        #emptyState {
            background-color: rgba(148, 163, 184, 0.12);
            border-radius: 18px;
            border: 1px dashed rgba(148, 163, 184, 0.4);
        }

        #emptyStateIcon {
            font-size: 32px;
        }

        #emptyStateTitle {
            font-size: 17px;
            font-weight: 600;
            color: #0e1624;
        }

        #emptyStateDescription {
            color: #475569;
            font-size: 13px;
            max-width: 420px;
        }

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

        QTableWidget::item {
            padding: 1px 8px;
        }

        QTableWidget::item:selected {
            background-color: rgba(37, 99, 235, 0.22);
            color: #0e1624;
        }

        QHeaderView::section {
            background-color: rgba(148, 163, 184, 0.12);
            border: none;
            font-weight: 700;
            color: #0e1624;
            padding: 10px 6px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }

        QHeaderView::section:horizontal {
            border-bottom: 2px solid rgba(37, 99, 235, 0.35);
        }

        QListWidget#checklist {
            border: none;
        }

        QListWidget#checklist::item {
            padding: 12px 16px;
            margin: 6px 0;
            border-radius: 12px;
        }

        QListWidget#checklist::item:selected {
            background-color: rgba(37, 99, 235, 0.18);
            color: #0e1624;
            font-weight: 600;
        }

        QListWidget#checklist::item:hover {
            background-color: rgba(15, 23, 42, 0.08);
        }

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
            color: #0e1624;
        }

        #statDescription {
            font-size: 12px;
            color: #64748b;
        }

        QStatusBar {
            background: transparent;
            color: #475569;
            padding-right: 24px;
            border-top: 1px solid rgba(148, 163, 184, 0.3);
        }

        QComboBox,
        QSpinBox {
            background-color: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.5);
            border-radius: 10px;
            padding: 8px 12px;
            min-height: 32px;
        }

        QComboBox QAbstractItemView {
            border-radius: 8px;
            padding: 6px;
        }

        QComboBox::drop-down {
            border: none;
            width: 24px;
        }

        QComboBox::down-arrow {
            image: none;
        }

        QSpinBox::up-button,
        QSpinBox::down-button,
        QDoubleSpinBox::up-button,
        QDoubleSpinBox::down-button {
            border: none;
            background: transparent;
            width: 0;
            height: 0;
            margin: 0;
        }

        QSpinBox::up-arrow,
        QDoubleSpinBox::up-arrow,
        QSpinBox::down-arrow,
        QDoubleSpinBox::down-arrow {
            image: none;
        }

        QToolTip {
            background-color: #0e1624;
            color: #f8fafc;
            border: none;
            padding: 8px 10px;
            border-radius: 8px;
        }

        QTabWidget::pane {
            border: 1px solid rgba(148, 163, 184, 0.32);
            border-radius: 14px;
            background: #f6f8fc;
            margin-top: 12px;
            padding: 12px;
        }

        QTabWidget::tab-bar {
            left: 12px;
        }

        QTabBar::tab {
            background: rgba(148, 163, 184, 0.18);
            color: #0e1624;
            padding: 10px 20px;
            border-radius: 10px;
            margin-right: 8px;
            font-weight: 600;
        }

        QTabBar::tab:selected {
            background: #1d4ed8;
            color: #f8fafc;
        }

        QTabBar::tab:hover {
            background: rgba(37, 99, 235, 0.32);
            color: #0e1624;
        }

        QTabBar::tab:!selected {
            border: 1px solid rgba(148, 163, 184, 0.35);
        }

        #analysisDivider {
            background-color: rgba(148, 163, 184, 0.45);
            border-radius: 2px;
            margin: 4px 0;
        }

        QLineEdit,
        QPlainTextEdit,
        QTextEdit {
            background-color: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.5);
            border-radius: 10px;
            padding: 10px 12px;
            color: #0e1624;
            selection-background-color: rgba(37, 99, 235, 0.25);
            selection-color: #0e1624;
        }

        QLineEdit:focus,
        QPlainTextEdit:focus,
        QTextEdit:focus {
            border-color: #1d4ed8;
            background-color: #ffffff;
        }

        QPlainTextEdit#commentInput {
            min-height: 100px;
        }

        QScrollBar:vertical {
            background: rgba(148, 163, 184, 0.18);
            width: 12px;
            margin: 8px 2px 8px 0;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical {
            background: #1d4ed8;
            min-height: 24px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical:hover {
            background: #173fae;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
        }

        QScrollBar:horizontal {
            background: rgba(148, 163, 184, 0.18);
            height: 12px;
            margin: 0 8px 2px 8px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal {
            background: #1d4ed8;
            min-width: 24px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal:hover {
            background: #173fae;
        }

        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            width: 0;
        }
        """
    )
)

APPLICATION_STYLESHEET = _APPLICATION_STYLESHEET_TEMPLATE.substitute(
    {
        "up_icon": _icon_path("chevron-up.svg"),
        "down_icon": _icon_path("chevron-down.svg"),
    }
)

__all__ = ["APPLICATION_STYLESHEET"]
