from __future__ import annotations

from datetime import date
from typing import Generator

import pandas as pd
import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.saft.models import CostVoucher, VoucherLine
from nordlys.ui.pages.hovedbok_page import HovedbokPage


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _voucher() -> CostVoucher:
    return CostVoucher(
        transaction_id="TX-1",
        document_number="B-10",
        transaction_date=date(2024, 1, 15),
        supplier_id=None,
        supplier_name=None,
        description="Utgående faktura",
        amount=1000.0,
        lines=[
            VoucherLine(
                account="3000",
                account_name="Salgsinntekt",
                description="Salg januar",
                vat_code="3",
                debit=0.0,
                credit=1000.0,
            ),
            VoucherLine(
                account="1500",
                account_name="Kundefordringer",
                description="Motpost",
                vat_code=None,
                debit=1000.0,
                credit=0.0,
            ),
        ],
    )


def _set_balances(page: HovedbokPage) -> None:
    balance_df = pd.DataFrame(
        {
            "Konto": ["3000"],
            "Kontonavn": ["Salgsinntekt"],
            "IB_netto": [0.0],
            "UB_netto": [-1000.0],
        }
    )
    page.set_account_balances(balance_df)


def test_apply_filter_shows_rows_for_account_in_balance(qapp: QApplication) -> None:
    page = HovedbokPage()
    page.set_vouchers([_voucher()])
    _set_balances(page)

    page.search_input.setText("3000")
    page.apply_filter()

    assert page.status_label.text() == "Viser 1 føringer."
    assert page.account_name_label.text() == "Konto: 3000 – Salgsinntekt"


def test_apply_filter_rejects_account_not_in_balance(qapp: QApplication) -> None:
    page = HovedbokPage()
    page.set_vouchers([_voucher()])
    _set_balances(page)

    page.search_input.setText("1500")
    page.apply_filter()

    assert page.status_label.text() == "Konto ikke finnes: 1500"
    assert page.account_name_label.text() == ""
