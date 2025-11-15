"""Hjelpeklasse for å registrere og aktivere sider i hovedvinduet."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtWidgets import QStackedWidget, QWidget


class PageManager:
    """Holder orden på sider og sørger for at de materialiseres ved behov."""

    def __init__(
        self,
        owner: Any,
        stack: QStackedWidget,
        apply_page_state: Callable[[str, QWidget], None],
    ) -> None:
        self._owner = owner
        self._stack = stack
        self._apply_page_state = apply_page_state
        self._page_map: Dict[str, QWidget] = {}
        self._page_factories: Dict[str, Callable[[], QWidget]] = {}
        self._page_attributes: Dict[str, str] = {}

    def register_page(
        self, key: str, widget: QWidget, *, attr: Optional[str] = None
    ) -> None:
        """Legger en ferdig instansiert side i stacken."""

        self._page_map[key] = widget
        if attr:
            self._page_attributes[key] = attr
            setattr(self._owner, attr, widget)
        self._stack.addWidget(widget)
        self._apply_page_state(key, widget)

    def register_lazy_page(
        self, key: str, factory: Callable[[], QWidget], *, attr: Optional[str] = None
    ) -> None:
        """Registrerer en fabrikk som bygger siden ved første behov."""

        self._page_factories[key] = factory
        if attr:
            self._page_attributes[key] = attr

    def ensure_page(self, key: str) -> Optional[QWidget]:
        """Returnerer siden, og lager den om den ikke finnes fra før."""

        widget = self._page_map.get(key)
        if widget is not None:
            return widget
        return self._materialize_page(key)

    def _materialize_page(self, key: str) -> Optional[QWidget]:
        factory = self._page_factories.get(key)
        if factory is None:
            return None
        widget = factory()
        attr = self._page_attributes.get(key)
        self.register_page(key, widget, attr=attr)
        return widget
