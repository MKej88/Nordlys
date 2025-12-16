from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from decimal import Decimal
from threading import Lock
from typing import List, Sequence, Tuple

import pandas as pd
import pytest

from nordlys.saft import (
    check_trial_balance,
    iter_saft_entries,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saft_header,
    parse_saldobalanse,
    parse_suppliers,
    SaftValidationResult,
    validate_saft_against_xsd,
)
from nordlys.saft.reporting_accounts import extract_cost_vouchers
from nordlys.saft.header import SaftHeader
from nordlys.saft.customer_analysis import (
    _parse_date,
    build_customer_supplier_analysis,
)
from nordlys.saft.periods import format_header_period
from nordlys.saft_customers import (
    build_customer_name_map,
    build_supplier_name_map,
    compute_customer_supplier_totals,
    compute_purchases_per_supplier,
    compute_sales_per_customer,
    analyze_sales_receivable_correlation,
    extract_credit_notes,
    get_amount,
    get_tx_customer_id,
    get_tx_supplier_id,
    parse_saft,
    save_outputs,
)
from nordlys.helpers.formatting import format_currency, format_difference
from nordlys.saft.loader import SaftLoadResult, load_saft_files


def build_sample_root() -> ET.Element:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <Company>
          <Name>Test AS</Name>
          <RegistrationNumber>999999999</RegistrationNumber>
        </Company>
        <SelectionCriteria>
          <PeriodStart>2023-01-01</PeriodStart>
          <PeriodEnd>2023-12-31</PeriodEnd>
          <PeriodEndYear>2023</PeriodEndYear>
        </SelectionCriteria>
        <AuditFileVersion>1.0</AuditFileVersion>
      </Header>
      <MasterFiles>
        <GeneralLedgerAccounts>
          <Account>
            <AccountID>3000</AccountID>
            <AccountDescription>Salg</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>0</ClosingDebitBalance>
            <ClosingCreditBalance>1000</ClosingCreditBalance>
          </Account>
          <Account>
            <AccountID>4000</AccountID>
            <AccountDescription>Varekjøp</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>600</ClosingDebitBalance>
            <ClosingCreditBalance>0</ClosingCreditBalance>
          </Account>
          <Account>
            <AccountID>1500</AccountID>
            <AccountDescription>Kundefordringer</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>400</ClosingDebitBalance>
            <ClosingCreditBalance>0</ClosingCreditBalance>
          </Account>
          <Account>
            <AccountID>2400</AccountID>
            <AccountDescription>Leverandørgjeld</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>0</ClosingDebitBalance>
            <ClosingCreditBalance>600</ClosingCreditBalance>
          </Account>
        </GeneralLedgerAccounts>
        <Customer>
          <CustomerID>K1</CustomerID>
          <CustomerNumber>1001</CustomerNumber>
          <Name>Kunde 1</Name>
        </Customer>
        <Supplier>
          <SupplierID>S1</SupplierID>
          <SupplierAccountID>2001</SupplierAccountID>
          <SupplierName>Leverandør 1</SupplierName>
        </Supplier>
      </MasterFiles>
      <SourceDocuments>
        <SalesInvoices>
          <Invoice>
            <CustomerID>K1</CustomerID>
            <DocumentTotals>
              <TaxExclusiveAmount>1000</TaxExclusiveAmount>
              <NetTotal>1000</NetTotal>
              <GrossTotal>1250</GrossTotal>
              <TaxPayable>250</TaxPayable>
            </DocumentTotals>
          </Invoice>
        </SalesInvoices>
      </SourceDocuments>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>5</PeriodNumber>
            </Period>
            <TransactionDate>2023-05-02</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1250</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-03-10</TransactionDate>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>600</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>600</CreditAmount>
              <SupplierID>S1</SupplierID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    return ET.fromstring(xml)


def build_summary_frame(entries: Sequence[Tuple[int, float]]) -> pd.DataFrame:
    konto_int = [konto for konto, _ in entries]
    ub_debet: List[float] = []
    ub_kredit: List[float] = []
    for _, amount in entries:
        if amount >= 0:
            ub_debet.append(amount)
            ub_kredit.append(0.0)
        else:
            ub_debet.append(0.0)
            ub_kredit.append(-amount)
    zeros = [0.0] * len(entries)
    return pd.DataFrame(
        {
            "Konto": [str(konto) for konto in konto_int],
            "Konto_int": konto_int,
            "IB Debet": zeros,
            "IB Kredit": zeros,
            "UB Debet": ub_debet,
            "UB Kredit": ub_kredit,
        }
    )


def test_parse_header_and_customers():
    root = build_sample_root()
    header = parse_saft_header(root)
    assert header.company_name == "Test AS"
    assert header.orgnr == "999999999"
    assert header.fiscal_year == "2023"
    customers = parse_customers(root)
    assert "K1" in customers
    assert customers["K1"].customer_number == "1001"
    assert customers["K1"].name == "Kunde 1"


def test_parse_header_with_selection_dates():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <SelectionCriteria>
          <SelectionStartDate>2023-01-01</SelectionStartDate>
          <SelectionEndDate>31.12.2023</SelectionEndDate>
        </SelectionCriteria>
      </Header>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    header = parse_saft_header(root)
    assert header.period_start == "2023-01-01"
    assert header.period_end == "31.12.2023"


def test_parse_date_supports_multiple_formats():
    assert _parse_date("31.12.2023") == date(2023, 12, 31)
    assert _parse_date("20231231") == date(2023, 12, 31)


def test_format_header_period_normalizes_dates():
    header = SaftHeader(
        company_name=None,
        orgnr=None,
        fiscal_year="2024",
        period_start="2024-01-01",
        period_end="2024-12-31",
        file_version=None,
    )
    assert format_header_period(header) == "2024 P1–P12"


def test_format_header_period_handles_month_tokens_without_year():
    header = SaftHeader(
        company_name=None,
        orgnr=None,
        fiscal_year="2025",
        period_start="P1",
        period_end="P12",
        file_version=None,
    )
    assert format_header_period(header) == "2025 P1–P12"


