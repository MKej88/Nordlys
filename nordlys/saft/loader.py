"""Funksjoner for lasting av SAF-T-data uten GUI-avhengigheter."""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence
from xml.etree.ElementTree import Element, ElementTree

from ..helpers.lazy_imports import lazy_import, lazy_pandas
from ..industry_groups import IndustryClassification
from ..settings import SAFT_STREAMING_ENABLED
from .entry_helpers import get_amount
from .brreg_enrichment import BrregEnrichment, enrich_from_header
from .customer_analysis import (
    CustomerSupplierAnalysis,
    build_customer_supplier_analysis,
)
from .trial_balance import TrialBalanceResult
from .xml_helpers import NamespaceMap, _findall

_LOGGER = logging.getLogger(__name__)

HEAVY_SAFT_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
HEAVY_SAFT_TOTAL_BYTES = 150 * 1024 * 1024  # 150 MB samlet
HEAVY_SAFT_MAX_WORKERS = 2
HEAVY_SAFT_STREAMING_BYTES = HEAVY_SAFT_FILE_BYTES

if TYPE_CHECKING:
    import pandas as pd

    from .. import saft
    from .. import saft_customers
    from .trial_balance import TrialBalanceResult
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
    credit_notes: Optional[pd.DataFrame]
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


@dataclass
class _ParsedSaftContent:
    """Holder på parsingresultater for en SAF-T-fil."""

    tree: ElementTree
    root: Element
    header: Optional["saft.SaftHeader"]
    namespaces: NamespaceMap


@dataclass
class _SaftFutures:
    """Samler futures slik at de er lette å håndtere samlet."""

    validation: Future["saft.SaftValidationResult"]
    enrichment: Future[BrregEnrichment]
    dataframe: Future["pd.DataFrame"]
    customers: Future[Dict[str, "saft.CustomerInfo"]]
    suppliers: Future[Dict[str, "saft.SupplierInfo"]]
    analysis: Future[CustomerSupplierAnalysis]
    trial_balance: Optional[Future["TrialBalanceResult"]]


def _parse_saft_content(file_path: str) -> _ParsedSaftContent:
    """Parser SAF-T-filen og returnerer nødvendige elementer."""

    tree, ns = saft_customers.parse_saft(file_path)
    root = tree.getroot()
    if root is None:  # pragma: no cover - guard mot korrupt XML
        raise ValueError("SAF-T-filen mangler et rot-element.")
    header = saft.parse_saft_header(root)
    return _ParsedSaftContent(tree=tree, root=root, header=header, namespaces=ns)


def _submit_background_tasks(
    executor: ThreadPoolExecutor,
    *,
    file_path: str,
    file_name: str,
    use_streaming: bool,
    parsed: _ParsedSaftContent,
    report_progress: Callable[[int, str], None],
) -> _SaftFutures:
    """Starter de mest tunge oppgavene i bakgrunnen."""

    trial_balance_future: Optional[Future["TrialBalanceResult"]] = None
    if use_streaming:
        report_progress(5, f"Beregner prøvebalanse for {file_name}")
        trial_balance_future = executor.submit(
            _compute_trial_balance_from_root, parsed, file_path
        )

    validation_future = executor.submit(
        saft.validate_saft_against_xsd,
        parsed.tree,
        parsed.header.file_version if parsed.header else None,
    )
    enrichment_future = executor.submit(enrich_from_header, parsed.header)
    dataframe_future = executor.submit(saft.parse_saldobalanse, parsed.root)
    customers_future = executor.submit(saft.parse_customers, parsed.root)
    suppliers_future = executor.submit(saft.parse_suppliers, parsed.root)
    analysis_future = executor.submit(
        build_customer_supplier_analysis,
        parsed.header,
        parsed.root,
        parsed.namespaces,
    )

    return _SaftFutures(
        validation=validation_future,
        enrichment=enrichment_future,
        dataframe=dataframe_future,
        customers=customers_future,
        suppliers=suppliers_future,
        analysis=analysis_future,
        trial_balance=trial_balance_future,
    )


