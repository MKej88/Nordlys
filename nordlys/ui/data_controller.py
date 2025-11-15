"""Samler datalogikken som tidligere lå direkte i `NordlysWindow`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox, QStatusBar, QWidget

from ..saft.loader import SaftLoadResult
from ..utils import format_currency
from .config import REVISION_TASKS
from .data_manager import DataUnavailableError, SaftAnalytics, SaftDatasetStore
from .header_bar import HeaderBar
from .page_state_handler import ComparisonRows, PageStateHandler

if TYPE_CHECKING:
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
        CostVoucherReviewPage,
        PurchasesApPage,
        SalesArPage,
    )


class SaftDataController:
    """Eier datasett, analyser og oppdaterer sidene når noe endrer seg."""

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
        self._dataset_store = dataset_store
        self._analytics = analytics
        self._header_bar = header_bar
        self._status_bar = status_bar
        self._parent = parent
        self._update_header_fields = update_header_fields
        self._pages = PageStateHandler(
            dataset_store,
            REVISION_TASKS,
            schedule_responsive_update,
        )

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
    def revision_pages(self) -> Dict[str, QWidget]:
        return self._pages.revision_pages

    # region Sider og oppdatering
    def apply_page_state(self, key: str, widget: QWidget) -> None:
        """Oppdaterer en side med gjeldende data når den opprettes."""

        self._pages.apply_page_state(key, widget)

    # endregion

    # region Import- og datasettlogikk
    def set_loading_state(
        self, loading: bool, status_message: Optional[str] = None
    ) -> None:
        self._header_bar.set_open_enabled(not loading)
        has_data = self._dataset_store.saft_df is not None
        self._header_bar.set_export_enabled(False if loading else has_data)
        if loading:
            self._header_bar.set_dataset_enabled(False)
        else:
            self._header_bar.set_dataset_enabled(
                bool(self._dataset_store.dataset_order)
            )
        if self._pages.sales_ar_page:
            if loading:
                self._pages.sales_ar_page.set_controls_enabled(False)
            else:
                self._pages.sales_ar_page.set_controls_enabled(
                    self._dataset_store.has_customer_data
                )
        if self._pages.purchases_ap_page:
            if loading:
                self._pages.purchases_ap_page.set_controls_enabled(False)
            else:
                self._pages.purchases_ap_page.set_controls_enabled(
                    self._dataset_store.has_supplier_data
                )
        if status_message:
            self._status_bar.showMessage(status_message)

    def log_import_event(self, message: str, *, reset: bool = False) -> None:
        if not self._pages.import_page:
            return
        if reset:
            self._pages.import_page.reset_log()
            self._pages.import_page.reset_errors()
        self._pages.import_page.append_log(message)

    def apply_saft_batch(self, results: Sequence[SaftLoadResult]) -> None:
        if not results:
            self._dataset_store.reset()
            self._update_dataset_selector()
            if self._pages.import_page:
                self._pages.import_page.update_invoice_count(None)
                self._pages.import_page.update_misc_info(None)
            return

        self._dataset_store.apply_batch(results)
        self._update_dataset_selector()

        default_key = self._dataset_store.select_default_key()
        if default_key is None:
            return

        self.activate_dataset(default_key, log_event=True)
        if len(results) > 1:
            self.log_import_event(
                "Alle filer er lastet inn. Bruk årvelgeren for å bytte datasett."
            )

    def activate_dataset(self, key: str, *, log_event: bool = False) -> None:
        if not self._dataset_store.activate(key):
            return
        dataset_items = self._dataset_store.dataset_items()
        keys = [item.key for item in dataset_items]
        if key in keys:
            self._header_bar.select_dataset(key)
        self._apply_saft_result(key, log_event=log_event)
        if not log_event:
            current_result = self._dataset_store.current_result
            if current_result is not None:
                label = self._dataset_store.dataset_label(current_result)
                self.log_import_event(f"Viser datasett: {label}")

    def _apply_saft_result(self, _key: str, *, log_event: bool = False) -> None:
        result = self._dataset_store.current_result
        if result is None:
            return

        if self._pages.import_page:
            self._pages.import_page.update_invoice_count(
                len(self._dataset_store.cost_vouchers)
            )

        saft_df = self._dataset_store.saft_df
        if saft_df is None:
            saft_df = result.dataframe
        self._update_header_fields()
        if self._pages.saldobalanse_page:
            self._pages.saldobalanse_page.set_dataframe(saft_df)
        self._pages.clear_comparison_tables()
        if self._pages.dashboard_page:
            self._pages.dashboard_page.update_summary(self._dataset_store.saft_summary)

        header = self._dataset_store.header
        company = header.company_name if header else None
        orgnr = header.orgnr if header else None
        period = None
        if header:
            period = (
                f"{header.fiscal_year or '—'} "
                f"P{header.period_start or '?'}–P{header.period_end or '?'}"
            )
        summary = self._dataset_store.saft_summary or {}
        revenue_value = summary.get("driftsinntekter")
        revenue_txt = (
            format_currency(revenue_value) if revenue_value is not None else "—"
        )
        account_count = len(saft_df.index)
        dataset_label = self._dataset_store.dataset_label(result)
        status_bits = [
            company or "Ukjent selskap",
            f"Org.nr: {orgnr}" if orgnr else "Org.nr: –",
            f"Periode: {period}" if period else None,
            f"{account_count} konti analysert",
            f"Driftsinntekter: {revenue_txt}",
            f"Datasett: {dataset_label}",
        ]
        status_message = " · ".join(bit for bit in status_bits if bit)
        if self._pages.import_page:
            misc_entries: List[Tuple[str, str]] = [
                ("Datasett", dataset_label or Path(result.file_path).name),
                ("Filnavn", Path(result.file_path).name),
                ("Konti analysert", str(account_count)),
            ]
            if company:
                misc_entries.append(("Selskap", str(company)))
            if orgnr:
                misc_entries.append(("Org.nr", str(orgnr)))
            if period:
                misc_entries.append(("Periode", period))
            if revenue_txt and revenue_txt != "—":
                misc_entries.append(("Driftsinntekter", revenue_txt))
            misc_entries.append(
                ("Oppdatert", datetime.now().strftime("%d.%m.%Y %H:%M"))
            )
            self._pages.import_page.update_misc_info(misc_entries)
            self._pages.import_page.update_status(status_message)
        if log_event:
            self.log_import_event(
                f"{dataset_label or Path(result.file_path).name}: SAF-T lesing fullført. "
                f"{account_count} konti analysert."
            )

        validation = self._dataset_store.validation_result
        if self._pages.import_page:
            self._pages.import_page.update_validation_status(validation)
        if log_event and validation is not None:
            if validation.is_valid is True:
                self.log_import_event("XSD-validering fullført: OK.")
            elif validation.is_valid is False:
                self.log_import_event("XSD-validering feilet.")
            elif validation.is_valid is None and validation.details:
                self.log_import_event(
                    "XSD-validering: detaljer tilgjengelig, se importstatus."
                )
        if validation and validation.is_valid is False:
            if self._pages.import_page:
                detail = (
                    validation.details.strip().splitlines()[0]
                    if validation.details and validation.details.strip()
                    else "Valideringen mot XSD feilet."
                )
                self._pages.import_page.record_error(f"XSD-validering: {detail}")
            QMessageBox.warning(
                self._parent,
                "XSD-validering feilet",
                validation.details
                or "Valideringen mot XSD feilet. Se Import-siden for detaljer.",
            )
        elif validation and validation.is_valid is None and validation.details:
            QMessageBox.information(self._parent, "XSD-validering", validation.details)

        if self._pages.sales_ar_page:
            self._pages.sales_ar_page.set_controls_enabled(
                self._dataset_store.has_customer_data
            )
            self._pages.sales_ar_page.clear_top_customers()
        if self._pages.purchases_ap_page:
            self._pages.purchases_ap_page.set_controls_enabled(
                self._dataset_store.has_supplier_data
            )
            self._pages.purchases_ap_page.clear_top_suppliers()
        if self._pages.cost_review_page:
            self._pages.cost_review_page.set_vouchers(self._dataset_store.cost_vouchers)

        if self._pages.vesentlig_page:
            self._pages.vesentlig_page.update_summary(self._dataset_store.saft_summary)
        if self._pages.regnskap_page:
            fiscal_year = header.fiscal_year if header else None
            self._pages.regnskap_page.set_dataframe(saft_df, fiscal_year)
        if self._pages.sammenstilling_page:
            fiscal_year = header.fiscal_year if header else None
            self._pages.sammenstilling_page.set_dataframe(saft_df, fiscal_year)
        brreg_status = self._process_brreg_result(result)

        self._header_bar.set_export_enabled(True)
        dataset_count = len(self._dataset_store.dataset_order)
        status_parts = [
            f"Datasett aktivt: {dataset_label or Path(result.file_path).name}."
        ]
        if dataset_count > 1:
            status_parts.append(f"{dataset_count} filer tilgjengelig.")
        if brreg_status:
            status_parts.append(brreg_status)
        self._status_bar.showMessage(" ".join(status_parts))

    def _update_dataset_selector(self) -> None:
        dataset_items = self._dataset_store.dataset_items()
        if not dataset_items:
            self._header_bar.clear_datasets()
            return
        entries = [
            (item.key, self._dataset_store.dataset_label(item.result))
            for item in dataset_items
        ]
        self._header_bar.set_dataset_items(entries, self._dataset_store.current_key)
        self._header_bar.set_dataset_enabled(True)

    # endregion

    # region Brreg og analyser
    def _process_brreg_result(self, result: SaftLoadResult) -> str:
        if self._pages.import_page:
            self._pages.import_page.update_industry(
                self._dataset_store.industry, self._dataset_store.industry_error
            )

        brreg_json = self._dataset_store.brreg_json

        if brreg_json is None:
            self.update_comparison_tables(None)
            if result.brreg_error:
                error_text = str(result.brreg_error).strip()
                if "\n" in error_text:
                    error_text = error_text.splitlines()[0]
                message = f"Regnskapsregister: import feilet ({error_text})."
            elif result.header and result.header.orgnr:
                message = "Regnskapsregister: import feilet."
            else:
                message = "Regnskapsregister: ikke tilgjengelig (mangler org.nr.)."
            if self._pages.import_page:
                self._pages.import_page.update_brreg_status(message)
                self._pages.import_page.record_error(message)
            self.log_import_event(message)
            return message

        summary = self._dataset_store.saft_summary
        if not summary:
            self.update_comparison_tables(None)
            message = (
                "Regnskapsregister: import vellykket, men ingen SAF-T-oppsummering å "
                "sammenligne."
            )
            if self._pages.import_page:
                self._pages.import_page.update_brreg_status(message)
            self.log_import_event(message)
            return message

        comparison_rows = self.build_brreg_comparison_rows()
        self.update_comparison_tables(comparison_rows)
        message = "Regnskapsregister: import vellykket."
        if self._pages.import_page:
            self._pages.import_page.update_brreg_status(message)
        self.log_import_event(message)
        return message

    def update_comparison_tables(self, rows: Optional[ComparisonRows]) -> None:
        self._pages.update_comparison_tables(rows)

    def build_brreg_comparison_rows(
        self,
    ) -> Optional[List[Tuple[str, Optional[float], Optional[float], Optional[float]]]]:
        return self._pages.build_brreg_comparison_rows()

    # endregion

    # region Hendelser
    def on_load_error(self, message: str) -> None:
        self.log_import_event(f"Feil ved lesing av SAF-T: {message}")
        if self._pages.import_page:
            self._pages.import_page.record_error(f"Lesing av SAF-T: {message}")
        QMessageBox.critical(self._parent, "Feil ved lesing av SAF-T", message)

    def on_calc_top_customers(
        self, source: str, topn: int
    ) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source
        try:
            rows = self._analytics.top_customers(topn)
        except DataUnavailableError as exc:
            QMessageBox.information(self._parent, "Ingen inntektslinjer", str(exc))
            return None
        self._status_bar.showMessage(f"Topp kunder (3xxx) beregnet. N={topn}.")
        return rows

    def on_calc_top_suppliers(
        self, source: str, topn: int
    ) -> Optional[List[Tuple[str, str, int, float]]]:
        _ = source
        try:
            rows = self._analytics.top_suppliers(topn)
        except DataUnavailableError as exc:
            QMessageBox.information(self._parent, "Ingen innkjøpslinjer", str(exc))
            return None
        self._status_bar.showMessage(
            "Innkjøp per leverandør (kostnadskonti 4xxx–8xxx) beregnet. " f"N={topn}."
        )
        return rows

    # endregion


__all__ = ["SaftDataController"]