def test_format_header_period_builds_year_range_when_needed():
    header = SaftHeader(
        company_name=None,
        orgnr=None,
        fiscal_year=None,
        period_start="2023-11-01",
        period_end="2024-01-31",
        file_version=None,
    )
    assert format_header_period(header) == "2023–2024 P11–P1"


def test_parse_saldobalanse_and_summary():
    root = build_sample_root()
    df = parse_saldobalanse(root)
    assert set(["Konto", "UB Debet", "UB Kredit"]).issubset(df.columns)
    summary = ns4102_summary_from_tb(df)
    # Salg 1000 -> driftsinntekter, varekost 600 -> varekostnad
    assert summary["driftsinntekter"] == 1000
    assert summary["varekostnad"] == 600
    assert summary["ebitda"] == 400
    assert summary["sum_inntekter"] == summary["driftsinntekter"]
    assert summary["annen_inntekt"] == 0
    assert summary["resultat_for_skatt"] == summary["ebt"]


def test_summary_breaks_out_income_and_finance_accounts():
    df = build_summary_frame(
        [
            (3000, -1000.0),
            (3800, -200.0),
            (3900, -100.0),
            (4000, 250.0),
            (5000, 100.0),
            (6000, 50.0),
            (6100, 25.0),
            (6200, 55.0),
            (7000, 75.0),
            (8000, -20.0),
            (8100, 5.0),
        ]
    )
    summary = ns4102_summary_from_tb(df)
    assert summary["sum_inntekter"] == pytest.approx(1300.0)
    assert summary["annen_inntekt"] == pytest.approx(300.0)
    assert summary["salgsinntekter"] == pytest.approx(1000.0)
    assert summary["andre_drift"] == pytest.approx(80.0)
    assert summary["annen_kost"] == pytest.approx(75.0)
    assert summary["finansinntekter"] == pytest.approx(20.0)
    assert summary["finanskostnader"] == pytest.approx(5.0)
    assert summary["resultat_for_skatt"] == pytest.approx(760.0)


