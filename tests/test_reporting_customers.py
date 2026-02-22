"""Tester for hjelpefunksjoner i reporting_customers."""

from datetime import date
from decimal import Decimal

from nordlys.saft.reporting_customers import (
    TransactionScope,
    _build_share_basis,
    _transaction_in_scope,
    build_aged_receivables,
)
from xml.etree import ElementTree as ET


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


def test_build_aged_receivables_buckets_open_items() -> None:
    xml_text = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Customer>
          <CustomerID>C1</CustomerID>
          <Name>Kunde 1</Name>
        </Customer>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2024-01-10</TransactionDate>
            <Line>
              <RecordID>1</RecordID>
              <AccountID>1500</AccountID>
              <CustomerID>C1</CustomerID>
              <DebitAmount>1000.00</DebitAmount>
              <CreditAmount>0.00</CreditAmount>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2024-02-10</TransactionDate>
            <Line>
              <RecordID>2</RecordID>
              <AccountID>1500</AccountID>
              <CustomerID>C1</CustomerID>
              <DebitAmount>0.00</DebitAmount>
              <CreditAmount>400.00</CreditAmount>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2024-03-15</TransactionDate>
            <Line>
              <RecordID>3</RecordID>
              <AccountID>1500</AccountID>
              <CustomerID>C1</CustomerID>
              <DebitAmount>500.00</DebitAmount>
              <CreditAmount>0.00</CreditAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml_text)
    ns = {"n1": "urn:StandardAuditFile-Taxation-Financial:NO"}

    aged = build_aged_receivables(root, ns, as_of_date=date(2024, 4, 1))

    assert len(aged.index) == 1
    row = aged.iloc[0]
    assert row["Kundenr"] == "C1"
    assert row["Kundenavn"] == "Kunde 1"
    assert row["61-90"] == 600.0
    assert row["0-30"] == 500.0
    assert row["Sum"] == 1100.0
