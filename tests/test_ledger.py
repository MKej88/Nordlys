from __future__ import annotations

from datetime import date

from nordlys.saft.ledger import (
    build_ledger_rows,
    build_statement_rows,
    filter_ledger_rows,
    rows_for_voucher,
    voucher_key_for_row,
)
from nordlys.saft.models import CostVoucher, VoucherLine


def _voucher(
    *,
    transaction_id: str = "TX-1",
    document_number: str | None = "B-10",
    description: str = "Utgående faktura",
) -> CostVoucher:
    return CostVoucher(
        transaction_id=transaction_id,
        document_number=document_number,
        transaction_date=date(2024, 1, 15),
        supplier_id=None,
        supplier_name=None,
        description=description,
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


def test_build_ledger_rows_maps_bilagstype_beskrivelse_and_mva() -> None:
    rows = build_ledger_rows([_voucher()])

    sales_row = [row for row in rows if row.konto == "3000"][0]
    assert sales_row.bilagstype == "Utgående faktura"
    assert sales_row.beskrivelse == "Salg januar"
    assert sales_row.mva == "3"
    assert sales_row.mva_belop == -1000.0


def test_filter_ledger_rows_supports_account_and_name_search() -> None:
    rows = build_ledger_rows([_voucher()])

    account_filtered = filter_ledger_rows(rows, "300")
    assert len(account_filtered) == 1
    assert account_filtered[0].konto == "3000"

    name_filtered = filter_ledger_rows(rows, "kundeford")
    assert len(name_filtered) == 1
    assert name_filtered[0].konto == "1500"


def test_rows_for_voucher_returns_all_lines_for_same_voucher() -> None:
    rows = build_ledger_rows([_voucher()])

    selected = rows[0]
    voucher_rows = rows_for_voucher(rows, selected)

    assert len(voucher_rows) == 2
    keys = {voucher_key_for_row(row) for row in voucher_rows}
    assert len(keys) == 1


def test_build_statement_rows_uses_transaction_id_when_bilag_missing() -> None:
    rows = build_ledger_rows([_voucher(document_number=None, transaction_id="TX-42")])

    statement_rows = build_statement_rows(rows)

    bilag_values = [row.bilag for row in statement_rows if row.source is not None]
    assert "TX-42" in bilag_values


def test_build_statement_rows_uses_balances_for_ib_and_ub() -> None:
    rows = build_ledger_rows([_voucher()])

    statement_rows = build_statement_rows(
        rows,
        account_balances={
            "3000": (-50.0, -1050.0),
            "1500": (50.0, 1050.0),
        },
    )

    assert statement_rows[0].tekst == "Inngående saldo"
    assert statement_rows[0].belop == 0.0
    assert statement_rows[-1].tekst == "Utgående saldo"
    assert statement_rows[-1].belop == 0.0
