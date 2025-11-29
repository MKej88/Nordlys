"""Hjelpeklasse som samler all sidelogikk for SAF-T-kontrolleren."""

from __future__ import annotations

from dataclasses import dataclass
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


ComparisonRow = Tuple[str, Optional[float], Optional[float], Optional[float]]
ComparisonRows = Sequence[ComparisonRow]


@dataclass(frozen=True)
class BalanceEntry:
    account: str
    name: str
    value: float
    column: str


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

        self._latest_comparison_rows: Optional[List[ComparisonRow]] = None
        self._latest_comparison_suggestions: Optional[List[str]] = None

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
            widget.update_suggestions(self._latest_comparison_suggestions)
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

    def update_comparison_tables(
        self,
        rows: Optional[ComparisonRows],
        suggestions: Optional[Sequence[str]] = None,
    ) -> None:
        self._latest_comparison_rows = list(rows) if rows is not None else None
        self._latest_comparison_suggestions = (
            list(suggestions) if suggestions is not None else None
        )
        if self.kontroll_page:
            self.kontroll_page.update_comparison(rows)
            self.kontroll_page.update_suggestions(self._latest_comparison_suggestions)
        if self.regnskap_page:
            self.regnskap_page.update_comparison(rows)

    def clear_comparison_tables(self) -> None:
        self.update_comparison_tables(None, None)

    def build_brreg_comparison_rows(
        self,
    ) -> Optional[Tuple[List[ComparisonRow], List[str]]]:
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

        comparison_rows: List[ComparisonRow] = []
        suggestions: List[str] = []
        for label, saf_value, brreg_value, _ in base_rows:
            diff = self._safe_difference(saf_value, brreg_value)
            if diff is not None and abs(diff) > 1:
                matches = self._find_balance_matches(diff)
                if matches:
                    suggestions.extend(
                        self._format_match_suggestions(label, diff, matches)
                    )

            comparison_rows.append((label, saf_value, brreg_value, diff))

        return comparison_rows, suggestions

    def _safe_difference(
        self, saf_value: Optional[float], brreg_value: Optional[float]
    ) -> Optional[float]:
        if saf_value is None or brreg_value is None:
            return None
        try:
            return float(saf_value) - float(brreg_value)
        except (TypeError, ValueError):
            return None

    def _find_balance_matches(self, target: float) -> List[List[BalanceEntry]]:
        df = self._dataset_store.saft_df
        if df is None or df.empty:
            return []

        account_col = self._first_existing_column(df, ("Konto", "AccountID"))
        if account_col is None:
            return []
        name_col = self._first_existing_column(df, ("Kontonavn", "AccountDescription"))

        for column_name, series in self._balance_series(df):
            numeric_series = pd.to_numeric(series, errors="coerce").dropna()
            if numeric_series.empty:
                continue

            entries = []
            for idx, value in numeric_series.items():
                if abs(value) < 0.5:
                    continue
                raw_account = df.at[idx, account_col]
                account_value = "" if pd.isna(raw_account) else str(raw_account).strip()
                name_value = ""
                if name_col:
                    raw_name = df.at[idx, name_col]
                    if not pd.isna(raw_name):
                        name_value = str(raw_name).strip()
                entries.append(
                    BalanceEntry(account_value, name_value, float(value), column_name)
                )

            matches = self._search_matches(entries, target)
            if matches:
                return matches

        return []

    def _search_matches(
        self, entries: Sequence[BalanceEntry], target: float
    ) -> List[List[BalanceEntry]]:
        tolerance = 1.0
        matches: List[List[BalanceEntry]] = []
        seen: set[Tuple[int, Tuple[Tuple[str, str], ...]]] = set()
        limited_entries = list(entries)[:120]

        def _consider(combo: Sequence[BalanceEntry]) -> None:
            total = sum(entry.value for entry in combo)
            if not self._is_close(total, target, tolerance):
                return
            key = (len(combo), tuple(sorted((e.account, e.column) for e in combo)))
            if key in seen:
                return
            seen.add(key)
            matches.append(list(combo))

        for entry in limited_entries:
            _consider([entry])

        for i in range(len(limited_entries)):
            for j in range(i + 1, len(limited_entries)):
                _consider([limited_entries[i], limited_entries[j]])

        triple_entries = limited_entries[:40]
        for i in range(len(triple_entries)):
            for j in range(i + 1, len(triple_entries)):
                for k in range(j + 1, len(triple_entries)):
                    _consider(
                        [triple_entries[i], triple_entries[j], triple_entries[k]]
                    )

        return matches[:5]

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

    def _format_match_suggestions(
        self, label: str, diff: float, matches: Sequence[Sequence[BalanceEntry]]
    ) -> List[str]:
        diff_text = format_currency(diff)
        entries: List[str] = []
        for combo in matches:
            intro = "Konto" if len(combo) == 1 else "Kombinasjon"
            accounts_text = "; ".join(
                self._format_entry_text(entry) for entry in combo
            )
            entries.append(f"{intro}: {accounts_text}")

        if not entries:
            return []

        detail_items = "".join(f"<li>{text}</li>" for text in entries)
        return [
            (
                f"<strong>{label}</strong> (avvik {diff_text}):"
                f"<ul>{detail_items}</ul>"
            )
        ]

    def _format_entry_text(self, entry: BalanceEntry) -> str:
        column_label = "UB" if "UB" in entry.column.upper() else "IB"
        account_label = entry.account or "ukjent konto"
        name_label = f" ({entry.name})" if entry.name else ""
        value_text = format_currency(entry.value)
        return f"{account_label}{name_label} – {value_text} i {column_label.lower()}"

    @staticmethod
    def _first_existing_column(
        df: pd.DataFrame, candidates: Sequence[str]
    ) -> Optional[str]:
        for column in candidates:
            if column in df.columns:
                return column
        return None

    @staticmethod
    def _is_close(value: float, target: float, tolerance: float) -> bool:
        return (
            abs(value - target) <= tolerance
            or abs(abs(value) - abs(target)) <= tolerance
        )


__all__ = ["PageStateHandler", "ComparisonRow", "ComparisonRows", "BalanceEntry"]
