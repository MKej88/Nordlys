"""Oppdaterer GUI når et nytt SAF-T-datasett aktiveres."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox

from ...saft.periods import format_header_period
from ...helpers.formatting import format_currency
from ..page_state_handler import ComparisonRows
from .context import ControllerContext
from .messaging import ImportMessenger

if TYPE_CHECKING:
    from ...saft.loader import SaftLoadResult


class DatasetFlowController:
    """Håndterer aktivisering av datasett og oppdatering av sidene."""

    def __init__(self, context: ControllerContext, messenger: ImportMessenger) -> None:
        self._context = context
        self._messenger = messenger

    def apply_saft_batch(self, results: Sequence[SaftLoadResult]) -> None:
        store = self._context.dataset_store
        if not results:
            store.reset()
            self._update_dataset_selector()
            self._reset_ui_state()
            return

        store.apply_batch(results)
        self._update_dataset_selector()

        default_key = store.select_default_key()
        if default_key is None:
            return

        self.activate_dataset(default_key, log_event=True)
        if len(results) > 1:
            self._messenger.log_import_event(
                "Alle filer er lastet inn. Bruk årvelgeren for å bytte datasett."
            )

    def activate_dataset(self, key: str, *, log_event: bool = False) -> None:
        store = self._context.dataset_store
        header_bar = self._context.header_bar
        if not store.activate(key):
            return
        dataset_items = store.dataset_items()
        keys = [item.key for item in dataset_items]
        if key in keys:
            header_bar.select_dataset(key)
        self._apply_saft_result(key, log_event=log_event)
        if not log_event:
            current_result = store.current_result
            if current_result is not None:
                label = store.dataset_label(current_result)
                self._messenger.log_import_event(f"Viser datasett: {label}")

    def update_comparison_tables(
        self,
        rows: Optional[ComparisonRows],
        suggestions: Optional[Sequence[str]] = None,
    ) -> None:
        self._context.pages.update_comparison_tables(rows, suggestions)

    def build_brreg_comparison_rows(
        self,
    ) -> Optional[Tuple[ComparisonRows, List[str]]]:
        return self._context.pages.build_brreg_comparison_rows()

    def _apply_saft_result(self, _key: str, *, log_event: bool = False) -> None:
        store = self._context.dataset_store
        pages = self._context.pages
        messenger = self._messenger

        result = store.current_result
        if result is None:
            return

        if pages.import_page:
            pages.import_page.update_invoice_count(len(store.cost_vouchers))

        saft_df = store.saft_df
        if saft_df is None:
            saft_df = result.dataframe
        self._context.update_header_fields()
        if pages.saldobalanse_page:
            pages.saldobalanse_page.set_dataframe(saft_df)
        pages.clear_comparison_tables()
        if pages.dashboard_page:
            pages.dashboard_page.update_summary(store.saft_summary)

        header = store.header
        company = header.company_name if header else None
        orgnr = header.orgnr if header else None
        period = format_header_period(header)
        summary = store.saft_summary or {}
        revenue_value = summary.get("driftsinntekter")
        revenue_txt = (
            format_currency(revenue_value) if revenue_value is not None else "—"
        )
        account_count = len(saft_df.index)
        dataset_label = store.dataset_label(result)
        status_bits = [
            company or "Ukjent selskap",
            f"Org.nr: {orgnr}" if orgnr else "Org.nr: –",
            f"Periode: {period}" if period else None,
            f"{account_count} konti analysert",
            f"Driftsinntekter: {revenue_txt}",
            f"Datasett: {dataset_label}",
        ]
        status_message = " · ".join(bit for bit in status_bits if bit)
        if pages.import_page:
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
            pages.import_page.update_misc_info(misc_entries)
            pages.import_page.update_status(status_message)
        if log_event:
            messenger.log_import_event(
                f"{dataset_label or Path(result.file_path).name}: SAF-T lesing fullført. "
                f"{account_count} konti analysert."
            )

        validation = store.validation_result
        if pages.import_page:
            pages.import_page.update_validation_status(validation)
        if log_event and validation is not None:
            if validation.is_valid is True:
                messenger.log_import_event("XSD-validering fullført: OK.")
            elif validation.is_valid is False:
                messenger.log_import_event("XSD-validering feilet.")
            elif validation.is_valid is None and validation.details:
                messenger.log_import_event(
                    "XSD-validering: detaljer tilgjengelig, se importstatus."
                )
        if validation and validation.is_valid is False:
            if pages.import_page:
                detail = (
                    validation.details.strip().splitlines()[0]
                    if validation.details and validation.details.strip()
                    else "Valideringen mot XSD feilet."
                )
                pages.import_page.record_error(f"XSD-validering: {detail}")
            QMessageBox.warning(
                self._context.parent,
                "XSD-validering feilet",
                validation.details
                or "Valideringen mot XSD feilet. Se Import-siden for detaljer.",
            )
        elif validation and validation.is_valid is None and validation.details:
            QMessageBox.information(
                self._context.parent, "XSD-validering", validation.details
            )

        trial_message = "Prøvebalanse er ikke beregnet (streaming er av)."
        if store.trial_balance_checked:
            if store.trial_balance_error:
                trial_message = f"Prøvebalanse: {store.trial_balance_error}"
                if pages.import_page:
                    pages.import_page.record_error(trial_message)
                messenger.log_import_event(trial_message)
                QMessageBox.warning(
                    self._context.parent,
                    "Prøvebalanse har avvik",
                    trial_message,
                )
            else:
                trial_message = "Prøvebalanse: OK"
                if log_event:
                    messenger.log_import_event(trial_message)
        if pages.import_page:
            pages.import_page.update_trial_balance_status(trial_message)

        if pages.sales_ar_page:
            pages.sales_ar_page.set_controls_enabled(store.has_customer_data)
            pages.sales_ar_page.update_sales_reconciliation(
                store.customer_sales_total,
                store.sales_account_total,
            )
            pages.sales_ar_page.clear_top_customers()
            pages.sales_ar_page.set_credit_notes(
                store.credit_note_rows(), store.credit_note_monthly_summary()
            )
            pages.sales_ar_page.set_sales_correlation(
                store.sales_with_receivable_total,
                store.sales_without_receivable_total,
                store.sales_without_receivable_rows(),
            )
            pages.sales_ar_page.set_receivable_overview(
                store.receivable_analysis,
                store.receivable_unclassified_rows(),
            )
            pages.sales_ar_page.set_bank_overview(store.bank_analysis)
        if pages.purchases_ap_page:
            pages.purchases_ap_page.set_controls_enabled(store.has_supplier_data)
            pages.purchases_ap_page.clear_top_suppliers()
        if pages.cost_review_page:
            pages.cost_review_page.set_vouchers(store.cost_vouchers)
        if pages.fixed_assets_page:
            pages.fixed_assets_page.update_data(store.saft_df, store.cost_vouchers)

        if pages.vesentlig_page:
            pages.vesentlig_page.update_summary(
                store.saft_summary,
                industry=store.industry,
                industry_error=store.industry_error,
            )
        fiscal_year = store.current_year_text
        if pages.regnskap_page:
            pages.regnskap_page.set_dataframe(saft_df, fiscal_year)
            pages.regnskap_page.set_summary_history(store.recent_summaries())
        if pages.sammenstilling_page:
            pages.sammenstilling_page.set_dataframe(saft_df, fiscal_year)
        brreg_status = self._process_brreg_result(result)

        self._context.header_bar.set_export_enabled(True)
        dataset_count = len(store.dataset_order)
        status_parts = [
            f"Datasett aktivt: {dataset_label or Path(result.file_path).name}."
        ]
        if dataset_count > 1:
            status_parts.append(f"{dataset_count} filer tilgjengelig.")
        if brreg_status:
            status_parts.append(brreg_status)
        self._context.status_bar.showMessage(" ".join(status_parts))

    def _reset_ui_state(self) -> None:
        pages = self._context.pages
        header_bar = self._context.header_bar
        store = self._context.dataset_store

        header_bar.set_export_enabled(False)
        header_bar.set_dataset_enabled(False)
        self._context.update_header_fields()
        self._context.status_bar.showMessage("Ingen datasett aktivt.")

        if pages.import_page:
            pages.import_page.update_status("Ingen SAF-T fil er lastet inn ennå.")
            pages.import_page.update_trial_balance_status(
                "Prøvebalanse er ikke beregnet ennå."
            )
            pages.import_page.update_validation_status(None)
            pages.import_page.update_brreg_status(
                "Regnskapsregister: ingen data importert ennå."
            )
            pages.import_page.update_invoice_count(None)
            pages.import_page.update_misc_info(None)
            pages.import_page.reset_errors()

        pages.clear_comparison_tables()

        if pages.dashboard_page:
            pages.dashboard_page.update_summary(None)
        if pages.saldobalanse_page:
            pages.saldobalanse_page.set_dataframe(None)
        if pages.regnskap_page:
            pages.regnskap_page.set_dataframe(None, None)
            pages.regnskap_page.set_summary_history([])
        if pages.vesentlig_page:
            pages.vesentlig_page.update_summary(
                None,
                industry=store.industry,
                industry_error=store.industry_error,
            )
        if pages.sammenstilling_page:
            pages.sammenstilling_page.set_dataframe(None, None)
        if pages.sales_ar_page:
            pages.sales_ar_page.set_controls_enabled(False)
            pages.sales_ar_page.update_sales_reconciliation(None, None)
            pages.sales_ar_page.clear_top_customers()
            pages.sales_ar_page.clear_sales_correlation()
            pages.sales_ar_page.clear_credit_notes()
            pages.sales_ar_page.clear_receivable_overview()
        if pages.purchases_ap_page:
            pages.purchases_ap_page.set_controls_enabled(False)
            pages.purchases_ap_page.clear_top_suppliers()
        if pages.cost_review_page:
            pages.cost_review_page.set_vouchers([])
        if pages.fixed_assets_page:
            pages.fixed_assets_page.clear()

    def _update_dataset_selector(self) -> None:
        store = self._context.dataset_store
        header_bar = self._context.header_bar
        dataset_items = store.dataset_items()
        if not dataset_items:
            header_bar.clear_datasets()
            return
        entries = [
            (item.key, store.dataset_label(item.result)) for item in dataset_items
        ]
        header_bar.set_dataset_items(entries, store.current_key)
        header_bar.set_dataset_enabled(True)

    def _process_brreg_result(self, result: SaftLoadResult) -> str:
        store = self._context.dataset_store
        pages = self._context.pages
        messenger = self._messenger

        if pages.import_page:
            pages.import_page.update_industry(store.industry, store.industry_error)

        brreg_json = store.brreg_json

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
            if pages.import_page:
                pages.import_page.update_brreg_status(message)
                pages.import_page.record_error(message)
            messenger.log_import_event(message)
            return message

        summary = store.saft_summary
        if not summary:
            self.update_comparison_tables(None)
            message = (
                "Regnskapsregister: import vellykket, men ingen SAF-T-oppsummering å "
                "sammenligne."
            )
            if pages.import_page:
                pages.import_page.update_brreg_status(message)
            messenger.log_import_event(message)
            return message

        comparison_result = self.build_brreg_comparison_rows()
        if comparison_result is None:
            self.update_comparison_tables(None, None)
        else:
            rows, suggestions = comparison_result
            self.update_comparison_tables(rows, suggestions)
        message = "Regnskapsregister: import vellykket."
        if pages.import_page:
            pages.import_page.update_brreg_status(message)
        messenger.log_import_event(message)
        return message
