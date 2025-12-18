from typing import Dict, List, Optional

import pandas as pd
import pytest

from nordlys.saft.header import SaftHeader
from nordlys.saft.loader import SaftLoadResult
from nordlys.saft.masterfiles import SupplierInfo
from nordlys.saft.reporting_customers import (
    ReceivablePostingAnalysis,
    SalesReceivableCorrelation,
)
from nordlys.saft.validation import SaftValidationResult
from nordlys.ui.data_manager.dataset_store import SaftDatasetStore


def _make_result(
    file_path: str,
    *,
    analysis_year: int | None,
    fiscal_year: str | None,
    orgnr: str = "123456789",
    summary: Optional[Dict[str, float]] = None,
) -> SaftLoadResult:
    header = SaftHeader(
        company_name="Test AS",
        orgnr=orgnr,
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
        credit_notes=None,
        sales_ar_correlation=None,
        receivable_analysis=None,
        bank_analysis=None,
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


def test_prepare_customer_sales_fills_missing_names() -> None:
    store = SaftDatasetStore()
    store._cust_name_by_nr = {"1": "Kari Kunde"}  # type: ignore[attr-defined]

    df = pd.DataFrame(
        {"Kundenr": ["1"], "Kundenavn": [float("nan")], "Omsetning eks mva": [10.0]}
    )

    prepared = store._prepare_customer_sales(df)  # type: ignore[attr-defined]

    assert prepared is not None
    assert prepared.loc[0, "Kundenavn"] == "Kari Kunde"


def test_dataset_label_includes_company_name_first() -> None:
    store = SaftDatasetStore()
    result = _make_result(
        "fil1.xml",
        analysis_year=2024,
        fiscal_year="2024",
    )

    store.apply_batch([result])

    assert store.dataset_label(result) == "Test AS - 2024"


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


def test_apply_batch_adds_years_for_same_company() -> None:
    store = SaftDatasetStore()
    previous = _make_result(
        "2023.xml",
        analysis_year=2023,
        fiscal_year="2023",
    )
    latest = _make_result(
        "2024.xml",
        analysis_year=2024,
        fiscal_year="2024",
    )

    store.apply_batch([previous])
    store.apply_batch([latest])

    assert store.dataset_order == ["2023.xml", "2024.xml"]
    assert store.activate("2023.xml")
    assert store.activate("2024.xml")


def test_apply_batch_resets_on_new_company() -> None:
    store = SaftDatasetStore()
    company_one = _make_result(
        "2023.xml",
        analysis_year=2023,
        fiscal_year="2023",
        orgnr="123456789",
    )
    company_two = _make_result(
        "2024.xml",
        analysis_year=2024,
        fiscal_year="2024",
        orgnr="987654321",
    )

    store.apply_batch([company_one])
    store.apply_batch([company_two])

    assert store.dataset_order == ["2024.xml"]
    assert not store.activate("2023.xml")


def test_credit_note_monthly_summary_sorts_by_month() -> None:
    store = SaftDatasetStore()
    store._credit_notes = pd.DataFrame(  # type: ignore[attr-defined]
        {
            "Dato": [
                pd.Timestamp(year=2023, month=12, day=1),
                pd.Timestamp(year=2023, month=1, day=15),
                pd.Timestamp(year=2023, month=3, day=10),
            ],
            "Beløp": [300.0, 100.0, 200.0],
        }
    )

    summary = store.credit_note_monthly_summary()

    assert summary == [
        ("Januar", 1, 100.0),
        ("Mars", 1, 200.0),
        ("Desember", 1, 300.0),
    ]


def test_sales_without_receivable_rows_include_motkonto_and_bilagsnr() -> None:
    store = SaftDatasetStore()
    store._sales_ar_correlation = SalesReceivableCorrelation(  # type: ignore[attr-defined]
        with_receivable_total=0.0,
        without_receivable_total=0.0,
        missing_sales=pd.DataFrame(
            {
                "Dato": [pd.Timestamp(year=2023, month=1, day=1)],
                "Bilagsnr": ["42"],
                "Beskrivelse": ["Test"],
                "Kontoer": ["3100"],
                "Motkontoer": ["1920"],
                "Beløp": [100.0],
            }
        ),
    )

    rows = store.sales_without_receivable_rows()

    assert rows == [("01.01.2023", "42", "Test", "3100", "1920", 100.0)]


def test_receivable_sales_counter_total_exposes_sales_sum() -> None:
    store = SaftDatasetStore()
    store._receivable_analysis = ReceivablePostingAnalysis(  # type: ignore[attr-defined]
        opening_balance=None,
        sales_counter_total=1234.56,
        bank_counter_total=0.0,
        other_counter_total=0.0,
        closing_balance=None,
        unclassified_rows=pd.DataFrame(),
    )

    assert store.receivable_sales_counter_total == pytest.approx(1234.56)


def test_apply_batch_blocks_multiple_companies_in_same_batch() -> None:
    store = SaftDatasetStore()
    first = _make_result(
        "2023.xml",
        analysis_year=2023,
        fiscal_year="2023",
        orgnr="123456789",
    )
    other = _make_result(
        "2024.xml",
        analysis_year=2024,
        fiscal_year="2024",
        orgnr="987654321",
    )

    with pytest.raises(ValueError):
        store.apply_batch([first, other])


def test_prepare_supplier_purchases_fills_missing_names_from_number_lookup() -> None:
    store = SaftDatasetStore()
    store._sup_name_by_nr = {"77": "Leverandør AS"}  # type: ignore[attr-defined]

    df = pd.DataFrame(
        {
            "Leverandørnr": ["77"],
            "Leverandørnavn": [float("nan")],
            "Innkjøp eks mva": [20.0],
        }
    )

    prepared = store._prepare_supplier_purchases(df)  # type: ignore[attr-defined]

    assert prepared is not None
    assert prepared.loc[0, "Leverandørnavn"] == "Leverandør AS"


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


def test_activate_merges_previous_year_revenue() -> None:
    store = SaftDatasetStore()
    previous = _make_result(
        "2023.xml",
        analysis_year=2023,
        fiscal_year="2023",
        summary={"driftsinntekter": 500.0, "sum_inntekter": 500.0},
    )
    current = _make_result(
        "2024.xml",
        analysis_year=2024,
        fiscal_year="2024",
        summary={"driftsinntekter": 600.0},
    )

    store.apply_batch([previous, current])

    assert store.activate("2024.xml")
    summary = store.saft_summary
    assert summary is not None
    assert summary["driftsinntekter"] == pytest.approx(600.0)
    assert summary["driftsinntekter_fjor"] == pytest.approx(500.0)
    assert summary["sum_inntekter_fjor"] == pytest.approx(500.0)


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


def test_prepare_supplier_purchases_fills_missing_names_from_supplier_ids() -> None:
    store = SaftDatasetStore()
    supplier = SupplierInfo(
        supplier_id="SUP-1",
        supplier_number="100",
        name="Brus AS",
    )
    store._ingest_suppliers({supplier.supplier_id: supplier})

    purchases = pd.DataFrame(
        {
            "Leverandørnr": ["100", "SUP-1"],
            "Leverandørnavn": ["", ""],
            "Innkjøp eks mva": [200.0, 150.0],
        }
    )

    prepared = store._prepare_supplier_purchases(purchases)

    assert list(prepared["Leverandørnavn"]) == ["Brus AS", "Brus AS"]
