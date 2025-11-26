"""Koordinerer all dataflyt mellom SAF-T og GUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, Optional, Sequence

from PySide6.QtWidgets import QStatusBar, QWidget

from ..config import REVISION_TASKS
from ..data_manager import SaftAnalytics, SaftDatasetStore
from ..header_bar import HeaderBar
from ..page_state_handler import ComparisonRows, PageStateHandler
from .analytics import AnalyticsEventHandler
from .context import ControllerContext
from .dataset_flow import DatasetFlowController
from .loading import LoadingStateController
from .messaging import ImportMessenger

if TYPE_CHECKING:
    from ..pages import (
        ComparisonPage,
        RegnskapsanalysePage,
        SammenstillingsanalysePage,
        SummaryPage,
    )
    from ..pages.dashboard_page import DashboardPage
    from ..pages.dataframe_page import DataFramePage
    from ..pages.import_page import ImportPage
    from ..pages.revision_pages import (
        CostVoucherReviewPage,
        FixedAssetsPage,
        PurchasesApPage,
        SalesArPage,
    )

    from ...saft.loader import SaftLoadResult


class SaftDataController:
    """Binder sammen datasettet, analysene og sidene i GUI-et."""

    def __init__(
        self,
        dataset_store: SaftDatasetStore,
        analytics: SaftAnalytics,
        header_bar: HeaderBar,
        status_bar: QStatusBar,
        parent: QWidget,
        schedule_responsive_update: Callable[[], None],
        update_header_fields: Callable[[], None],
    ) -> None:
        self._pages = PageStateHandler(
            dataset_store,
            REVISION_TASKS,
            schedule_responsive_update,
        )
        self._context = ControllerContext(
            dataset_store=dataset_store,
            analytics=analytics,
            header_bar=header_bar,
            status_bar=status_bar,
            parent=parent,
            pages=self._pages,
            update_header_fields=update_header_fields,
        )
        self._loading = LoadingStateController(self._context)
        self._messenger = ImportMessenger(self._context)
        self._dataset_flow = DatasetFlowController(self._context, self._messenger)
        self._analytics_events = AnalyticsEventHandler(self._context)

    # region Eierskap til sidene
    @property
    def import_page(self) -> Optional["ImportPage"]:
        return self._pages.import_page

    @import_page.setter
    def import_page(self, widget: Optional["ImportPage"]) -> None:
        self._pages.import_page = widget

    @property
    def dashboard_page(self) -> Optional["DashboardPage"]:
        return self._pages.dashboard_page

    @dashboard_page.setter
    def dashboard_page(self, widget: Optional["DashboardPage"]) -> None:
        self._pages.dashboard_page = widget

    @property
    def saldobalanse_page(self) -> Optional["DataFramePage"]:
        return self._pages.saldobalanse_page

    @saldobalanse_page.setter
    def saldobalanse_page(self, widget: Optional["DataFramePage"]) -> None:
        self._pages.saldobalanse_page = widget

    @property
    def kontroll_page(self) -> Optional["ComparisonPage"]:
        return self._pages.kontroll_page

    @kontroll_page.setter
    def kontroll_page(self, widget: Optional["ComparisonPage"]) -> None:
        self._pages.kontroll_page = widget

    @property
    def regnskap_page(self) -> Optional["RegnskapsanalysePage"]:
        return self._pages.regnskap_page

    @regnskap_page.setter
    def regnskap_page(self, widget: Optional["RegnskapsanalysePage"]) -> None:
        self._pages.regnskap_page = widget

    @property
    def vesentlig_page(self) -> Optional["SummaryPage"]:
        return self._pages.vesentlig_page

    @vesentlig_page.setter
    def vesentlig_page(self, widget: Optional["SummaryPage"]) -> None:
        self._pages.vesentlig_page = widget

    @property
    def sammenstilling_page(self) -> Optional["SammenstillingsanalysePage"]:
        return self._pages.sammenstilling_page

    @sammenstilling_page.setter
    def sammenstilling_page(
        self, widget: Optional["SammenstillingsanalysePage"]
    ) -> None:
        self._pages.sammenstilling_page = widget

    @property
    def sales_ar_page(self) -> Optional["SalesArPage"]:
        return self._pages.sales_ar_page

    @sales_ar_page.setter
    def sales_ar_page(self, widget: Optional["SalesArPage"]) -> None:
        self._pages.sales_ar_page = widget

    @property
    def purchases_ap_page(self) -> Optional["PurchasesApPage"]:
        return self._pages.purchases_ap_page

    @purchases_ap_page.setter
    def purchases_ap_page(self, widget: Optional["PurchasesApPage"]) -> None:
        self._pages.purchases_ap_page = widget

    @property
    def cost_review_page(self) -> Optional["CostVoucherReviewPage"]:
        return self._pages.cost_review_page

    @cost_review_page.setter
    def cost_review_page(self, widget: Optional["CostVoucherReviewPage"]) -> None:
        self._pages.cost_review_page = widget

    @property
    def fixed_assets_page(self) -> Optional["FixedAssetsPage"]:
        return self._pages.fixed_assets_page

    @fixed_assets_page.setter
    def fixed_assets_page(self, widget: Optional["FixedAssetsPage"]) -> None:
        self._pages.fixed_assets_page = widget

    @property
    def revision_pages(self) -> Dict[str, QWidget]:
        return self._pages.revision_pages

    # endregion

    def apply_page_state(self, key: str, widget: QWidget) -> None:
        self._pages.apply_page_state(key, widget)

    # region Import og datasett
    def set_loading_state(
        self, loading: bool, status_message: Optional[str] = None
    ) -> None:
        self._loading.set_loading_state(loading, status_message)

    def log_import_event(self, message: str, *, reset: bool = False) -> None:
        self._messenger.log_import_event(message, reset=reset)

    def apply_saft_batch(self, results: Sequence[SaftLoadResult]) -> None:
        self._dataset_flow.apply_saft_batch(results)

    def activate_dataset(self, key: str, *, log_event: bool = False) -> None:
        self._dataset_flow.activate_dataset(key, log_event=log_event)

    def update_comparison_tables(self, rows: Optional[ComparisonRows]) -> None:
        self._dataset_flow.update_comparison_tables(rows)

    def build_brreg_comparison_rows(self) -> Optional[ComparisonRows]:
        return self._dataset_flow.build_brreg_comparison_rows()

    # endregion

    # region Hendelser
    def on_load_error(self, message: str) -> None:
        self._messenger.handle_load_error(message)

    def on_calc_top_customers(self, source: str, topn: int):
        return self._analytics_events.on_calc_top_customers(source, topn)

    def on_calc_top_suppliers(self, source: str, topn: int):
        return self._analytics_events.on_calc_top_suppliers(source, topn)

    # endregion


__all__ = ["SaftDataController"]
