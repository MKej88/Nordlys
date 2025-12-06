"""Tester for hjelpefunksjoner i reporting_customers."""

from datetime import date
from decimal import Decimal

from nordlys.saft.reporting_customers import (
    TransactionScope,
    _build_share_basis,
    _transaction_in_scope,
)


def test_transaction_in_scope_date_range_filters_by_bounds() -> None:
    scope = TransactionScope(
        date=date(2023, 1, 10),
        voucher_description=None,
        transaction_description=None,
        period_year=None,
        period_number=None,
    )

    assert _transaction_in_scope(
        scope,
        start_date=date(2023, 1, 1),
        end_date=date(2023, 1, 31),
        year=None,
        last_period=None,
        use_range=True,
    )

    assert not _transaction_in_scope(
        scope,
        start_date=date(2023, 2, 1),
        end_date=date(2023, 2, 28),
        year=None,
        last_period=None,
        use_range=True,
    )


def test_transaction_in_scope_period_checks_last_period() -> None:
    scope = TransactionScope(
        date=None,
        voucher_description=None,
        transaction_description=None,
        period_year=2022,
        period_number=3,
    )

    assert _transaction_in_scope(
        scope,
        start_date=None,
        end_date=None,
        year=2022,
        last_period=6,
        use_range=False,
    )

    assert not _transaction_in_scope(
        scope,
        start_date=None,
        end_date=None,
        year=2023,
        last_period=None,
        use_range=False,
    )

    assert not _transaction_in_scope(
        scope,
        start_date=None,
        end_date=None,
        year=2022,
        last_period=2,
        use_range=False,
    )


def test_build_share_basis_merges_vat_and_gross_shares() -> None:
    gross = {"A": Decimal("200"), "B": Decimal("100")}
    vat_share = {"A": Decimal("50")}

    share_basis, share_total = _build_share_basis(gross, vat_share)

    assert share_basis == {"A": Decimal("50"), "B": Decimal("100")}
    assert share_total == Decimal("150")

    share_basis_no_vat, share_total_no_vat = _build_share_basis(gross, {})

    assert share_basis_no_vat == gross
    assert share_total_no_vat == Decimal("300")
