from datetime import date
from pathlib import Path

import pandas as pd

from nordlys.saft.models import CostVoucher
from nordlys.ui.data_manager import SaftDatasetStore
from nordlys.ui.excel_export import export_dataset_to_excel
from nordlys.ui.pdf_export import export_dataset_to_pdf


def _build_store() -> SaftDatasetStore:
    store = SaftDatasetStore()
    store._saft_df = pd.DataFrame({"Konto": ["3000"], "UB_netto": [1000.0]})
    store._saft_summary = {"driftsinntekter": 1000.0, "resultat": 500.0}
    store._customer_sales = pd.DataFrame(
        {
            "Kundenr": ["1"],
            "Kundenavn": ["Alpha"],
            "Omsetning eks mva": [250.0],
        }
    )
    store._supplier_purchases = pd.DataFrame(
        {
            "Leverandørnr": ["10"],
            "Leverandørnavn": ["Beta"],
            "Innkjøp eks mva": [300.0],
        }
    )
    store._cost_vouchers = [
        CostVoucher(
            transaction_id="t1",
            document_number="D1",
            transaction_date=date(2024, 1, 2),
            supplier_id="10",
            supplier_name="Beta",
            description="Testbilag",
            amount=123.0,
            lines=[],
        )
    ]
    return store


def test_excel_export_includes_new_sheets(tmp_path: Path) -> None:
    store = _build_store()
    out_file = tmp_path / "rapport.xlsx"
    export_dataset_to_excel(store, str(out_file))

    with pd.ExcelFile(out_file) as workbook:
        sheet_names = set(workbook.sheet_names)
        assert "Purchases_by_supplier" in sheet_names
        assert "Cost_vouchers" in sheet_names

        vouchers_df = workbook.parse("Cost_vouchers")
        assert not vouchers_df.empty
        assert set(vouchers_df.columns) >= {"Bilagsnr", "Beløp"}


def test_pdf_export_creates_file(tmp_path: Path) -> None:
    store = _build_store()
    out_file = tmp_path / "rapport.pdf"
    export_dataset_to_pdf(store, str(out_file))

    assert out_file.exists()
    assert out_file.stat().st_size > 0


def test_pdf_export_handles_non_numeric_amounts(tmp_path: Path) -> None:
    store = _build_store()
    store._customer_sales["Omsetning eks mva"] = store._customer_sales["Omsetning eks mva"].astype(object)  # type: ignore[index]
    store._supplier_purchases["Innkjøp eks mva"] = store._supplier_purchases["Innkjøp eks mva"].astype(object)  # type: ignore[index]
    store._customer_sales.loc[0, "Omsetning eks mva"] = "ukjent"  # type: ignore[index]
    store._supplier_purchases.loc[0, "Innkjøp eks mva"] = "?"  # type: ignore[index]

    out_file = tmp_path / "rapport_snill.pdf"
    export_dataset_to_pdf(store, str(out_file))

    assert out_file.exists()
    assert out_file.stat().st_size > 0
