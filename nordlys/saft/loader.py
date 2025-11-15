"""Funksjoner for lasting av SAF-T-data uten GUI-avhengigheter."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence
import xml.etree.ElementTree as ET

from ..brreg import fetch_brreg, map_brreg_metrics
from ..industry_groups import (
    IndustryClassification,
    classify_from_brreg_json,
    classify_from_orgnr,
    load_cached_brreg,
)
from ..helpers.lazy_imports import lazy_import, lazy_pandas
from ..settings import SAFT_STREAMING_ENABLED, SAFT_STREAMING_VALIDATE

if TYPE_CHECKING:
    import pandas as pd

    from .. import saft
    from .. import saft_customers
else:
    pd = lazy_pandas()
    saft = lazy_import("nordlys.saft")
    saft_customers = lazy_import("nordlys.saft_customers")


@dataclass
class SaftLoadResult:
    """Resultatobjekt fra bakgrunnslasting av SAF-T."""

    file_path: str
    header: Optional["saft.SaftHeader"]
    dataframe: pd.DataFrame
    customers: Dict[str, "saft.CustomerInfo"]
    customer_sales: Optional[pd.DataFrame]
    suppliers: Dict[str, "saft.SupplierInfo"]
    supplier_purchases: Optional[pd.DataFrame]
    cost_vouchers: List["saft_customers.CostVoucher"]
    analysis_year: Optional[int]
    summary: Optional[Dict[str, float]]
    validation: "saft.SaftValidationResult"
    trial_balance: Optional[Dict[str, Decimal]] = None
    trial_balance_error: Optional[str] = None
    brreg_json: Optional[Dict[str, object]] = None
    brreg_map: Optional[Dict[str, Optional[float]]] = None
    brreg_error: Optional[str] = None
    industry: Optional[IndustryClassification] = None
    industry_error: Optional[str] = None


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None


def load_saft_file(
    file_path: str,
    *,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> SaftLoadResult:
    """Laster en enkelt SAF-T-fil og returnerer resultatet."""

    file_name = Path(file_path).name

    def _report_progress(percent: int, message: str) -> None:
        if progress_callback is None:
            return
        clamped = max(0, min(100, int(percent)))
        progress_callback(clamped, message)

    _report_progress(0, f"Forbereder {file_name}")

    trial_balance: Optional[Dict[str, Decimal]] = None
    trial_balance_error: Optional[str] = None
    if SAFT_STREAMING_ENABLED:
        _report_progress(5, f"Leser hovedbok (streaming) for {file_name}")
        try:
            trial_balance = saft.check_trial_balance(
                Path(file_path), validate=SAFT_STREAMING_VALIDATE
            )
            if trial_balance["diff"] != Decimal("0"):
                trial_balance_error = (
                    "Prøvebalansen går ikke opp (diff "
                    f"{trial_balance['diff']}) for {file_name}."
                )
        except Exception as exc:  # pragma: no cover - robust mot eksterne feil
            trial_balance = None
            trial_balance_error = str(exc)

    tree, ns = saft_customers.parse_saft(file_path)
    root = tree.getroot()
    if root is None:  # pragma: no cover - guard mot korrupt XML
        raise ValueError("SAF-T-filen mangler et rot-element.")
    ns_et: dict[str, str] = {
        key: value
        for key, value in ns.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    header = saft.parse_saft_header(root)
    dataframe = saft.parse_saldobalanse(root)
    _report_progress(25, f"Tolker saldobalanse for {file_name}")
    customers = saft.parse_customers(root)
    suppliers = saft.parse_suppliers(root)

    period_start = _parse_date(header.period_start) if header else None
    period_end = _parse_date(header.period_end) if header else None
    analysis_year: Optional[int] = None
    customer_sales: Optional[pd.DataFrame] = None
    supplier_purchases: Optional[pd.DataFrame] = None
    cost_vouchers: List["saft_customers.CostVoucher"] = []
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None
    if period_start or period_end:
        parent_map = saft_customers.build_parent_map(root)
        (
            customer_sales,
            supplier_purchases,
        ) = saft_customers.compute_customer_supplier_totals(
            root,
            ns,
            date_from=period_start,
            date_to=period_end,
            parent_map=parent_map,
        )
        cost_vouchers = saft_customers.extract_cost_vouchers(
            root,
            ns,
            date_from=period_start,
            date_to=period_end,
            parent_map=parent_map,
        )
        if period_end:
            analysis_year = period_end.year
        elif period_start:
            analysis_year = period_start.year
    else:
        if header and header.fiscal_year:
            try:
                analysis_year = int(header.fiscal_year)
            except (TypeError, ValueError):
                analysis_year = None
        if analysis_year is None and header and header.period_end:
            parsed_end = _parse_date(header.period_end)
            if parsed_end:
                analysis_year = parsed_end.year
        if analysis_year is None:
            for tx in root.findall(
                ".//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction",
                ns_et or None,
            ):
                date_element = tx.find("n1:TransactionDate", ns_et or None)
                if date_element is not None and date_element.text:
                    parsed = _parse_date(date_element.text)
                    if parsed:
                        analysis_year = parsed.year
                        break
        if analysis_year is not None:
            if parent_map is None:
                parent_map = saft_customers.build_parent_map(root)
            (
                customer_sales,
                supplier_purchases,
            ) = saft_customers.compute_customer_supplier_totals(
                root,
                ns,
                year=analysis_year,
                parent_map=parent_map,
            )
            cost_vouchers = saft_customers.extract_cost_vouchers(
                root,
                ns,
                year=analysis_year,
                parent_map=parent_map,
            )

    _report_progress(50, f"Analyserer kunder og leverandører for {file_name}")

    summary = saft.ns4102_summary_from_tb(dataframe)
    validation = saft.validate_saft_against_xsd(
        file_path,
        header.file_version if header else None,
    )

    _report_progress(75, f"Validerer og beriker data for {file_name}")

    brreg_json: Optional[Dict[str, object]] = None
    brreg_map: Optional[Dict[str, Optional[float]]] = None
    brreg_error: Optional[str] = None
    industry: Optional[IndustryClassification] = None
    industry_error: Optional[str] = None
    if header and header.orgnr:
        with ThreadPoolExecutor(max_workers=2) as executor:
            brreg_future = executor.submit(fetch_brreg, header.orgnr)
            industry_future = executor.submit(
                classify_from_orgnr,
                header.orgnr,
                header.company_name,
            )

            try:
                fetched_json, fetch_error = brreg_future.result()
                if fetch_error:
                    brreg_error = fetch_error
                else:
                    brreg_json = fetched_json
                    if brreg_json is not None:
                        brreg_map = map_brreg_metrics(brreg_json)
                    else:
                        brreg_error = "Fikk ikke noe data fra Brønnøysundregistrene."
            except Exception as exc:  # pragma: no cover - nettverksfeil vises i GUI
                brreg_error = str(exc)

            try:
                industry = industry_future.result()
            except Exception as exc:  # pragma: no cover - nettverksfeil vises i GUI
                industry_error = str(exc)
                cached: Optional[Dict[str, object]]
                try:
                    cached = load_cached_brreg(header.orgnr)
                except Exception:
                    cached = None
                if cached:
                    try:
                        industry = classify_from_brreg_json(
                            header.orgnr,
                            header.company_name,
                            cached,
                        )
                        industry_error = None
                    except Exception as cache_exc:  # pragma: no cover - sjelden
                        industry_error = str(cache_exc)
    elif header:
        industry_error = "SAF-T mangler organisasjonsnummer."

    _report_progress(100, f"Ferdig med {file_name}")

    return SaftLoadResult(
        file_path=file_path,
        header=header,
        dataframe=dataframe,
        customers=customers,
        customer_sales=customer_sales,
        suppliers=suppliers,
        supplier_purchases=supplier_purchases,
        cost_vouchers=cost_vouchers,
        analysis_year=analysis_year,
        summary=summary,
        trial_balance=trial_balance,
        trial_balance_error=trial_balance_error,
        validation=validation,
        brreg_json=brreg_json,
        brreg_map=brreg_map,
        brreg_error=brreg_error,
        industry=industry,
        industry_error=industry_error,
    )


def load_saft_files(
    file_paths: Sequence[str],
    *,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> List[SaftLoadResult]:
    """Laster en eller flere SAF-T-filer med fremdriftsrapportering."""

    paths = list(file_paths)
    total = len(paths)
    if total == 0:
        if progress_callback is not None:
            progress_callback(100, "Ingen filer å laste.")
        return []

    if total == 1:
        single = load_saft_file(paths[0], progress_callback=progress_callback)
        if progress_callback is not None:
            progress_callback(100, "Import fullført.")
        return [single]

    results: List[Optional[SaftLoadResult]] = [None] * total

    if progress_callback is not None:
        progress_lock = Lock()
        progress_values: List[int] = [0] * total
        last_messages: List[str] = [f"Laster {Path(path).name} …" for path in paths]

        def _progress_factory(index: int) -> Callable[[int, str], None]:
            def _inner(percent: int, message: str) -> None:
                normalized = max(0, min(100, int(percent)))
                clean_message = message.strip()
                with progress_lock:
                    progress_values[index] = normalized
                    if clean_message:
                        last_messages[index] = clean_message
                    overall = int(round(sum(progress_values) / total))
                    active_message = clean_message or last_messages[index]
                progress_callback(overall, active_message)

            return _inner

    else:

        def _progress_factory(index: int) -> Optional[Callable[[int, str], None]]:
            return None

    cpu_count = os.cpu_count() or 1
    max_workers = min(total, max(1, cpu_count))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for index, path in enumerate(paths):
            progress_arg = _progress_factory(index)
            kwargs = {}
            if progress_arg is not None:
                kwargs["progress_callback"] = progress_arg
            futures[executor.submit(load_saft_file, path, **kwargs)] = index

        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()

    if progress_callback is not None:
        progress_callback(100, "Import fullført.")

    return [result for result in results if result is not None]
