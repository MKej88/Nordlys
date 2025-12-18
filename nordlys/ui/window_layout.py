"""Hjelpefunksjon for å bygge hovedlayouten til Nordlys-vinduet."""

from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .header_bar import HeaderBar
from .navigation import NavigationPanel
from .widgets import CardFrame


@dataclass(slots=True)
class WindowComponents:
    """Referanser til de viktigste widgetene i vinduet."""

    nav_panel: NavigationPanel
    content_layout: QVBoxLayout
    header_bar: HeaderBar
    info_card: CardFrame
    lbl_company: QLabel
    lbl_orgnr: QLabel
    lbl_period: QLabel
    lbl_industry: QLabel
    stack: QStackedWidget
    status_bar: QStatusBar
    progress_label: QLabel
    progress_bar: QProgressBar


def setup_main_window(window: QMainWindow) -> WindowComponents:
    """Bygger hele layouten og returnerer nyttige referanser."""

    central = QWidget()
    window.setCentralWidget(central)
    root_layout = QHBoxLayout(central)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    nav_panel = NavigationPanel()
    root_layout.addWidget(nav_panel, 0)

    content_wrapper = QWidget()
    content_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    content_layout = QVBoxLayout(content_wrapper)
    content_layout.setContentsMargins(32, 32, 32, 32)
    content_layout.setSpacing(24)
    root_layout.addWidget(content_wrapper, 1)

    header_bar = HeaderBar()
    content_layout.addWidget(header_bar)

    info_card = CardFrame("Selskapsinformasjon")
    info_grid = QGridLayout()
    info_grid.setHorizontalSpacing(24)
    info_grid.setVerticalSpacing(8)

    lbl_company = QLabel("Selskap: –")
    lbl_orgnr = QLabel("Org.nr: –")
    lbl_period = QLabel("Periode: –")
    lbl_industry = QLabel("Bransje: –")
    info_grid.addWidget(lbl_company, 0, 0)
    info_grid.addWidget(lbl_orgnr, 0, 1)
    info_grid.addWidget(lbl_period, 0, 2)
    info_grid.addWidget(lbl_industry, 0, 3)
    info_card.add_layout(info_grid)
    content_layout.addWidget(info_card)

    stack = QStackedWidget()
    content_layout.addWidget(stack, 1)

    status_bar = QStatusBar()
    status_bar.showMessage("Klar.")
    progress_label = QLabel()
    progress_label.setObjectName("statusProgressLabel")
    progress_label.setVisible(False)
    status_bar.addPermanentWidget(progress_label)
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0)
    progress_bar.setTextVisible(False)
    progress_bar.setFixedWidth(180)
    progress_bar.setVisible(False)
    status_bar.addPermanentWidget(progress_bar)
    window.setStatusBar(status_bar)

    return WindowComponents(
        nav_panel=nav_panel,
        content_layout=content_layout,
        header_bar=header_bar,
        info_card=info_card,
        lbl_company=lbl_company,
        lbl_orgnr=lbl_orgnr,
        lbl_period=lbl_period,
        lbl_industry=lbl_industry,
        stack=stack,
        status_bar=status_bar,
        progress_label=progress_label,
        progress_bar=progress_bar,
    )
