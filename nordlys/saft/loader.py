"""Funksjoner for lasting av SAF-T-data uten GUI-avhengigheter."""

from __future__ import annotations

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence

from ..helpers.lazy_imports import lazy_import, lazy_pandas
from ..industry_groups import IndustryClassification
from ..settings import SAFT_STREAMING_ENABLED
from .brreg_enrichment import BrregEnrichment, enrich_from_header
from .customer_analysis import (
    CustomerSupplierAnalysis,
    build_customer_supplier_analysis,
)
from .trial_balance import compute_trial_balance

_LOGGER = logging.getLogger(__name__)

HEAVY_SAFT_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
HEAVY_SAFT_TOTAL_BYTES = 150 * 1024 * 1024  # 150 MB samlet
HEAVY_SAFT_MAX_WORKERS = 2
HEAVY_SAFT_STREAMING_BYTES = HEAVY_SAFT_FILE_BYTES

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


def load_saft_file(
    file_path: str,
    *,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    file_size: Optional[int] = None,
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

    validation: Optional["saft.SaftValidationResult"] = None
    enrichment: Optional[BrregEnrichment] = None

    background_workers = max(3, min(6, os.cpu_count() or 1))
    use_streaming = _should_stream_trial_balance(file_path, file_size=file_size)

    with ThreadPoolExecutor(max_workers=background_workers) as executor:
        trial_balance_future = None
        if use_streaming:
            _report_progress(5, f"Leser hovedbok (streaming) for {file_name}")
            trial_balance_future = executor.submit(
                compute_trial_balance, file_path, streaming_enabled=True
            )

        tree, ns = saft_customers.parse_saft(file_path)
        root = tree.getroot()
        if root is None:  # pragma: no cover - guard mot korrupt XML
            raise ValueError("SAF-T-filen mangler et rot-element.")
        header = saft.parse_saft_header(root)

        validation_future = executor.submit(
            saft.validate_saft_against_xsd,
            tree,
            header.file_version if header else None,
        )
        enrichment_future = executor.submit(enrich_from_header, header)

        dataframe_future = executor.submit(saft.parse_saldobalanse, root)
        customers_future = executor.submit(saft.parse_customers, root)
        suppliers_future = executor.submit(saft.parse_suppliers, root)
        analysis_future = executor.submit(
            build_customer_supplier_analysis, header, root, ns
        )

        dataframe = dataframe_future.result()
        customers = customers_future.result()
        suppliers = suppliers_future.result()
        _report_progress(25, f"Tolker saldobalanse for {file_name}")

        analysis: CustomerSupplierAnalysis = analysis_future.result()
        analysis_year = analysis.analysis_year
        customer_sales = analysis.customer_sales
        supplier_purchases = analysis.supplier_purchases
        cost_vouchers = analysis.cost_vouchers

        _report_progress(50, f"Analyserer kunder og leverandører for {file_name}")

        summary = saft.ns4102_summary_from_tb(dataframe)

        _report_progress(75, f"Validerer og beriker data for {file_name}")

        validation = validation_future.result()
        enrichment = enrichment_future.result()
        trial_balance_result = (
            trial_balance_future.result() if trial_balance_future is not None else None
        )

        if trial_balance_result is not None:
            trial_balance = trial_balance_result.balance
            trial_balance_error = trial_balance_result.error

    if validation is None:
        raise RuntimeError("Validering av SAF-T kunne ikke fullføres.")

    if enrichment is None:
        raise RuntimeError("Beriking fra Brønnøysundregistrene manglet resultat.")

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
        brreg_json=enrichment.brreg_json,
        brreg_map=enrichment.brreg_map,
        brreg_error=enrichment.brreg_error,
        industry=enrichment.industry,
        industry_error=enrichment.industry_error,
    )


