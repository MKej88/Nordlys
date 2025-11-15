"""Samler datalogikken som tidligere lå direkte i `NordlysWindow`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox, QStatusBar, QWidget

from ..saft.loader import SaftLoadResult
from ..utils import format_currency
from .config import REVISION_TASKS
from .data_manager import DataUnavailableError, SaftAnalytics, SaftDatasetStore
from .header_bar import HeaderBar
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


ComparisonRows = Sequence[Tuple[str, Optional[float], Optional[float], Optional[float]]]


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
        self._schedule_responsive_update = schedule_responsive_update
        self._update_header_fields = update_header_fields

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

        self._latest_comparison_rows: Optional[ComparisonRows] = None

    # region Sider og oppdatering
    def apply_page_state(self, key: str, widget: QWidget) -> None:
        """Oppdaterer en side med gjeldende data når den opprettes."""

        if key == "import" and isinstance(widget, ImportPage):
            self.import_page = widget
        if key in REVISION_TASKS:
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
            widget.set_checklist_items(REVISION_TASKS.get("rev.salg", []))
            widget.set_controls_enabled(self._dataset_store.has_customer_data)
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
        elif key in REVISION_TASKS and isinstance(widget, ChecklistPage):
            widget.set_items(REVISION_TASKS.get(key, []))
        self._schedule_responsive_update()

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
        if self.sales_ar_page:
            if loading:
                self.sales_ar_page.set_controls_enabled(False)
            else:
                self.sales_ar_page.set_controls_enabled(
                    self._dataset_store.has_customer_data
                )
        if self.purchases_ap_page:
            if loading:
                self.purchases_ap_page.set_controls_enabled(False)
            else:
                self.purchases_ap_page.set_controls_enabled(
                    self._dataset_store.has_supplier_data
                )
        if status_message:
            self._status_bar.showMessage(status_message)

    def log_import_event(self, message: str, *, reset: bool = False) -> None:
        if not self.import_page:
            return
        if reset:
            self.import_page.reset_log()
            self.import_page.reset_errors()
        self.import_page.append_log(message)

    def apply_saft_batch(self, results: Sequence[SaftLoadResult]) -> None:
        if not results:
            self._dataset_store.reset()
            self._update_dataset_selector()
            if self.import_page:
                self.import_page.update_invoice_count(None)
                self.import_page.update_misc_info(None)
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

        if self.import_page:
            self.import_page.update_invoice_count(
                len(self._dataset_store.cost_vouchers)
            )

        saft_df = self._dataset_store.saft_df or result.dataframe
        self._update_header_fields()
        if self.saldobalanse_page:
            self.saldobalanse_page.set_dataframe(saft_df)
        self._latest_comparison_rows = None
        if self.kontroll_page:
            self.kontroll_page.update_comparison(None)
        if self.dashboard_page:
            self.dashboard_page.update_summary(self._dataset_store.saft_summary)

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
        if self.import_page:
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
            self.import_page.update_misc_info(misc_entries)
            self.import_page.update_status(status_message)
        if log_event:
            self.log_import_event(
                f"{dataset_label or Path(result.file_path).name}: SAF-T lesing fullført. "
                f"{account_count} konti analysert."
            )

        validation = self._dataset_store.validation_result
        if self.import_page:
            self.import_page.update_validation_status(validation)
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
            if self.import_page:
                detail = (
                    validation.details.strip().splitlines()[0]
                    if validation.details and validation.details.strip()
                    else "Valideringen mot XSD feilet."
                )
                self.import_page.record_error(f"XSD-validering: {detail}")
            QMessageBox.warning(
                self._parent,
                "XSD-validering feilet",
                validation.details
                or "Valideringen mot XSD feilet. Se Import-siden for detaljer.",
            )
        elif validation and validation.is_valid is None and validation.details:
            QMessageBox.information(self._parent, "XSD-validering", validation.details)

        if self.sales_ar_page:
            self.sales_ar_page.set_controls_enabled(
                self._dataset_store.has_customer_data
            )
            self.sales_ar_page.clear_top_customers()
        if self.purchases_ap_page:
            self.purchases_ap_page.set_controls_enabled(
                self._dataset_store.has_supplier_data
            )
            self.purchases_ap_page.clear_top_suppliers()
        if self.cost_review_page:
            self.cost_review_page.set_vouchers(self._dataset_store.cost_vouchers)

        if self.vesentlig_page:
            self.vesentlig_page.update_summary(self._dataset_store.saft_summary)
        if self.regnskap_page:
            fiscal_year = header.fiscal_year if header else None
            self.regnskap_page.set_dataframe(saft_df, fiscal_year)
        if self.sammenstilling_page:
            fiscal_year = header.fiscal_year if header else None
            self.sammenstilling_page.set_dataframe(saft_df, fiscal_year)
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
        if self.import_page:
            self.import_page.update_industry(
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
            if self.import_page:
                self.import_page.update_brreg_status(message)
                self.import_page.record_error(message)
            self.log_import_event(message)
            return message

        summary = self._dataset_store.saft_summary
        if not summary:
            self.update_comparison_tables(None)
            message = (
                "Regnskapsregister: import vellykket, men ingen SAF-T-oppsummering å "
                "sammenligne."
            )
            if self.import_page:
                self.import_page.update_brreg_status(message)
            self.log_import_event(message)
            return message

        comparison_rows = self.build_brreg_comparison_rows()
        self.update_comparison_tables(comparison_rows)
        message = "Regnskapsregister: import vellykket."
        if self.import_page:
            self.import_page.update_brreg_status(message)
        self.log_import_event(message)
        return message

    def update_comparison_tables(self, rows: Optional[ComparisonRows]) -> None:
        self._latest_comparison_rows = list(rows) if rows is not None else None
        if self.kontroll_page:
            self.kontroll_page.update_comparison(rows)
        if self.regnskap_page:
            self.regnskap_page.update_comparison(rows)

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

    # endregion

    # region Hendelser
    def on_load_error(self, message: str) -> None:
        self.log_import_event(f"Feil ved lesing av SAF-T: {message}")
        if self.import_page:
            self.import_page.record_error(f"Lesing av SAF-T: {message}")
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
