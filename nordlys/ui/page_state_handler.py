"""Hjelpeklasse som samler all sidelogikk for SAF-T-kontrolleren."""

from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtWidgets import QWidget

from .pages import (
    ComparisonPage,
    RegnskapsanalysePage,
    SammenstillingsanalysePage,
    SummaryPage,
)
from .pages.dashboard_page import DashboardPage
from .pages.dataframe_page import DataFramePage
from .pages.import_page import ImportPage
from .pages.revision_pages import (
    ChecklistPage,
    CostVoucherReviewPage,
    PurchasesApPage,
    SalesArPage,
)
from .data_manager import SaftDatasetStore


ComparisonRows = Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]


class PageStateHandler:
    """Holder orden på aktive sider og sørger for oppdatering ved behov."""

    def __init__(
        self,
        dataset_store: SaftDatasetStore,
        revision_tasks: Mapping[str, Sequence[str]],
        schedule_responsive_update: Callable[[], None],
    ) -> None:
        self._dataset_store = dataset_store
        self._revision_tasks = revision_tasks
        self._schedule_responsive_update = schedule_responsive_update

        self.import_page: Optional[ImportPage] = None
        self.dashboard_page: Optional[DashboardPage] = None
        self.saldobalanse_page: Optional[DataFramePage] = None
        self.kontroll_page: Optional[ComparisonPage] = None
        self.regnskap_page: Optional[RegnskapsanalysePage] = None
        self.vesentlig_page: Optional[SummaryPage] = None
        self.sammenstilling_page: Optional[SammenstillingsanalysePage] = None
        self.sales_ar_page: Optional[SalesArPage] = None
        self.purchases_ap_page: Optional[PurchasesApPage] = None
        self.cost_review_page: Optional[CostVoucherReviewPage] = None
        self.revision_pages: Dict[str, QWidget] = {}

        self._latest_comparison_rows: Optional[
            List[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        ] = None

    def apply_page_state(self, key: str, widget: QWidget) -> None:
        """Lagrer referansen og oppdaterer siden med eksisterende data."""

        if key == "import" and isinstance(widget, ImportPage):
            self.import_page = widget
        if key in self._revision_tasks:
            self.revision_pages[key] = widget
        if key == "dashboard" and isinstance(widget, DashboardPage):
            self.dashboard_page = widget
            widget.update_summary(self._dataset_store.saft_summary)
        elif key == "plan.saldobalanse" and isinstance(widget, DataFramePage):
            self.saldobalanse_page = widget
            widget.set_dataframe(self._dataset_store.saft_df)
        elif key == "plan.kontroll" and isinstance(widget, ComparisonPage):
            self.kontroll_page = widget
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.regnskapsanalyse" and isinstance(
            widget, RegnskapsanalysePage
        ):
            self.regnskap_page = widget
            header = self._dataset_store.header
            fiscal_year = header.fiscal_year if header else None
            widget.set_dataframe(self._dataset_store.saft_df, fiscal_year)
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.vesentlighet" and isinstance(widget, SummaryPage):
            self.vesentlig_page = widget
            widget.update_summary(self._dataset_store.saft_summary)
        elif key == "plan.sammenstilling" and isinstance(
            widget, SammenstillingsanalysePage
        ):
            self.sammenstilling_page = widget
            header = self._dataset_store.header
            fiscal_year = header.fiscal_year if header else None
            widget.set_dataframe(self._dataset_store.saft_df, fiscal_year)
        elif key == "rev.salg" and isinstance(widget, SalesArPage):
            self.sales_ar_page = widget
            widget.set_checklist_items(self._revision_tasks.get("rev.salg", []))
            widget.set_controls_enabled(self._dataset_store.has_customer_data)
            widget.update_sales_reconciliation(
                self._dataset_store.customer_sales_total,
                self._dataset_store.sales_account_total,
            )
            if not self._dataset_store.has_customer_data:
                widget.clear_top_customers()
        elif key == "rev.innkjop" and isinstance(widget, PurchasesApPage):
            self.purchases_ap_page = widget
            widget.set_controls_enabled(self._dataset_store.has_supplier_data)
            if not self._dataset_store.has_supplier_data:
                widget.clear_top_suppliers()
        elif key == "rev.kostnad" and isinstance(widget, CostVoucherReviewPage):
            self.cost_review_page = widget
            widget.set_vouchers(self._dataset_store.cost_vouchers)
        elif key in self._revision_tasks and isinstance(widget, ChecklistPage):
            widget.set_items(list(self._revision_tasks.get(key, [])))
        self._schedule_responsive_update()

    def update_comparison_tables(self, rows: Optional[ComparisonRows]) -> None:
        self._latest_comparison_rows = list(rows) if rows is not None else None
        if self.kontroll_page:
            self.kontroll_page.update_comparison(rows)
        if self.regnskap_page:
            self.regnskap_page.update_comparison(rows)

    def clear_comparison_tables(self) -> None:
        self.update_comparison_tables(None)

    def build_brreg_comparison_rows(
        self,
    ) -> Optional[List[Tuple[str, Optional[float], Optional[float], Optional[float]]]]:
        summary = self._dataset_store.saft_summary
        brreg_map = self._dataset_store.brreg_map
        if not summary or not brreg_map:
            return None

        return [
            (
                "Driftsinntekter",
                summary.get("driftsinntekter"),
                brreg_map.get("driftsinntekter"),
                None,
            ),
            (
                "EBIT",
                summary.get("ebit"),
                brreg_map.get("ebit"),
                None,
            ),
            (
                "Årsresultat",
                summary.get("arsresultat"),
                brreg_map.get("arsresultat"),
                None,
            ),
            (
                "Eiendeler (UB)",
                summary.get("eiendeler_UB_brreg"),
                brreg_map.get("eiendeler_UB"),
                None,
            ),
            (
                "Egenkapital (UB)",
                summary.get("egenkapital_UB"),
                brreg_map.get("egenkapital_UB"),
                None,
            ),
            (
                "Gjeld (UB)",
                summary.get("gjeld_UB_brreg"),
                brreg_map.get("gjeld_UB"),
                None,
            ),
        ]


__all__ = ["PageStateHandler", "ComparisonRows"]
