from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal

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
from nordlys.saft_customers import (
    build_customer_name_map,
    build_supplier_name_map,
    compute_customer_supplier_totals,
    compute_purchases_per_supplier,
    compute_sales_per_customer,
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
            <TransactionDate>2023-05-02</TransactionDate>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
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


def build_sales_dedup_root() -> ET.Element:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Customer>
          <CustomerID>K1</CustomerID>
          <CustomerNumber>1001</CustomerNumber>
          <Name>Kunde 1</Name>
        </Customer>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2023-01-05</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-1</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-01-07</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-1</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1100</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1100</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-01-07</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-1</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>800</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>800</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-01-10</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-1</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>1500</AccountID>
              <CreditAmount>1100</CreditAmount>
              <CustomerID>K1</CustomerID>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <DebitAmount>1100</DebitAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    return ET.fromstring(xml)


def build_purchase_dedup_root() -> ET.Element:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Supplier>
          <SupplierID>S1</SupplierID>
          <SupplierAccountID>5001</SupplierAccountID>
          <SupplierName>Leverandør 1</SupplierName>
        </Supplier>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2023-02-01</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>BILL-7</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>500</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>500</CreditAmount>
              <SupplierID>S1</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-02-03</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>BILL-7</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>650</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>650</CreditAmount>
              <SupplierID>S1</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-02-03</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>BILL-7</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>4000</AccountID>
              <DebitAmount>450</DebitAmount>
            </Line>
            <Line>
              <AccountID>2400</AccountID>
              <CreditAmount>450</CreditAmount>
              <SupplierID>S1</SupplierID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-02-05</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>BILL-7</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>2400</AccountID>
              <DebitAmount>650</DebitAmount>
              <SupplierID>S1</SupplierID>
            </Line>
            <Line>
              <AccountID>1920</AccountID>
              <CreditAmount>650</CreditAmount>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    return ET.fromstring(xml)


def build_far_apart_sales_root() -> ET.Element:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Customer>
          <CustomerID>K1</CustomerID>
          <CustomerNumber>1001</CustomerNumber>
          <Name>Kunde 1</Name>
        </Customer>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2023-01-02</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-2</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>900</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>900</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-03-15</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-2</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>800</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>800</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    return ET.fromstring(xml)


def build_mixed_window_sales_root() -> ET.Element:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <MasterFiles>
        <Customer>
          <CustomerID>K1</CustomerID>
          <CustomerNumber>1001</CustomerNumber>
          <Name>Kunde 1</Name>
        </Customer>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <TransactionDate>2023-01-01</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-5</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1000</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-01-03</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-5</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>1200</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1200</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
          <Transaction>
            <TransactionDate>2023-01-20</TransactionDate>
            <DocumentReference>
              <ReferenceNumber>INV-5</ReferenceNumber>
            </DocumentReference>
            <Line>
              <AccountID>3000</AccountID>
              <CreditAmount>900</CreditAmount>
            </Line>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>900</DebitAmount>
              <CustomerID>K1</CustomerID>
            </Line>
          </Transaction>
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """
    return ET.fromstring(xml)


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


def test_parse_saldobalanse_and_summary():
    root = build_sample_root()
    df = parse_saldobalanse(root)
    assert set(["Konto", "UB Debet", "UB Kredit"]).issubset(df.columns)
    summary = ns4102_summary_from_tb(df)
    # Salg 1000 -> driftsinntekter, varekost 600 -> varekostnad
    assert summary["driftsinntekter"] == 1000
    assert summary["varekostnad"] == 600
    assert summary["ebitda"] == 400


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

    assert len(entries) == 4
    assert entries[0]["account_id"] == "3000"
    assert entries[0]["kredit"] == Decimal("1000")
    total_debet = sum(item["debet"] for item in entries)
    total_kredit = sum(item["kredit"] for item in entries)
    assert total_debet == Decimal("1600")
    assert total_kredit == Decimal("1600")


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

    assert result["debet"] == Decimal("1600")
    assert result["kredit"] == Decimal("1600")
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


def test_compute_sales_per_customer_deduplicates_reference():
    root = build_sales_dedup_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Omsetning eks mva"] == pytest.approx(800.0)
    assert row["Transaksjoner"] == 1

    sales_df, purchases_df = compute_customer_supplier_totals(root, ns, year=2023)
    assert not sales_df.empty
    assert purchases_df.empty
    totals_row = sales_df.iloc[0]
    assert totals_row["Omsetning eks mva"] == pytest.approx(800.0)
    assert totals_row["Transaksjoner"] == 1


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


def test_compute_purchases_per_supplier_deduplicates_reference():
    root = build_purchase_dedup_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_purchases_per_supplier(root, ns, year=2023)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Innkjøp eks mva"] == pytest.approx(450.0)
    assert row["Transaksjoner"] == 1

    _, purchases_df = compute_customer_supplier_totals(root, ns, year=2023)
    assert not purchases_df.empty
    totals_row = purchases_df.iloc[0]
    assert totals_row["Innkjøp eks mva"] == pytest.approx(450.0)
    assert totals_row["Transaksjoner"] == 1


def test_compute_customer_supplier_totals_matches_individual():
    root = build_sample_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    expected_sales = compute_sales_per_customer(root, ns, year=2023)
    expected_purchases = compute_purchases_per_supplier(root, ns, year=2023)

    sales, purchases = compute_customer_supplier_totals(root, ns, year=2023)

    pd.testing.assert_frame_equal(sales, expected_sales)
    pd.testing.assert_frame_equal(purchases, expected_purchases)


def test_reference_dedup_keeps_far_apart_transactions():
    root = build_far_apart_sales_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Omsetning eks mva"] == pytest.approx(1700.0)
    assert row["Transaksjoner"] == 2


def test_reference_dedup_collapses_nearby_even_if_late_change_exists():
    root = build_mixed_window_sales_root()
    ns = {"n1": root.tag.split("}")[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Omsetning eks mva"] == pytest.approx(2100.0)
    assert row["Transaksjoner"] == 2


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
    assert format_currency(1234.5) == "1,235"
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
    monkeypatch.setattr(saft_module, "XMLSCHEMA_AVAILABLE", False, raising=False)
    monkeypatch.setattr(saft_module, "XMLSchema", None, raising=False)
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


def test_load_saft_files_parallel_progress(monkeypatch):
    validation = SaftValidationResult(
        audit_file_version=None,
        version_family=None,
        schema_version=None,
        is_valid=None,
    )

    def fake_load(path: str, progress_callback=None):
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
