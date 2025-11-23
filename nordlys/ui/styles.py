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
            color: #0f172a;
        }

        QMainWindow {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:0,
                y2:1,
                stop:0 #f9fbff,
                stop:1 #e5edff
            );
        }

        #navPanel {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:1,
                y2:0,
                stop:0 #0b1226,
                stop:1 #0f2952
            );
            color: #e2e8f0;
            border-right: 1px solid rgba(148, 163, 184, 0.12);
            border-top-right-radius: 22px;
            border-bottom-right-radius: 22px;
            padding: 16px 12px;
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
            color: #dbeafe;
            font-size: 14px;
        }

        #navTree:focus {
            outline: none;
            border: none;
        }

        QTreeWidget::item:focus {
            outline: none;
        }

        #navTree::item {
            height: 36px;
            padding: 8px 10px 8px 8px;
            border-radius: 12px;
            margin: 2px 0;
        }

        #navTree::item:selected {
            background-color: rgba(14, 165, 233, 0.28);
            border: 1px solid rgba(125, 211, 252, 0.55);
            color: #f8fafc;
            font-weight: 700;
        }

        #navTree::item:hover {
            background-color: rgba(59, 130, 246, 0.18);
            color: #e0f2fe;
        }

        QPushButton {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:1,
                y2:1,
                stop:0 #2563eb,
                stop:0.6 #4f46e5,
                stop:1 #7c3aed
            );
            color: #f8fafc;
            border-radius: 12px;
            padding: 10px 22px;
            font-weight: 700;
            letter-spacing: 0.2px;
            border: 1px solid rgba(226, 232, 240, 0.35);
        }

        QPushButton:focus {
            outline: none;
        }

        QPushButton:disabled {
            background-color: #94a3b8;
            color: #e5e7eb;
            border: none;
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
            background: #1f3fbf;
        }

        QPushButton#approveButton {
            background: #16a34a;
            border: 1px solid rgba(74, 222, 128, 0.6);
        }

        QPushButton#approveButton:hover:!disabled {
            background: #15803d;
        }

        QPushButton#approveButton:pressed {
            background: #166534;
        }

        QPushButton#rejectButton {
            background: #dc2626;
            border: 1px solid rgba(248, 113, 113, 0.5);
        }

        QPushButton#rejectButton:hover:!disabled {
            background: #b91c1c;
        }

        QPushButton#rejectButton:pressed {
            background: #991b1b;
        }

        QPushButton#navButton {
            background: #0ea5e9;
            border: 1px solid rgba(125, 211, 252, 0.65);
        }

        QPushButton#navButton:hover:!disabled {
            background: #0284c7;
        }

        QPushButton#navButton:pressed {
            background: #0369a1;
        }

        QPushButton#exportPdfButton {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:1,
                y2:1,
                stop:0 #fb923c,
                stop:1 #f97316
            );
        }

        QPushButton#exportPdfButton:hover:!disabled {
            background: #ea580c;
        }

        QPushButton#exportPdfButton:pressed {
            background: #c2410c;
        }

        #card {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:1,
                y2:1,
                stop:0 #ffffff,
                stop:1 #f3f6ff
            );
            border-radius: 22px;
            border: 1px solid rgba(148, 163, 184, 0.32);
            padding: 2px;
        }

        #cardTitle {
            font-size: 20px;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: 0.2px;
        }

        #cardSubtitle {
            color: #475569;
            font-size: 13px;
            line-height: 1.5;
        }

        #taskProgressDialog {
            background-color: rgba(15, 23, 42, 0.92);
            border-radius: 28px;
            border: 1px solid rgba(226, 232, 240, 0.24);
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
            font-weight: 800;
            color: #0f172a;
        }

        #taskProgressDetail {
            color: #475569;
            font-size: 13px;
            line-height: 1.5;
        }

        QProgressBar#taskProgressBar {
            background: rgba(15, 23, 42, 0.55);
            border: 1px solid rgba(226, 232, 240, 0.2);
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
                stop:0 #22c55e,
                stop:1 #16a34a
            );
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

        #analysisSectionTitle {
            font-size: 16px;
            font-weight: 800;
            color: #0f172a;
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
            font-weight: 900;
            color: #0b1226;
            letter-spacing: 0.6px;
        }

        QLabel#pageSubtitle {
            color: #1e293b;
            font-size: 15px;
        }

        #statusLabel {
            color: #1f2937;
            font-size: 14px;
            line-height: 1.6;
        }

        QLabel[meta='true'] {
            font-weight: 700;
            color: #0f172a;
        }

        QLabel#statusLabel[statusState='approved'] {
            color: #15803d;
            font-weight: 800;
        }

        QLabel#statusLabel[statusState='rejected'] {
            color: #b91c1c;
            font-weight: 800;
        }

        QLabel#statusLabel[statusState='pending'] {
            color: #0ea5e9;
            font-weight: 700;
        }

        #emptyState {
            background-color: rgba(148, 163, 184, 0.12);
            border-radius: 18px;
            border: 1px dashed rgba(148, 163, 184, 0.4);
        }

        #emptyStateIcon {
            font-size: 32px;
            color: #0ea5e9;
        }

        #emptyStateTitle {
            font-size: 17px;
            font-weight: 700;
            color: #0f172a;
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
            color: #0f172a;
        }

        QHeaderView::section {
            background-color: rgba(14, 165, 233, 0.16);
            border: none;
            font-weight: 800;
            color: #0f172a;
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
            color: #0f172a;
            font-weight: 700;
        }

        QListWidget#checklist::item:hover {
            background-color: rgba(14, 165, 233, 0.14);
        }

        #statBadge {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:1,
                y2:1,
                stop:0 #f8fafc,
                stop:1 #e0f2fe
            );
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 16px;
        }

        #statTitle {
            font-size: 12px;
            font-weight: 700;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 1.2px;
        }

        #statValue {
            font-size: 26px;
            font-weight: 800;
            color: #0f172a;
        }

        #statDescription {
            font-size: 12px;
            color: #0ea5e9;
            font-weight: 600;
        }

        QStatusBar {
            background: rgba(255, 255, 255, 0.85);
            color: #334155;
            padding-right: 24px;
            border-top: 1px solid rgba(148, 163, 184, 0.3);
        }

        QComboBox, QSpinBox {
            background-color: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.5);
            border-radius: 10px;
            padding: 8px 12px;
            min-height: 32px;
        }

        QComboBox QAbstractItemView {
            border-radius: 8px;
            padding: 6px;
            selection-background-color: rgba(14, 165, 233, 0.2);
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
        QDoubleSpinBox::up-arrow {
            image: none;
        }

        QSpinBox::down-arrow,
        QDoubleSpinBox::down-arrow {
            image: none;
        }

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

        QTabWidget::tab-bar {
            left: 12px;
        }

        QTabBar::tab {
            background: rgba(148, 163, 184, 0.18);
            color: #0f172a;
            padding: 10px 20px;
            border-radius: 10px;
            margin-right: 8px;
            font-weight: 700;
        }

        QTabBar::tab:selected {
            background: qlineargradient(
                spread:pad,
                x1:0,
                y1:0,
                x2:1,
                y2:0,
                stop:0 #2563eb,
                stop:1 #0ea5e9
            );
            color: #f8fafc;
        }

        QTabBar::tab:hover {
            background: rgba(37, 99, 235, 0.35);
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

        QLineEdit,
        QPlainTextEdit,
        QTextEdit {
            background-color: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.5);
            border-radius: 10px;
            padding: 10px 12px;
            color: #0f172a;
            selection-background-color: rgba(37, 99, 235, 0.25);
            selection-color: #0f172a;
        }

        QLineEdit:focus,
        QPlainTextEdit:focus,
        QTextEdit:focus {
            border-color: #2563eb;
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
            background: #2563eb;
            min-height: 24px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical:hover {
            background: #1d4ed8;
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
            background: #2563eb;
            min-width: 24px;
            border-radius: 6px;
        }

        QScrollBar::handle:horizontal:hover {
            background: #1d4ed8;
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
