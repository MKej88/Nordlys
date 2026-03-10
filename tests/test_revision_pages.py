from __future__ import annotations

from datetime import date
from typing import Generator

import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication, QWidget
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.saft.models import CostVoucher, VoucherLine
from nordlys.ui.pages.revision_pages import _CostVoucherReviewModule


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _voucher(number: str, supplier: str, amount: float) -> CostVoucher:
    return CostVoucher(
        transaction_id=number,
        document_number=number,
        transaction_date=date(2024, 1, 2),
        supplier_id=supplier,
        supplier_name=f"Leverandør {supplier}",
        description=f"Bilag {number}",
        amount=amount,
        lines=[
            VoucherLine(
                account="4000",
                account_name="Varekjøp",
                description="Testlinje",
                vat_code="1",
                debit=amount,
                credit=0.0,
            )
        ],
    )


def test_selection_status_overview_updates_with_decision(qapp: QApplication) -> None:
    module = _CostVoucherReviewModule(
        QWidget(),
        "Bilagskontroll",
        "Test",
        is_specific=False,
    )
    vouchers = [_voucher("1001", "2001", 1000.0), _voucher("1002", "2002", 2000.0)]

    module._start_review(vouchers)

    assert module.selection_status_table.rowCount() == 2
    assert module.selection_status_table.item(0, 2).text() == "Ikke vurdert"

    module._record_decision("Godkjent")

    assert module.selection_status_table.item(0, 2).text() == "Godkjent"


def test_clicking_status_overview_row_shows_selected_voucher(qapp: QApplication) -> None:
    module = _CostVoucherReviewModule(
        QWidget(),
        "Bilagskontroll",
        "Test",
        is_specific=False,
    )
    vouchers = [_voucher("1001", "2001", 1000.0), _voucher("1002", "2002", 2000.0)]

    module._start_review(vouchers)
    module._on_selection_overview_row_clicked(1, 0)

    assert module.value_document.text() == "1002"
