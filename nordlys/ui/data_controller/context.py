"""Felles data som deles mellom underkontroller i SAF-T-håndteringen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QStatusBar, QWidget

from ..data_manager import SaftAnalytics, SaftDatasetStore
from ..header_bar import HeaderBar
from ..page_state_handler import PageStateHandler


@dataclass(slots=True)
class ControllerContext:
    """Holder på alle avhengigheter som deles mellom hjelpeklasser."""

    dataset_store: SaftDatasetStore
    analytics: SaftAnalytics
    header_bar: HeaderBar
    status_bar: QStatusBar
    parent: QWidget
    pages: PageStateHandler
    update_header_fields: Callable[[], None]