@pytest.mark.parametrize(
    "company_block",
    [
        "<TaxRegistrationNumber>111222333</TaxRegistrationNumber>",
        "<TaxRegistrationNumber><RegistrationNumber>444555666</RegistrationNumber></TaxRegistrationNumber>",
        "<CompanyID>777888999</CompanyID>",
        "<TaxRegistrationNumber><CompanyID>123123123</CompanyID></TaxRegistrationNumber>",
    ],
)
def test_parse_header_registration_number_fallbacks(company_block: str):
    xml = f"""
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <Company>
          <Name>Fallback AS</Name>
          {company_block}
        </Company>
      </Header>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    header = parse_saft_header(root)
    expected = "".join(
        ch
        for ch in ET.fromstring(f"<root>{company_block}</root>").itertext()
        if ch.strip()
    )
    assert header.orgnr == expected


def test_parse_saft_detects_namespace(tmp_path):
    xml_path = tmp_path / "simple.xml"
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        "  <Header><AuditFileVersion>1.0</AuditFileVersion></Header>"
        "</AuditFile>",
        encoding="utf-8",
    )
    tree, ns = parse_saft(xml_path)
    assert tree.getroot().tag.endswith("AuditFile")
    assert ns["n1"] == "urn:StandardAuditFile-Taxation-Financial:NO"


def test_iter_saft_entries_streams_lines(tmp_path):
    root = build_sample_root()
    xml_path = tmp_path / "stream.xml"
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

    entries = list(iter_saft_entries(xml_path))

    assert len(entries) == 5
    assert entries[0]["account_id"] == "3000"
    assert entries[0]["kredit"] == Decimal("1000")
    total_debet = sum(item["debet"] for item in entries)
    total_kredit = sum(item["kredit"] for item in entries)
    assert total_debet == Decimal("1850")
    assert total_kredit == Decimal("1850")


def test_iter_saft_entries_handles_amount_wrapper(tmp_path):
    xml_path = tmp_path / "nested_amount.xml"
    xml_path.write_text(
        """
        <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
          <GeneralLedgerEntries>
            <Journal>
              <Transaction>
                <Line>
                  <Description>Debet med Amount</Description>
                  <DebitAmount><Amount>1 234,50</Amount></DebitAmount>
                </Line>
                <Line>
                  <Description>Kredit med Amount</Description>
                  <CreditAmount><Amount>1234.50</Amount></CreditAmount>
                </Line>
              </Transaction>
            </Journal>
          </GeneralLedgerEntries>
        </AuditFile>
        """.strip(),
        encoding="utf-8",
    )

    entries = list(iter_saft_entries(xml_path))

    assert len(entries) == 2
    assert entries[0]["debet"] == Decimal("1234.50")
    assert entries[0]["line_description"] == "Debet med Amount"
    assert entries[1]["kredit"] == Decimal("1234.50")
    assert entries[1]["line_description"] == "Kredit med Amount"


def test_check_trial_balance_balanced(tmp_path):
    root = build_sample_root()
    xml_path = tmp_path / "balanced.xml"
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

    result = check_trial_balance(xml_path)

    assert result["debet"] == Decimal("1850")
    assert result["kredit"] == Decimal("1850")
    assert result["diff"] == Decimal("0")


def test_check_trial_balance_reports_diff(tmp_path):
    xml_path = tmp_path / "unbalanced.xml"
    xml_path.write_text(
        """
        <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
          <GeneralLedgerEntries>
            <Journal>
              <Transaction>
                <Line>
                  <AccountID>1000</AccountID>
                  <DebitAmount>100</DebitAmount>
                </Line>
                <Line>
                  <AccountID>2000</AccountID>
                  <CreditAmount>90</CreditAmount>
                </Line>
              </Transaction>
            </Journal>
          </GeneralLedgerEntries>
        </AuditFile>
        """.strip(),
        encoding="utf-8",
    )

    result = check_trial_balance(xml_path)

    assert result["debet"] == Decimal("100")
    assert result["kredit"] == Decimal("90")
    assert result["diff"] == Decimal("10")


def test_validate_saft_handles_missing_file(tmp_path):
    missing_path = tmp_path / "finnes_ikke.xml"
    result = validate_saft_against_xsd(missing_path)

    assert result.is_valid in (None, False)
    assert result.details is not None and result.details.strip() != ""


def test_get_amount_handles_nested_amount():
    line_xml = """
    <Line xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <CreditAmount><Amount>123,45</Amount></CreditAmount>
      <DebitAmount>10</DebitAmount>
    </Line>
    """
    line = ET.fromstring(line_xml)
    ns = {"n1": "urn:StandardAuditFile-Taxation-Financial:NO"}
    credit = get_amount(line, "CreditAmount", ns)
    debit = get_amount(line, "DebitAmount", ns)
    assert float(credit) == pytest.approx(123.45)
    assert float(debit) == pytest.approx(10.0)


def test_get_tx_customer_id_priority():
    ns = {"n1": "urn:StandardAuditFile-Taxation-Financial:NO"}
    xml_ar = """
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Line>
        <AccountID>3000</AccountID>
        <CustomerID>SALE</CustomerID>
      </Line>
      <Line>
        <AccountID>1500</AccountID>
        <CustomerID>AR-CUST</CustomerID>
      </Line>
    </Transaction>
    """
    transaction_ar = ET.fromstring(xml_ar)
    assert get_tx_customer_id(transaction_ar, ns) == "AR-CUST"

    xml_dimensions = """
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Line>
        <AccountID>4000</AccountID>
        <CustomerID />
      </Line>
      <Line>
        <AccountID>4900</AccountID>
        <Dimensions>
          <CustomerID>DIM-CUST</CustomerID>
        </Dimensions>
      </Line>
    </Transaction>
    """
    transaction_dim = ET.fromstring(xml_dimensions)
    assert get_tx_customer_id(transaction_dim, ns) == "DIM-CUST"

    xml_analysis = """
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Line>
        <AccountID>4900</AccountID>
        <Dimensions>
          <Analysis>
            <Type>customer-segment</Type>
            <ID>ANAL-CUST</ID>
          </Analysis>
        </Dimensions>
      </Line>
    </Transaction>
    """
    transaction_analysis = ET.fromstring(xml_analysis)
    assert get_tx_customer_id(transaction_analysis, ns) == "ANAL-CUST"


@pytest.mark.parametrize(
    "customer_block",
    [
        "<CustomerInfo><CustomerID>TX-CUST</CustomerID></CustomerInfo>",
        "<Customer><CustomerID>TX-CUST</CustomerID></Customer>",
        "<CustomerID>TX-CUST</CustomerID>",
    ],
)
def test_get_tx_customer_id_reads_transaction_level_blocks(customer_block: str) -> None:
    ns = {"n1": "urn:StandardAuditFile-Taxation-Financial:NO"}
    xml = f"""
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      {customer_block}
      <Line>
        <AccountID>3000</AccountID>
        <CreditAmount>100</CreditAmount>
      </Line>
    </Transaction>
    """
    transaction = ET.fromstring(xml)
    assert get_tx_customer_id(transaction, ns) == "TX-CUST"


def test_compute_sales_per_customer():
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert not df.empty
    row = df.iloc[0]
    assert row["Kundenr"] == "K1"
    assert row["Kundenavn"] == "Kunde 1"
    assert row["Omsetning eks mva"] == pytest.approx(1000.0)
    assert row["Transaksjoner"] == 1


def test_compute_sales_per_customer_date_filter():
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(
        root, ns, date_from="2023-06-01", date_to="2023-12-31"
    )
    assert df.empty


def test_compute_sales_per_customer_distributes_vat():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>4</PeriodNumber>
            </Period>
            <TransactionDate>2023-04-15</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1200</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>300</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>500</DebitAmount>
              <CustomerID>C1</CustomerID>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
              <CustomerID>C2</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert set(df["Kundenr"]) == {"C1", "C2"}
    totals = dict(zip(df["Kundenr"], df["Omsetning eks mva"]))
    assert totals["C1"] == pytest.approx(400.0)
    assert totals["C2"] == pytest.approx(800.0)
    counts = dict(zip(df["Kundenr"], df["Transaksjoner"]))
    assert counts["C1"] == 1
    assert counts["C2"] == 1


@pytest.mark.parametrize(
    "customer_block",
    [
        "<CustomerInfo><CustomerID>CASH1</CustomerID></CustomerInfo>",
        "<Customer><CustomerID>CASH1</CustomerID></Customer>",
        "<CustomerID>CASH1</CustomerID>",
    ],
)
def test_compute_sales_per_customer_includes_cash_sale_with_tx_customer(
    customer_block: str,
) -> None:
    xml = f"""
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>5</PeriodNumber>
            </Period>
            <TransactionDate>2023-05-05</TransactionDate>
            {customer_block}
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1250</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
      <MasterFiles>
        <Customers>
          <Customer>
            <CustomerID>CASH1</CustomerID>
            <Name>Kontantsalg</Name>
          </Customer>
        </Customers>
      </MasterFiles>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = compute_sales_per_customer(root, ns, year=2023)

    assert list(df["Kundenr"]) == ["CASH1"]
    assert df.loc[0, "Omsetning eks mva"] == pytest.approx(1000.0)
    assert df.loc[0, "Transaksjoner"] == 1


@pytest.mark.parametrize(
    ("voucher_description", "expected_customer"),
    [
        ("Annet", "A"),
        ("Diverse", "D"),
    ],
)
def test_compute_sales_per_customer_assigns_voucher_description_buckets(
    voucher_description: str, expected_customer: str
) -> None:
    xml = f"""
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Customers>
          <Customer>
            <CustomerID>A</CustomerID>
            <Name>Annet</Name>
          </Customer>
          <Customer>
            <CustomerID>D</CustomerID>
            <Name>Diverse</Name>
          </Customer>
        </Customers>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>6</PeriodNumber>
            </Period>
            <TransactionDate>2023-06-15</TransactionDate>
            <VoucherDescription>{voucher_description}</VoucherDescription>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1250</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = compute_sales_per_customer(root, ns, year=2023)

    assert list(df["Kundenr"]) == [expected_customer]
    assert df.loc[0, "Omsetning eks mva"] == pytest.approx(1000.0)
    assert df.loc[0, "Transaksjoner"] == 1


@pytest.mark.parametrize(
    ("voucher_description", "expected_customer"),
    [
        ("Kontantsalg diverse kunder", "D"),
        ("Annet kontantoppgjør", "A"),
    ],
)
def test_compute_sales_per_customer_handles_voucher_description_substrings(
    voucher_description: str, expected_customer: str
) -> None:
    xml = f"""
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>6</PeriodNumber>
            </Period>
            <TransactionDate>2023-06-15</TransactionDate>
            <VoucherDescription>{voucher_description}</VoucherDescription>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1250</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = compute_sales_per_customer(root, ns, year=2023)

    assert list(df["Kundenr"]) == [expected_customer]
    assert df.loc[0, "Omsetning eks mva"] == pytest.approx(1000.0)
    assert df.loc[0, "Transaksjoner"] == 1


