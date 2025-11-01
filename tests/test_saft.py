from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from nordlys.saft import (
    ns4102_summary_from_tb,
    parse_customers,
    parse_saldobalanse,
    parse_saft_header,
    parse_suppliers,
    validate_saft_against_xsd,
)
from nordlys.saft_customers import (
    build_customer_name_map,
    build_supplier_name_map,
    compute_purchases_per_supplier,
    compute_sales_per_customer,
    get_amount,
    get_tx_customer_id,
    get_tx_supplier_id,
    parse_saft,
    save_outputs,
)
from nordlys.utils import format_currency, format_difference


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
    assert set(['Konto', 'UB Debet', 'UB Kredit']).issubset(df.columns)
    summary = ns4102_summary_from_tb(df)
    # Salg 1000 -> driftsinntekter, varekost 600 -> varekostnad
    assert summary['driftsinntekter'] == 1000
    assert summary['varekostnad'] == 600
    assert summary['ebitda'] == 400


def test_parse_saft_detects_namespace(tmp_path):
    xml_path = tmp_path / 'simple.xml'
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        '  <Header><AuditFileVersion>1.0</AuditFileVersion></Header>'
        '</AuditFile>',
        encoding='utf-8',
    )
    tree, ns = parse_saft(xml_path)
    assert tree.getroot().tag.endswith('AuditFile')
    assert ns['n1'] == 'urn:StandardAuditFile-Taxation-Financial:NO'


def test_get_amount_handles_nested_amount():
    line_xml = """
    <Line xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <CreditAmount><Amount>123,45</Amount></CreditAmount>
      <DebitAmount>10</DebitAmount>
    </Line>
    """
    line = ET.fromstring(line_xml)
    ns = {'n1': 'urn:StandardAuditFile-Taxation-Financial:NO'}
    credit = get_amount(line, 'CreditAmount', ns)
    debit = get_amount(line, 'DebitAmount', ns)
    assert float(credit) == pytest.approx(123.45)
    assert float(debit) == pytest.approx(10.0)


def test_get_tx_customer_id_priority():
    ns = {'n1': 'urn:StandardAuditFile-Taxation-Financial:NO'}
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
    assert get_tx_customer_id(transaction_ar, ns) == 'AR-CUST'

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
    assert get_tx_customer_id(transaction_dim, ns) == 'DIM-CUST'

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
    assert get_tx_customer_id(transaction_analysis, ns) == 'ANAL-CUST'


def test_compute_sales_per_customer():
    root = build_sample_root()
    ns = {'n1': root.tag.split('}')[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    assert not df.empty
    row = df.iloc[0]
    assert row['Kundenr'] == 'K1'
    assert row['Kundenavn'] == 'Kunde 1'
    assert row['Omsetning eks mva'] == pytest.approx(1000.0)
    assert row['Transaksjoner'] == 1


def test_compute_sales_per_customer_date_filter():
    root = build_sample_root()
    ns = {'n1': root.tag.split('}')[0][1:]}
    df = compute_sales_per_customer(root, ns, date_from='2023-06-01', date_to='2023-12-31')
    assert df.empty


def test_parse_suppliers_and_compute_purchases():
    root = build_sample_root()
    suppliers = parse_suppliers(root)
    assert 'S1' in suppliers
    assert suppliers['S1'].supplier_number == '2001'

    ns = {'n1': root.tag.split('}')[0][1:]}
    df = compute_purchases_per_supplier(root, ns, year=2023)
    assert not df.empty
    row = df.iloc[0]
    assert row['Leverandørnr'] == 'S1'
    assert row['Leverandørnavn'] == 'Leverandør 1'
    assert row['Innkjøp eks mva'] == pytest.approx(600.0)
    assert row['Transaksjoner'] == 1


def test_compute_purchases_per_supplier_date_filter():
    root = build_sample_root()
    ns = {'n1': root.tag.split('}')[0][1:]}
    df = compute_purchases_per_supplier(root, ns, date_from='2023-07-01', date_to='2023-12-31')
    assert df.empty


def test_get_tx_supplier_id_priority():
    ns = {'n1': 'urn:StandardAuditFile-Taxation-Financial:NO'}
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
    assert get_tx_supplier_id(transaction_ap, ns) == 'AP-SUP'

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
    assert get_tx_supplier_id(transaction_dim, ns) == 'DIM-SUP'

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
    assert get_tx_supplier_id(transaction_analysis, ns) == 'ANAL-SUP'


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
    ns = {'n1': root.tag.split('}')[0][1:]}
    names = build_supplier_name_map(root, ns)
    assert names['SUP1'] == 'Fallback Leverandør'


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
    ns = {'n1': root.tag.split('}')[0][1:]}
    names = build_customer_name_map(root, ns)
    assert names['CU1'] == 'Fallback Navn'


def test_save_outputs(tmp_path):
    root = build_sample_root()
    ns = {'n1': root.tag.split('}')[0][1:]}
    df = compute_sales_per_customer(root, ns, year=2023)
    csv_path, xlsx_path = save_outputs(df, tmp_path, 2023)
    assert csv_path.exists()
    assert xlsx_path.exists()
    saved = pd.read_csv(csv_path)
    assert 'Kundenr' in saved.columns

def test_format_helpers():
    assert format_currency(1234.5) == '1,234'
    assert format_difference(2000, 1500) == '500'


def test_validate_saft_against_xsd_unknown_version(tmp_path):
    xml_path = tmp_path / 'saft_unknown.xml'
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        '  <Header>'
        '    <AuditFileVersion>9.9</AuditFileVersion>'
        '  </Header>'
        '</AuditFile>',
        encoding='utf-8',
    )
    result = validate_saft_against_xsd(xml_path, '9.9')
    assert result.is_valid is None
    assert result.version_family is None
    assert 'Ingen XSD' in (result.details or '')


def test_validate_saft_against_xsd_known_version(tmp_path):
    xml_path = tmp_path / 'saft_13.xml'
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        '  <Header>'
        '    <AuditFileVersion>1.30</AuditFileVersion>'
        '  </Header>'
        '</AuditFile>',
        encoding='utf-8',
    )
    result = validate_saft_against_xsd(xml_path)
    assert result.version_family == '1.3'
    assert result.schema_version == '1.30'
    saft_module = sys.modules['nordlys.saft']
    if saft_module.XMLSCHEMA_AVAILABLE:
        assert result.is_valid is False
    else:
        assert result.is_valid is None
        assert 'xmlschema' in (result.details or '').lower()


def test_validate_saft_against_xsd_without_dependency(monkeypatch, tmp_path):
    saft_module = sys.modules['nordlys.saft']
    monkeypatch.setattr(saft_module, 'XMLSCHEMA_AVAILABLE', False, raising=False)
    monkeypatch.setattr(saft_module, 'XMLSchema', None, raising=False)
    xml_path = tmp_path / 'saft_12.xml'
    xml_path.write_text(
        '<AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">'
        '  <Header>'
        '    <AuditFileVersion>1.20</AuditFileVersion>'
        '  </Header>'
        '</AuditFile>',
        encoding='utf-8',
    )
    result = validate_saft_against_xsd(xml_path)
    assert result.version_family == '1.2'
    assert result.is_valid is None
    assert 'xmlschema' in (result.details or '').lower()