def load_saft_files(
    file_paths: Sequence[str] | str,
    *,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> List[SaftLoadResult]:
    """
    Laster en eller flere SAF-T-filer med fremdriftsrapportering.

    Funksjonen kan ta imot én eller flere filbaner og spinner opp en trådpool
    med opptil én arbeider per CPU-kjerne. `_suggest_max_workers` senker
    samtidig antallet til `HEAVY_SAFT_MAX_WORKERS` når filene er store for å
    unngå minnepress.
    """

    if isinstance(file_paths, (str, os.PathLike)):
        paths = [str(file_paths)]
    else:
        paths = list(file_paths)
    file_sizes = [_file_size_bytes(path) for path in paths]
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

    failed_files: List[str] = []
    first_exception: Optional[BaseException] = None

    if progress_callback is not None:
        progress_lock = Lock()
        progress_values: List[float] = [0.0] * total
        weights: List[float] = []
        for size in file_sizes:
            if size is None or size <= 0:
                weights.append(1.0)
            else:
                weights.append(float(size))
        total_weight = sum(weights) if weights else float(total)
        if total_weight == 0:
            total_weight = float(total)
        last_messages: List[str] = [f"Laster {Path(path).name} …" for path in paths]
        overall_progress = 0

        def _progress_factory(index: int) -> Callable[[int, str], None]:
            def _inner(percent: int, message: str) -> None:
                nonlocal overall_progress
                normalized = max(0.0, min(100.0, float(percent)))
                clean_message = message.strip()
                with progress_lock:
                    progress_values[index] = normalized
                    if clean_message:
                        last_messages[index] = clean_message
                    weighted_sum = sum(
                        value * weight
                        for value, weight in zip(progress_values, weights)
                    )
                    overall = int(round(weighted_sum / total_weight))
                    if overall < overall_progress:
                        overall = overall_progress
                    else:
                        overall_progress = overall
                    active_message = clean_message or last_messages[index]
                progress_callback(overall, active_message)

            return _inner

    else:

        def _progress_factory(index: int) -> Callable[[int, str], None]:
            def _inner(percent: int, message: str) -> None:
                return None

            return _inner

    max_workers = _suggest_max_workers(paths, file_sizes=file_sizes)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        submission_order = sorted(range(total), key=lambda idx: -(file_sizes[idx] or 0))
        for index in submission_order:
            path = paths[index]
            progress_arg = _progress_factory(index)
            if progress_callback is not None:
                future = executor.submit(
                    load_saft_file,
                    path,
                    progress_callback=progress_arg,
                    file_size=file_sizes[index],
                )
            else:
                future = executor.submit(
                    load_saft_file, path, file_size=file_sizes[index]
                )
            futures[future] = index

        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - vi vil logge og fortsette
                file_label = Path(paths[index]).name
                _LOGGER.exception("Feil ved import av %s", file_label)
                failed_files.append(file_label)
                if first_exception is None:
                    first_exception = exc
                if progress_callback is not None:
                    error_message = f"Feil ved import av {file_label}: {exc}"
                    with progress_lock:
                        progress_values[index] = 100.0
                        last_messages[index] = error_message
                        weighted_sum = sum(
                            value * weight
                            for value, weight in zip(progress_values, weights)
                        )
                        overall = int(round(weighted_sum / total_weight))
                        if overall < overall_progress:
                            overall = overall_progress
                        else:
                            overall_progress = overall
                    progress_callback(overall, error_message)

    if progress_callback is not None:
        if failed_files:
            failed_summary = ", ".join(sorted(failed_files))
            final_message = f"Import fullført med feil i: {failed_summary}."
        else:
            final_message = "Import fullført."
        progress_callback(100, final_message)

    successful_results = [result for result in results if result is not None]

    if first_exception is not None:
        if progress_callback is None or not successful_results:
            raise first_exception

    return successful_results


def _suggest_max_workers(
    paths: Sequence[str],
    *,
    cpu_limit: Optional[int] = None,
    file_sizes: Optional[Sequence[Optional[int]]] = None,
) -> int:
    """Velger et trådantall som unngår minnepress ved store filer."""

    if not paths:
        return 1

    cpu_count = cpu_limit if cpu_limit is not None else (os.cpu_count() or 1)
    desired = max(1, min(len(paths), cpu_count))
    if desired == 1:
        return 1

    heavy_files = 0
    total_bytes = 0
    for idx, path in enumerate(paths):
        size = None
        if file_sizes is not None and idx < len(file_sizes):
            size = file_sizes[idx]
        if size is None:
            size = _file_size_bytes(path)
        if size is None:
            continue
        total_bytes += size
        if size >= HEAVY_SAFT_FILE_BYTES:
            heavy_files += 1

    heavy_by_count = heavy_files >= 2
    heavy_by_total = total_bytes >= HEAVY_SAFT_TOTAL_BYTES

    if heavy_by_count or heavy_by_total:
        return min(desired, HEAVY_SAFT_MAX_WORKERS)

    return desired


def _should_stream_trial_balance(
    file_path: str | os.PathLike[str], *, file_size: Optional[int] = None
) -> bool:
    """Velger streaming for prøvebalansen når det er forventet gevinster.

    Streaming tvinges på for store filer, selv om miljøvariabelen ikke er satt,
    for å unngå at importen blir begrenset av minne- og I/O-flaskehalser.
    """

    if SAFT_STREAMING_ENABLED:
        return True

    size = file_size if file_size is not None else _file_size_bytes(file_path)
    if size is None:
        return False

    return size >= HEAVY_SAFT_STREAMING_BYTES


def _file_size_bytes(path: str | os.PathLike[str]) -> Optional[int]:
    """Returnerer filstørrelse i bytes, eller ``None`` ved feil."""

    try:
        return Path(path).stat().st_size
    except OSError:
        return None
