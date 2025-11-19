from typing import Dict, List, Optional

import pandas as pd
import pytest

from nordlys.saft.header import SaftHeader
from nordlys.saft.loader import SaftLoadResult
from nordlys.saft.validation import SaftValidationResult
from nordlys.ui.data_manager.dataset_store import SaftDatasetStore


def _make_result(
    file_path: str,
    *,
    analysis_year: int | None,
    fiscal_year: str | None,
    summary: Optional[Dict[str, float]] = None,
) -> SaftLoadResult:
    header = SaftHeader(
        company_name="Test AS",
        orgnr="123456789",
        fiscal_year=fiscal_year,
        period_start="2023-01-01",
        period_end="2023-12-31",
        file_version="1.30",
    )
    return SaftLoadResult(
        file_path=file_path,
        header=header,
        dataframe=pd.DataFrame({"Konto": []}),
        customers={},
        customer_sales=None,
        suppliers={},
        supplier_purchases=None,
        cost_vouchers=[],
        analysis_year=analysis_year,
        summary=summary or {},
        validation=SaftValidationResult(
            audit_file_version=None,
            version_family=None,
            schema_version=None,
            is_valid=None,
        ),
    )


def test_customer_sales_total_and_balance_diff() -> None:
    store = SaftDatasetStore()
    store._customer_sales = pd.DataFrame(  # type: ignore[attr-defined]
        {
            "Kundenr": ["1", "2"],
            "Omsetning eks mva": [100.0, 250.5],
        }
    )
    store._saft_summary = {"driftsinntekter": 350.5}  # type: ignore[attr-defined]

    assert store.customer_sales_total == pytest.approx(350.5)
    assert store.sales_account_total == pytest.approx(350.5)
    assert store.customer_sales_balance_diff == pytest.approx(0.0)


def test_customer_sales_balance_requires_both_sources() -> None:
    store = SaftDatasetStore()
    store._customer_sales = pd.DataFrame(  # type: ignore[attr-defined]
        {
            "Kundenr": ["1"],
            "Omsetning eks mva": [100.0],
        }
    )

    assert store.customer_sales_total == pytest.approx(100.0)
    assert store.sales_account_total is None
    assert store.customer_sales_balance_diff is None

    store._saft_summary = {"driftsinntekter": 80.0}  # type: ignore[attr-defined]
    assert store.sales_account_total == pytest.approx(80.0)
    assert store.customer_sales_balance_diff == pytest.approx(20.0)

    store._customer_sales = pd.DataFrame({"Kundenr": ["1"]})  # type: ignore[attr-defined]
    assert store.customer_sales_total is None


def test_current_year_text_prefers_analysis_year() -> None:
    store = SaftDatasetStore()
    result = _make_result(
        "fil1.xml",
        analysis_year=2022,
        fiscal_year="2020",
    )
    store.apply_batch([result])
    assert store.activate("fil1.xml")
    assert store.current_year == 2022
    assert store.current_year_text == "2022"


def test_current_year_text_falls_back_to_header_value() -> None:
    store = SaftDatasetStore()
    result = _make_result(
        "fil2.xml",
        analysis_year=None,
        fiscal_year="2021",
    )
    store.apply_batch([result])
    assert store.activate("fil2.xml")
    assert store.current_year == 2021
    assert store.current_year_text == "2021"


def test_current_year_text_none_when_no_year_available() -> None:
    store = SaftDatasetStore()
    result = _make_result(
        "fil3.xml",
        analysis_year=None,
        fiscal_year=None,
    )
    store.apply_batch([result])
    assert store.activate("fil3.xml")
    assert store.current_year is None
    assert store.current_year_text is None


def test_recent_summaries_limits_and_marks_current() -> None:
    store = SaftDatasetStore()
    results: List[SaftLoadResult] = []
    for idx in range(6):
        summary = {
            "driftsinntekter": float(100 * (idx + 1)),
            "arsresultat": float(10 * (idx + 1)),
        }
        result = _make_result(
            f"fil{idx}.xml",
            analysis_year=2020 + idx,
            fiscal_year=str(2020 + idx),
            summary=summary,
        )
        results.append(result)

    store.apply_batch(results)
    assert store.activate("fil5.xml")

    snapshots = store.recent_summaries(limit=5)
    assert len(snapshots) == 5
    assert snapshots[-1].is_current
    assert snapshots[-1].label == store.dataset_label(results[-1])

    # Eldste verdier skal fjernes når limit er mindre enn totalt antall
    assert snapshots[0].label == store.dataset_label(results[1])
    margins = [snap.summary.get("arsresultat") for snap in snapshots]
    assert margins[0] == pytest.approx(20.0)


def test_prepare_dataframe_with_previous_fills_missing_history() -> None:
    store = SaftDatasetStore()
    current = pd.DataFrame(
        {
            "Konto": ["1000", "2000"],
            "UB_netto": [100.0, 200.0],
        }
    )
    previous = pd.DataFrame({"Konto": ["1000"], "UB_netto": [50.0]})

    combined = store._prepare_dataframe_with_previous(current, previous)
    history = list(combined["forrige"].values)

    assert history[0] == pytest.approx(50.0)
    assert history[1] == pytest.approx(0.0)
