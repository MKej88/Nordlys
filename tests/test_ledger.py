from __future__ import annotations

from datetime import date

from nordlys.saft.ledger import build_ledger_rows, filter_ledger_rows
from nordlys.saft.models import CostVoucher, VoucherLine


def _voucher() -> CostVoucher:
    return CostVoucher(
        transaction_id="TX-1",
        document_number="B-10",
        transaction_date=date(2024, 1, 15),
        supplier_id=None,
        supplier_name=None,
        description="Faktura",
        amount=1000.0,
        lines=[
            VoucherLine(
                account="3000",
                account_name="Salgsinntekt",
                description="Salg",
                vat_code=None,
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


def test_build_ledger_rows_includes_counter_accounts() -> None:
    rows = build_ledger_rows([_voucher()])

    assert len(rows) == 2
    rows_by_account = {row.konto: row for row in rows}
    assert rows_by_account["3000"].dato == "2024-01-15"
    assert rows_by_account["3000"].motkontoer == "1500"
    assert rows_by_account["1500"].motkontoer == "3000"


def test_filter_ledger_rows_supports_account_and_name_search() -> None:
    rows = build_ledger_rows([_voucher()])

    account_filtered = filter_ledger_rows(rows, "300")
    assert len(account_filtered) == 1
    assert account_filtered[0].konto == "3000"

    name_filtered = filter_ledger_rows(rows, "kundeford")
    assert len(name_filtered) == 1
    assert name_filtered[0].konto == "1500"
