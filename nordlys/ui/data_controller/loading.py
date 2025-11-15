"""Holder styr på lastestatus for SAF-T-importer."""

from __future__ import annotations

from typing import Optional

from .context import ControllerContext


class LoadingStateController:
    """Aktiverer og deaktiverer knapper når vi laster SAF-T."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def set_loading_state(
        self, loading: bool, status_message: Optional[str] = None
    ) -> None:
        header = self._context.header_bar
        store = self._context.dataset_store
        pages = self._context.pages

        header.set_open_enabled(not loading)
        has_data = store.saft_df is not None
        header.set_export_enabled(False if loading else has_data)
        if loading:
            header.set_dataset_enabled(False)
        else:
            header.set_dataset_enabled(bool(store.dataset_order))

        if pages.sales_ar_page:
            pages.sales_ar_page.set_controls_enabled(
                False if loading else store.has_customer_data
            )
        if pages.purchases_ap_page:
            pages.purchases_ap_page.set_controls_enabled(
                False if loading else store.has_supplier_data
            )

        if status_message:
            self._context.status_bar.showMessage(status_message)