def _collect_validation_and_enrichment(
    futures: _SaftFutures,
) -> tuple["saft.SaftValidationResult", BrregEnrichment]:
    """Henter resultater for validering og beriking."""

    return futures.validation.result(), futures.enrichment.result()


def _resolve_trial_balance(
    trial_balance_future: Optional[Future["TrialBalanceResult"]],
) -> tuple[Optional[Dict[str, Decimal]], Optional[str]]:
    """Pakker ut resultatet fra prøvebalanseberegningen."""

    if trial_balance_future is None:
        return None, None

    trial_balance_result = trial_balance_future.result()
    return trial_balance_result.balance, trial_balance_result.error


def _compute_trial_balance_from_root(
    parsed: _ParsedSaftContent, file_path: str
) -> TrialBalanceResult:
    """Summerer debet og kredit fra et allerede parset XML-tre.

    Denne varianten unngår en ny runde med fil-lesing når vi likevel har
    hele ``ElementTree`` i minnet, noe som reduserer total importtid for
    større filer.
    """

    total_debet = Decimal("0")
    total_kredit = Decimal("0")
    journals_path = "n1:SourceDocuments/n1:GeneralLedgerEntries/n1:Journals/n1:Journal"

    try:
        for journal in _findall(parsed.root, journals_path, parsed.namespaces):
            for transaction in _findall(journal, "n1:Transaction", parsed.namespaces):
                for line in _findall(transaction, "n1:Line", parsed.namespaces):
                    total_debet += get_amount(line, "DebitAmount", parsed.namespaces)
                    total_kredit += get_amount(line, "CreditAmount", parsed.namespaces)
    except Exception as exc:  # pragma: no cover - robusthet mot defekte data
        return TrialBalanceResult(
            balance=None,
            error=(
                "Kunne ikke beregne prøvebalanse for {file}: {exc}".format(
                    file=Path(file_path).name, exc=exc
                )
            ),
        )

    diff = total_debet - total_kredit
    error: Optional[str] = None
    if diff != Decimal("0"):
        error = "Prøvebalansen går ikke opp (diff {diff}) for {file}.".format(
            diff=diff, file=Path(file_path).name
        )

    return TrialBalanceResult(
        balance={"debet": total_debet, "kredit": total_kredit, "diff": diff},
        error=error,
    )


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

    header: Optional["saft.SaftHeader"] = None
    validation: Optional["saft.SaftValidationResult"] = None
    enrichment: Optional[BrregEnrichment] = None

    background_workers = max(3, min(6, os.cpu_count() or 1))
    use_streaming = _should_stream_trial_balance(file_path, file_size=file_size)

    with ThreadPoolExecutor(max_workers=background_workers) as executor:
        parsed = _parse_saft_content(file_path)
        header = parsed.header
        futures = _submit_background_tasks(
            executor,
            file_path=file_path,
            file_name=file_name,
            use_streaming=use_streaming,
            parsed=parsed,
            report_progress=_report_progress,
        )

        dataframe = futures.dataframe.result()
        customers = futures.customers.result()
        suppliers = futures.suppliers.result()
        _report_progress(25, f"Tolker saldobalanse for {file_name}")

        analysis: CustomerSupplierAnalysis = futures.analysis.result()
        analysis_year = analysis.analysis_year
        customer_sales = analysis.customer_sales
        supplier_purchases = analysis.supplier_purchases
        cost_vouchers = analysis.cost_vouchers
        credit_notes = analysis.credit_notes

        _report_progress(50, f"Analyserer kunder og leverandører for {file_name}")

        summary = saft.ns4102_summary_from_tb(dataframe)

        _report_progress(75, f"Validerer og beriker data for {file_name}")

        validation, enrichment = _collect_validation_and_enrichment(futures)
        trial_balance, trial_balance_error = _resolve_trial_balance(
            futures.trial_balance
        )

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
        credit_notes=credit_notes,
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
