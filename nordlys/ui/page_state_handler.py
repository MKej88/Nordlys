"""Hjelpeklasse som samler all sidelogikk for SAF-T-kontrolleren."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from PySide6.QtWidgets import QWidget

from ..helpers.formatting import format_currency
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
    FixedAssetsPage,
    PurchasesApPage,
    SalesArPage,
)
from .data_manager import SaftDatasetStore


ComparisonRows = Sequence[
    Tuple[str, Optional[float], Optional[float], Optional[float], Optional[str]]
]


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
        self.fixed_assets_page: Optional[FixedAssetsPage] = None
        self.revision_pages: Dict[str, QWidget] = {}

        self._latest_comparison_rows: Optional[
            List[
                Tuple[
                    str,
                    Optional[float],
                    Optional[float],
                    Optional[float],
                    Optional[str],
                ]
            ]
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
            widget.set_dataframe(
                self._dataset_store.saft_df, self._dataset_store.current_year_text
            )
            widget.set_summary_history(self._dataset_store.recent_summaries())
            widget.update_comparison(self._latest_comparison_rows)
        elif key == "plan.vesentlighet" and isinstance(widget, SummaryPage):
            self.vesentlig_page = widget
            widget.update_summary(self._dataset_store.saft_summary)
        elif key == "plan.sammenstilling" and isinstance(
            widget, SammenstillingsanalysePage
        ):
            self.sammenstilling_page = widget
            widget.set_dataframe(
                self._dataset_store.saft_df, self._dataset_store.current_year_text
            )
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
        elif key == "rev.driftsmidler" and isinstance(widget, FixedAssetsPage):
            self.fixed_assets_page = widget
            widget.update_data(
                self._dataset_store.saft_df, self._dataset_store.cost_vouchers
            )
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

    def build_brreg_comparison_rows(self) -> Optional[
        List[Tuple[str, Optional[float], Optional[float], Optional[float], Optional[str]]]
    ]:
        summary = self._dataset_store.saft_summary
        brreg_map = self._dataset_store.brreg_map
        if not summary or not brreg_map:
            return None

        base_rows: List[Tuple[str, Optional[float], Optional[float], Optional[float]]]
        base_rows = [
            (
                "Eiendeler",
                summary.get("eiendeler_UB_brreg"),
                brreg_map.get("eiendeler_UB"),
                None,
            ),
            (
                "Egenkapital",
                summary.get("egenkapital_UB"),
                brreg_map.get("egenkapital_UB"),
                None,
            ),
            (
                "Gjeld",
                summary.get("gjeld_UB_brreg"),
                brreg_map.get("gjeld_UB"),
                None,
            ),
        ]

        rows_with_explanations: List[
            Tuple[str, Optional[float], Optional[float], Optional[float], Optional[str]]
        ] = []
        for label, saf_value, brreg_value, _ in base_rows:
            diff = self._safe_difference(saf_value, brreg_value)
            explanation = None
            if diff is not None and abs(diff) > 2:
                match = self._find_balance_match(diff)
                if match:
                    explanation = self._format_match_explanation(match)

            rows_with_explanations.append(
                (label, saf_value, brreg_value, diff, explanation)
            )

        return rows_with_explanations

    def _safe_difference(
        self, saf_value: Optional[float], brreg_value: Optional[float]
    ) -> Optional[float]:
        if saf_value is None or brreg_value is None:
            return None
        try:
            return float(saf_value) - float(brreg_value)
        except (TypeError, ValueError):
            return None

    def _find_balance_match(
        self, target: float
    ) -> Optional[Tuple[str, str, float, str]]:
        df = self._dataset_store.saft_df
        if df is None or df.empty:
            return None

        account_col = self._first_existing_column(df, ("Konto", "AccountID"))
        if account_col is None:
            return None
        name_col = self._first_existing_column(df, ("Kontonavn", "AccountDescription"))

        series_candidates = list(self._balance_series(df))
        if not series_candidates:
            return None

        tolerance = 2.0
        best_match: Optional[Tuple[int, float, float, str]] = None

        def _update_best(
            column_name: str,
            numeric_series: pd.Series,
            *,
            comparison_target: float,
            source_series: pd.Series,
        ) -> None:
            nonlocal best_match
            deltas = (numeric_series - comparison_target).abs()
            close_mask = deltas <= tolerance
            if not close_mask.any():
                return
            idx = int(deltas[close_mask].idxmin())
            distance = float(deltas.loc[idx])
            value = float(source_series.loc[idx])
            if best_match is None or distance < best_match[2]:
                best_match = (idx, value, distance, column_name)

        for column_name, series in series_candidates:
            numeric_series = pd.to_numeric(series, errors="coerce")
            if numeric_series.notna().any():
                _update_best(
                    column_name,
                    numeric_series,
                    comparison_target=target,
                    source_series=numeric_series,
                )
            abs_series = numeric_series.abs()
            if abs_series.notna().any():
                _update_best(
                    column_name,
                    abs_series,
                    comparison_target=abs(target),
                    source_series=numeric_series,
                )

        if best_match is None:
            return None

        index, value, _, column_name = best_match
        raw_account = df.at[index, account_col]
        account_value = "" if pd.isna(raw_account) else str(raw_account).strip()
        name_value = ""
        if name_col:
            raw_name = df.at[index, name_col]
            if not pd.isna(raw_name):
                name_value = str(raw_name).strip()
        return account_value, name_value, value, column_name

    def _balance_series(self, df: pd.DataFrame) -> Iterable[Tuple[str, pd.Series]]:
        seen: set[str] = set()

        def _existing(column: str) -> Optional[pd.Series]:
            return df[column] if column in df.columns else None

        for column in ("UB_netto", "UB", "IB_netto", "IB"):
            series = _existing(column)
            if series is not None and column not in seen:
                seen.add(column)
                yield column, series

        debit = df.get("UB Debet")
        credit = df.get("UB Kredit")
        if debit is not None and credit is not None and "UB" not in seen:
            seen.add("UB")
            yield "UB", pd.to_numeric(debit, errors="coerce") - pd.to_numeric(
                credit, errors="coerce"
            )

    @staticmethod
    def _first_existing_column(
        df: pd.DataFrame, candidates: Sequence[str]
    ) -> Optional[str]:
        for column in candidates:
            if column in df.columns:
                return column
        return None

    @staticmethod
    def _format_match_explanation(match: Tuple[str, str, float, str]) -> str:
        account, name, value, column = match
        column_label = "UB" if "UB" in column.upper() else "IB"
        account_label = account or "ukjent konto"
        name_label = f" ({name})" if name else ""
        value_text = format_currency(value)
        return (
            f"Mulig forklaring: konto {account_label}{name_label} "
            f"har {value_text} i {column_label.lower()}."
        )


__all__ = ["PageStateHandler", "ComparisonRows"]
