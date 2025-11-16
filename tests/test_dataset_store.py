import pandas as pd
import pytest

from nordlys.ui.data_manager.dataset_store import SaftDatasetStore


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