def test_compute_sales_per_customer_creates_missing_bucket_customers() -> None:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>6</PeriodNumber>
            </Period>
            <TransactionDate>2023-06-15</TransactionDate>
            <VoucherDescription>Annet</VoucherDescription>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1250</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = compute_sales_per_customer(root, ns, year=2023)

    assert list(df["Kundenr"]) == ["A"]
    assert df.loc[0, "Kundenavn"] == "Annet"
    assert df.loc[0, "Omsetning eks mva"] == pytest.approx(1000.0)


def test_compute_sales_per_customer_does_not_use_general_description_buckets() -> None:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Customers>
          <Customer>
            <CustomerID>A</CustomerID>
            <Name>Annet</Name>
          </Customer>
        </Customers>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>6</PeriodNumber>
            </Period>
            <TransactionDate>2023-06-20</TransactionDate>
            <Description>Salg Diverse kunder</Description>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1250</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = compute_sales_per_customer(root, ns, year=2023)

    assert df.empty


def test_compute_sales_per_customer_balances_against_revenue() -> None:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>2</PeriodNumber>
            </Period>
            <TransactionDate>2023-02-15</TransactionDate>
            <CustomerInfo>
              <CustomerID>CHK1</CustomerID>
            </CustomerInfo>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
              <CustomerID>CHK1</CustomerID>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>250</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
      <MasterFiles>
        <Customers>
          <Customer>
            <CustomerID>CHK1</CustomerID>
            <Name>Kontrollkunde</Name>
          </Customer>
        </Customers>
      </MasterFiles>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = compute_sales_per_customer(root, ns, year=2023)

    assert list(df["Kundenr"]) == ["CHK1"]
    assert df.loc[0, "Omsetning eks mva"] == pytest.approx(1000.0)
    assert df.loc[0, "Transaksjoner"] == 1


def test_compute_sales_per_customer_ignores_payments_without_vat():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>3</PeriodNumber>
            </Period>
            <TransactionDate>2023-03-01</TransactionDate>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>200</DebitAmount>
              <CustomerID>PAY</CustomerID>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <CreditAmount>200</CreditAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert df.empty


def test_compute_sales_per_customer_falls_back_to_transaction_customer():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>1</PeriodNumber>
            </Period>
            <TransactionDate>2023-01-10</TransactionDate>
            <CustomerInfo>
              <CustomerID>HEAD-1</CustomerID>
            </CustomerInfo>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1250</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1500</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert list(df["Kundenr"]) == ["HEAD-1"]
    assert df.iloc[0]["Omsetning eks mva"] == pytest.approx(1250.0)


def test_compute_sales_per_customer_includes_non_1500_customer_lines():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>4</PeriodNumber>
            </Period>
            <TransactionDate>2023-04-20</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1200</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>300</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1500</DebitAmount>
              <CustomerID>BANK</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert list(df["Kundenr"]) == ["BANK"]
    assert df.iloc[0]["Omsetning eks mva"] == pytest.approx(1200.0)


def test_compute_sales_per_customer_ignores_non_receivable_lines_without_customer():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>9</PeriodNumber>
            </Period>
            <TransactionDate>2023-09-10</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1250</DebitAmount>
              <CustomerID>CUST-1</CustomerID>
            </Line>
            <Line>
              <AccountID>1460</AccountID>
              <CreditAmount>600</CreditAmount>
            </Line>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>600</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert list(df["Kundenr"]) == ["CUST-1"]
    assert df.iloc[0]["Omsetning eks mva"] == pytest.approx(1000.0)


def test_compute_sales_per_customer_includes_asset_sale_without_vat():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>8</PeriodNumber>
            </Period>
            <TransactionDate>2023-08-05</TransactionDate>
            <Line>
              <AccountID>3800</AccountID>
              <CreditAmount>200000</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>200000</DebitAmount>
              <CustomerID>ASSET</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert list(df["Kundenr"]) == ["ASSET"]
    assert df.iloc[0]["Omsetning eks mva"] == pytest.approx(200000.0)


def test_compute_sales_per_customer_last_period_filter():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>5</PeriodNumber>
            </Period>
            <TransactionDate>2023-05-20</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>800</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>200</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
              <CustomerID>PER</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>11</PeriodNumber>
            </Period>
            <TransactionDate>2023-11-10</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1250</DebitAmount>
              <CustomerID>PER</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023, last_period=6)
    assert list(df["Kundenr"]) == ["PER"]
    assert df.iloc[0]["Omsetning eks mva"] == pytest.approx(800.0)


def test_compute_sales_per_customer_excludes_zero_net_customers():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>2</PeriodNumber>
            </Period>
            <TransactionDate>2023-02-01</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1250</DebitAmount>
              <CustomerID>ZERO</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>3</PeriodNumber>
            </Period>
            <TransactionDate>2023-03-01</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <DebitAmount>1000</DebitAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <DebitAmount>250</DebitAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <CreditAmount>1250</CreditAmount>
              <CustomerID>ZERO</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert df.empty


def test_parse_suppliers_and_compute_purchases():
    root = build_sample_root()
    suppliers = parse_suppliers(root)
    assert "S1" in suppliers
    assert suppliers["S1"].supplier_number == "2001"

    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_purchases_per_supplier(root, ns, year=2023)
    assert not df.empty
    row = df.iloc[0]
    assert row["Leverandørnr"] == "S1"
    assert row["Leverandørnavn"] == "Leverandør 1"
    assert row["Innkjøp eks mva"] == pytest.approx(600.0)
    assert row["Transaksjoner"] == 1


def test_compute_purchases_per_supplier_date_filter():
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_purchases_per_supplier(
        root, ns, date_from="2023-07-01", date_to="2023-12-31"
    )
    assert df.empty


def test_extract_credit_notes_filters_months_and_year():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>2</PeriodNumber>
            </Period>
            <TransactionDate>2023-02-15</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <DebitAmount>500</DebitAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <CreditAmount>500</CreditAmount>
            </Line>
          </Transaction>
            <Transaction>
              <TransactionDate>2023-03-01</TransactionDate>
              <Line>
                <AccountID>3000</AccountID>
                <DebitAmount>800</DebitAmount>
              </Line>
              <Line>
                <AccountID>1500</AccountID>
                <CreditAmount>800</CreditAmount>
              </Line>
            </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    df = extract_credit_notes(root, ns, year=2023)
    assert len(df.index) == 2
    feb_row = df.iloc[0]
    march_row = df.iloc[1]
    assert feb_row["Dato"] == date(2023, 2, 15)
    assert feb_row["Beløp"] == pytest.approx(500.0)
    assert "3000" in feb_row["Kontoer"]
    assert march_row["Dato"] == date(2023, 3, 1)
    assert march_row["Beløp"] == pytest.approx(800.0)


def test_analyze_sales_receivable_correlation_separates_totals():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionID>1001</TransactionID>
            <TransactionDate>2023-02-10</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionID>2001</TransactionID>
            <TransactionDate>2023-03-05</TransactionDate>
            <Line>
              <AccountID>3100</AccountID>
              <CreditAmount>800</CreditAmount>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>800</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """

    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    result = analyze_sales_receivable_correlation(root, ns, year=2023)

    assert result.with_receivable_total == pytest.approx(1000.0)
    assert result.without_receivable_total == pytest.approx(800.0)
    assert len(result.missing_sales.index) == 1
    missing_row = result.missing_sales.iloc[0]
    assert missing_row["Dato"] == date(2023, 3, 5)
    assert missing_row["Bilagsnr"] == "2001"
    assert missing_row["Beløp"] == pytest.approx(800.0)
    assert "3100" in missing_row["Kontoer"]
    assert "1920" in missing_row["Motkontoer"]


def test_compute_customer_supplier_totals_matches_individual():
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    expected_sales = compute_sales_per_customer(root, ns, year=2023)
    expected_purchases = compute_purchases_per_supplier(root, ns, year=2023)

    sales, purchases = compute_customer_supplier_totals(root, ns, year=2023)

    pd.testing.assert_frame_equal(sales, expected_sales)
    pd.testing.assert_frame_equal(purchases, expected_purchases)


def test_compute_customer_supplier_totals_respects_last_period_for_suppliers():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>4</PeriodNumber>
            </Period>
            <TransactionDate>2023-04-15</TransactionDate>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>500</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>500</CreditAmount>
              <SupplierID>EARLY</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>9</PeriodNumber>
            </Period>
            <TransactionDate>2023-09-15</TransactionDate>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>900</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>900</CreditAmount>
              <SupplierID>LATE</SupplierID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    _, purchases_all = compute_customer_supplier_totals(root, ns, year=2023)
    assert set(purchases_all["Leverandørnr"]) == {"EARLY", "LATE"}

    _, purchases_limited = compute_customer_supplier_totals(
        root, ns, year=2023, last_period=6
    )
    assert list(purchases_limited["Leverandørnr"]) == ["EARLY"]
    assert purchases_limited.iloc[0]["Innkjøp eks mva"] == pytest.approx(500.0)


def test_compute_customer_supplier_totals_empty_results_and_export(tmp_path):
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2023-02-01</TransactionDate>
            <Line>
              <AccountID>1000</AccountID>
              <DebitAmount>500</DebitAmount>
              <CustomerID>CU-1</CustomerID>
            </Line>
            <Line>
              <AccountID>1900</AccountID>
              <CreditAmount>500</CreditAmount>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-03-15</TransactionDate>
            <Line>
              <AccountID>2900</AccountID>
              <DebitAmount>750</DebitAmount>
            </Line>
            <Line>
              <AccountID>2100</AccountID>
              <CreditAmount>750</CreditAmount>
              <SupplierID>SUP-1</SupplierID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    customer_df, supplier_df = compute_customer_supplier_totals(root, ns, year=2023)

    assert list(customer_df.columns) == ["Kundenr", "Kundenavn", "Omsetning eks mva"]
    assert list(supplier_df.columns) == [
        "Leverandørnr",
        "Leverandørnavn",
        "Innkjøp eks mva",
    ]
    assert customer_df.empty
    assert supplier_df.empty

    csv_path, xlsx_path = save_outputs(customer_df, tmp_path, 2023)
    assert csv_path.exists()
    assert xlsx_path.exists()


def test_customer_supplier_analysis_includes_all_file_months():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <SelectionCriteria>
          <PeriodStart>2023-01-01</PeriodStart>
          <PeriodEnd>2023-10-31</PeriodEnd>
        </SelectionCriteria>
        <FiscalYear>2023</FiscalYear>
      </Header>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>5</PeriodNumber>
            </Period>
            <TransactionDate>2023-05-15</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1250</DebitAmount>
              <CustomerID>FULL-YEAR</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>12</PeriodNumber>
            </Period>
            <TransactionDate>2023-12-10</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>250</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1250</DebitAmount>
              <CustomerID>FULL-YEAR</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    header = parse_saft_header(root)

    analysis = build_customer_supplier_analysis(header, root, ns)

    assert analysis.customer_sales is not None
    totals = dict(
        zip(
            analysis.customer_sales["Kundenr"],
            analysis.customer_sales["Omsetning eks mva"],
        )
    )
    assert totals["FULL-YEAR"] == pytest.approx(2000.0)


def test_build_customer_supplier_analysis_handles_missing_transaction_dates():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <SelectionCriteria>
          <PeriodEnd>2023-12-31</PeriodEnd>
        </SelectionCriteria>
        <FiscalYear>2023</FiscalYear>
      </Header>
      <MasterFiles>
        <Customer>
          <CustomerID>PERIOD-ONLY</CustomerID>
          <Name>Period Customer</Name>
        </Customer>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Period>
              <PeriodYear>2023</PeriodYear>
              <PeriodNumber>2</PeriodNumber>
            </Period>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>500</CreditAmount>
            </Line>
            <Line>
              <AccountID>2700</AccountID>
              <CreditAmount>125</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>625</DebitAmount>
              <CustomerID>PERIOD-ONLY</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    header = parse_saft_header(root)

    analysis = build_customer_supplier_analysis(header, root, ns)

    assert analysis.customer_sales is not None
    assert not analysis.customer_sales.empty
    totals = dict(
        zip(
            analysis.customer_sales["Kundenr"],
            analysis.customer_sales["Omsetning eks mva"],
        )
    )
    assert totals["PERIOD-ONLY"] == pytest.approx(500.0)


def test_compute_purchases_includes_all_cost_accounts():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2023-01-15</TransactionDate>
            <Line>
              <AccountID>5500</AccountID>
              <DebitAmount>250</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>250</CreditAmount>
              <SupplierID>SUP-55</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-02-20</TransactionDate>
            <Line>
              <AccountID>6300</AccountID>
              <DebitAmount>400</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>400</CreditAmount>
              <SupplierID>SUP-63</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-03-12</TransactionDate>
            <Line>
              <AccountID>3100</AccountID>
              <DebitAmount>999</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>999</CreditAmount>
              <SupplierID>SUP-31</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-04-18</TransactionDate>
            <Line>
              <AccountID>7800</AccountID>
              <DebitAmount>150</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>150</CreditAmount>
              <SupplierID>SUP-78</SupplierID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_purchases_per_supplier(root, ns, year=2023)
    assert set(df["Leverandørnr"]) == {"SUP-55", "SUP-63", "SUP-78"}
    totals = dict(zip(df["Leverandørnr"], df["Innkjøp eks mva"]))
    assert totals["SUP-55"] == pytest.approx(250.0)
    assert totals["SUP-63"] == pytest.approx(400.0)
    assert totals["SUP-78"] == pytest.approx(150.0)


def test_get_tx_supplier_id_priority():
    ns = {"n1": "urn:StandardAuditFile-Taxation-Financial:NO"}
    xml_ap = """
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Line>
        <AccountID>2400</AccountID>
        <SupplierID>AP-SUP</SupplierID>
      </Line>
      <Line>
        <AccountID>4000</AccountID>
        <SupplierID>GEN-SUP</SupplierID>
      </Line>
    </Transaction>
    """
    transaction_ap = ET.fromstring(xml_ap)
    assert get_tx_supplier_id(transaction_ap, ns) == "AP-SUP"

    xml_dim = """
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Line>
        <AccountID>4000</AccountID>
        <Dimensions>
          <SupplierID>DIM-SUP</SupplierID>
        </Dimensions>
      </Line>
    </Transaction>
    """
    transaction_dim = ET.fromstring(xml_dim)
    assert get_tx_supplier_id(transaction_dim, ns) == "DIM-SUP"

    xml_analysis = """
    <Transaction xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Line>
        <AccountID>4800</AccountID>
        <Dimensions>
          <Analysis>
            <Type>supplier-segment</Type>
            <ID>ANAL-SUP</ID>
          </Analysis>
        </Dimensions>
      </Line>
    </Transaction>
    """
    transaction_analysis = ET.fromstring(xml_analysis)
    assert get_tx_supplier_id(transaction_analysis, ns) == "ANAL-SUP"


def test_build_supplier_name_map_fallback():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>500</DebitAmount>
            </Line>
            <SupplierInfo>
              <SupplierID>SUP1</SupplierID>
              <SupplierName>Fallback Leverandør</SupplierName>
            </SupplierInfo>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    names = build_supplier_name_map(root, ns)
    assert names["SUP1"] == "Fallback Leverandør"


def test_build_customer_name_map_fallback():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>500</CreditAmount>
            </Line>
            <CustomerInfo>
              <CustomerID>CU1</CustomerID>
              <Name>Fallback Navn</Name>
            </CustomerInfo>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}
    names = build_customer_name_map(root, ns)
    assert names["CU1"] == "Fallback Navn"


def test_build_customer_name_map_includes_bucket_names():
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>500</CreditAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    root = ET.fromstring(xml)
    ns = {"n1": root.tag.split("}")[0][1:]}

    names = build_customer_name_map(root, ns)

    assert names["A"] == "Annet"
    assert names["D"] == "Diverse"


def test_save_outputs(tmp_path):
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    csv_path, xlsx_path = save_outputs(df, tmp_path, 2023)
    assert csv_path.exists()
    assert xlsx_path.exists()
    assert xlsx_path.suffix in {".xlsx", ".csv"}
    saved = pd.read_csv(csv_path)
    assert "Kundenr" in saved.columns


def test_save_outputs_faller_til_xlsxwriter(tmp_path, monkeypatch):
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)

    original_to_excel = pd.DataFrame.to_excel

    def fake_to_excel(self, *args, **kwargs):
        if args and isinstance(args[0], pd.ExcelWriter):
            return original_to_excel(self, *args, **kwargs)
        raise ModuleNotFoundError("No module named 'openpyxl'")

    monkeypatch.setattr(pd.DataFrame, "to_excel", fake_to_excel, raising=False)

    csv_path, xlsx_path = save_outputs(df, tmp_path, 2023)

    assert csv_path.exists()
    assert xlsx_path.exists()
    assert xlsx_path.suffix == ".xlsx"

    with zipfile.ZipFile(xlsx_path) as archive:
        contents = set(archive.namelist())
        assert "xl/workbook.xml" in contents
        assert any(name.startswith("xl/worksheets/sheet") for name in contents)


def test_format_helpers():
    assert format_currency(1234.5) == "1 235"
    assert format_difference(2000, 1500) == "500"


def test_validate_saft_against_xsd_unknown_version(tmp_path):
    xml_path = tmp_path / "saft_unknown.xml"
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        "  <Header>"
        "    <AuditFileVersion>9.9</AuditFileVersion>"
        "  </Header>"
        "</AuditFile>",
        encoding="utf-8",
    )
    result = validate_saft_against_xsd(xml_path, "9.9")
    assert result.is_valid is None
    assert result.version_family is None
    assert "Ingen XSD" in (result.details or "")


def test_validate_saft_against_xsd_known_version(tmp_path):
    xml_path = tmp_path / "saft_13.xml"
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        "  <Header>"
        "    <AuditFileVersion>1.30</AuditFileVersion>"
        "  </Header>"
        "</AuditFile>",
        encoding="utf-8",
    )
    result = validate_saft_against_xsd(xml_path)
    assert result.version_family == "1.3"
    assert result.schema_version == "1.30"
    saft_module = sys.modules["nordlys.saft"]
    if saft_module.XMLSCHEMA_AVAILABLE:
        assert result.is_valid is False
    else:
        assert result.is_valid is None
        assert "xmlschema" in (result.details or "").lower()


def test_validate_saft_against_xsd_without_dependency(monkeypatch, tmp_path):
    saft_module = sys.modules["nordlys.saft"]
    validation_module = sys.modules["nordlys.saft.validation"]
    monkeypatch.setattr(saft_module, "XMLSCHEMA_AVAILABLE", False, raising=False)
    monkeypatch.setattr(validation_module, "XMLSCHEMA_AVAILABLE", False, raising=False)
    monkeypatch.setattr(validation_module, "XMLSchema", None, raising=False)
    xml_path = tmp_path / "saft_12.xml"
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        "  <Header>"
        "    <AuditFileVersion>1.20</AuditFileVersion>"
        "  </Header>"
        "</AuditFile>",
        encoding="utf-8",
    )
    result = validate_saft_against_xsd(xml_path)
    assert result.version_family == "1.2"
    assert result.is_valid is None
    assert "xmlschema" in (result.details or "").lower()


def test_validate_saft_against_xsd_uses_lazy_xmlresource(monkeypatch, tmp_path):
    validation_module = sys.modules["nordlys.saft.validation"]
    xml_path = tmp_path / "saft_lazy.xml"
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        "  <Header>"
        "    <AuditFileVersion>1.30</AuditFileVersion>"
        "  </Header>"
        "</AuditFile>",
        encoding="utf-8",
    )
    schema_path = tmp_path / "schema.xsd"
    schema_path.write_text("<schema />", encoding="utf-8")

    call_info: dict[str, object] = {}

    class FakeSchema:
        def __init__(self, path: str) -> None:
            assert path == str(schema_path)

        def validate(self, resource: object) -> None:
            call_info["resource"] = resource

    class FakeResource:
        def __init__(self, source: str, **kwargs) -> None:
            call_info["source"] = source
            call_info["lazy"] = kwargs.get("lazy")

    monkeypatch.setattr(validation_module, "XMLSCHEMA_AVAILABLE", True, raising=False)
    monkeypatch.setattr(validation_module, "XMLSchema", FakeSchema, raising=False)
    monkeypatch.setattr(validation_module, "XMLResource", FakeResource, raising=False)
    monkeypatch.setattr(validation_module, "_ensure_xmlschema_loaded", lambda: True)
    monkeypatch.setattr(
        validation_module,
        "_schema_info_for_family",
        lambda _: (schema_path, "1.30"),
    )

    result = validation_module.validate_saft_against_xsd(xml_path, version="1.30")

    assert result.is_valid is True
    assert call_info["source"] == str(xml_path)
    assert call_info["lazy"] is True


def test_validate_saft_against_xsd_caches_schema(monkeypatch, tmp_path):
    validation_module = sys.modules["nordlys.saft.validation"]
    xml_path = tmp_path / "saft_cached.xml"
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        "  <Header>"
        "    <AuditFileVersion>1.30</AuditFileVersion>"
        "  </Header>"
        "</AuditFile>",
        encoding="utf-8",
    )
    schema_path = tmp_path / "schema.xsd"
    schema_path.write_text("<schema />", encoding="utf-8")

    call_count = {"init": 0}

    class FakeSchema:
        def __init__(self, path: str) -> None:
            call_count["init"] += 1
            assert path == str(schema_path)

        def validate(self, resource: object) -> None:
            return None

    monkeypatch.setattr(validation_module, "XMLSCHEMA_AVAILABLE", True, raising=False)
    monkeypatch.setattr(validation_module, "XMLSchema", FakeSchema, raising=False)
    monkeypatch.setattr(validation_module, "_SCHEMA_CACHE", {}, raising=False)
    monkeypatch.setattr(validation_module, "_SCHEMA_CACHE_LOCK", Lock(), raising=False)
    monkeypatch.setattr(validation_module, "_ensure_xmlschema_loaded", lambda: True)
    monkeypatch.setattr(
        validation_module, "_schema_info_for_family", lambda _: (schema_path, "1.30")
    )

    first = validation_module.validate_saft_against_xsd(xml_path, version="1.30")
    second = validation_module.validate_saft_against_xsd(xml_path, version="1.30")

    assert first.is_valid is True
    assert second.is_valid is True
    assert call_count["init"] == 1


def test_validate_saft_against_xsd_accepts_element_tree(monkeypatch, tmp_path):
    validation_module = sys.modules["nordlys.saft.validation"]

    xml_root = ET.fromstring(
        """
        <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
          <Header>
            <AuditFileVersion>1.30</AuditFileVersion>
          </Header>
        </AuditFile>
        """
    )
    xml_tree = ET.ElementTree(xml_root)
    schema_path = tmp_path / "schema.xsd"
    schema_path.write_text("<schema />", encoding="utf-8")

    call_info: dict[str, object] = {}

    class FakeSchema:
        def __init__(self, path: str) -> None:
            call_info["schema_path"] = path

        def validate(self, resource: object) -> None:
            call_info["resource"] = resource

    monkeypatch.setattr(validation_module, "XMLSCHEMA_AVAILABLE", True, raising=False)
    monkeypatch.setattr(validation_module, "XMLSchema", FakeSchema, raising=False)
    monkeypatch.setattr(validation_module, "_SCHEMA_CACHE", {}, raising=False)
    monkeypatch.setattr(validation_module, "_SCHEMA_CACHE_LOCK", Lock(), raising=False)
    monkeypatch.setattr(validation_module, "_ensure_xmlschema_loaded", lambda: True)
    monkeypatch.setattr(
        validation_module, "_schema_info_for_family", lambda _: (schema_path, "1.30")
    )

    result = validation_module.validate_saft_against_xsd(xml_tree)

    assert result.is_valid is True
    assert call_info["resource"] is xml_tree


def test_load_saft_files_parallel_progress(monkeypatch):
    validation = SaftValidationResult(
        audit_file_version=None,
        version_family=None,
        schema_version=None,
        is_valid=None,
    )

    def fake_load(path: str, progress_callback=None, file_size=None):
        if progress_callback is not None:
            progress_callback(0, f"Forbereder {path}")
            progress_callback(50, f"Halvveis {path}")
        if "slow" in path:
            time.sleep(0.01)
        if progress_callback is not None:
            progress_callback(100, f"Ferdig {path}")
        return SaftLoadResult(
            file_path=path,
            header=None,
            dataframe=pd.DataFrame(),
            customers={},
            customer_sales=None,
            suppliers={},
            supplier_purchases=None,
            credit_notes=None,
            sales_ar_correlation=None,
            cost_vouchers=[],
            analysis_year=None,
            summary={},
            validation=validation,
        )

    monkeypatch.setattr("nordlys.saft.loader.load_saft_file", fake_load)

    progress_events = []
    files = ["slow.xml", "fast.xml", "medium.xml"]
    results = load_saft_files(
        files, progress_callback=lambda pct, msg: progress_events.append((pct, msg))
    )

    assert [result.file_path for result in results] == files
    assert progress_events
    percentages = [percent for percent, _ in progress_events]
    assert all(earlier <= later for earlier, later in zip(percentages, percentages[1:]))
    assert progress_events[-1] == (100, "Import fullført.")


def test_load_saft_files_keeps_successes_when_one_fails(monkeypatch):
    validation = SaftValidationResult(
        audit_file_version=None,
        version_family=None,
        schema_version=None,
        is_valid=None,
    )

    def fake_load(path: str, progress_callback=None, file_size=None):
        if "bad" in path:
            raise RuntimeError("Kunne ikke lese fil")
        return SaftLoadResult(
            file_path=path,
            header=None,
            dataframe=pd.DataFrame(),
            customers={},
            customer_sales=None,
            suppliers={},
            supplier_purchases=None,
            credit_notes=None,
            sales_ar_correlation=None,
            cost_vouchers=[],
            analysis_year=None,
            summary={},
            validation=validation,
        )

    progress_events = []
    monkeypatch.setattr("nordlys.saft.loader.load_saft_file", fake_load)

    results = load_saft_files(
        ["good.xml", "bad.xml"],
        progress_callback=lambda pct, msg: progress_events.append((pct, msg)),
    )

    assert [result.file_path for result in results] == ["good.xml"]
    assert progress_events
    assert progress_events[-1] == (100, "Import fullført med feil i: bad.xml.")


def test_load_saft_files_raises_on_partial_failure_without_progress(monkeypatch):
    validation = SaftValidationResult(
        audit_file_version=None,
        version_family=None,
        schema_version=None,
        is_valid=None,
    )

    def fake_load(path: str, progress_callback=None, file_size=None):
        if "bad" in path:
            raise RuntimeError("Kunne ikke lese fil")
        return SaftLoadResult(
            file_path=path,
            header=None,
            dataframe=pd.DataFrame(),
            customers={},
            customer_sales=None,
            suppliers={},
            supplier_purchases=None,
            credit_notes=None,
            sales_ar_correlation=None,
            cost_vouchers=[],
            analysis_year=None,
            summary={},
            validation=validation,
        )

    monkeypatch.setattr("nordlys.saft.loader.load_saft_file", fake_load)

    with pytest.raises(RuntimeError):
        load_saft_files(["good.xml", "bad.xml"])


def test_suggest_max_workers_limits_large_imports(monkeypatch, tmp_path):
    from nordlys.saft import loader

    files = []
    for idx in range(5):
        path = tmp_path / f"file_{idx}.xml"
        path.write_bytes(b"x" * (idx + 1))
        files.append(str(path))

    monkeypatch.setattr(loader, "HEAVY_SAFT_FILE_BYTES", 1)
    monkeypatch.setattr(loader, "HEAVY_SAFT_TOTAL_BYTES", 5)

    limited = loader._suggest_max_workers(files, cpu_limit=8)
    assert limited == loader.HEAVY_SAFT_MAX_WORKERS

    # Når datasettet er lite skal ikke heuristikken begrense.
    unrestricted = loader._suggest_max_workers(files[:2], cpu_limit=2)
    assert unrestricted == 2


def test_extract_cost_vouchers_includes_asset_transactions():
    root = build_sample_root()
    namespace = root.tag.split("}")[0].lstrip("{")
    ns = {"n1": namespace}

    journal = root.find(".//{urn:StandardAuditFile-Taxation-Financial:NO}Journal")
    assert journal is not None

    transaction = ET.SubElement(
        journal, "{urn:StandardAuditFile-Taxation-Financial:NO}Transaction"
    )
    ET.SubElement(
        transaction, "{urn:StandardAuditFile-Taxation-Financial:NO}TransactionDate"
    ).text = "2023-08-15"

    asset_line = ET.SubElement(
        transaction, "{urn:StandardAuditFile-Taxation-Financial:NO}Line"
    )
    ET.SubElement(
        asset_line, "{urn:StandardAuditFile-Taxation-Financial:NO}AccountID"
    ).text = "1200"
    ET.SubElement(
        asset_line, "{urn:StandardAuditFile-Taxation-Financial:NO}DebitAmount"
    ).text = "75000"

    credit_line = ET.SubElement(
        transaction, "{urn:StandardAuditFile-Taxation-Financial:NO}Line"
    )
    ET.SubElement(
        credit_line, "{urn:StandardAuditFile-Taxation-Financial:NO}AccountID"
    ).text = "2400"
    ET.SubElement(
        credit_line, "{urn:StandardAuditFile-Taxation-Financial:NO}CreditAmount"
    ).text = "75000"
    ET.SubElement(
        credit_line, "{urn:StandardAuditFile-Taxation-Financial:NO}SupplierID"
    ).text = "S1"

    vouchers = extract_cost_vouchers(root, ns, year=2023)

    assert any(
        any(line.account.startswith("12") for line in voucher.lines)
        for voucher in vouchers
    )
