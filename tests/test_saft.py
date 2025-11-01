from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import pandas as pd

from nordlys.saft import (
    extract_ar_from_gl,
    extract_sales_taxbase_by_customer,
    ns4102_summary_from_tb,
    parse_customers,
    parse_saldobalanse,
    parse_saft_header,
    validate_saft_against_xsd,
)
from nordlys.utils import format_currency, format_difference
from nordlys.ui.formatting import format_orgnr, format_period


def build_sample_root() -> ET.Element:
    xml = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <Company>
          <Name>Test AS</Name>
          <RegistrationNumber>999999999</RegistrationNumber>
        </Company>
        <SelectionCriteria>
          <PeriodStart>01</PeriodStart>
          <PeriodEnd>12</PeriodEnd>
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
        </GeneralLedgerAccounts>
        <Customer>
          <CustomerID>K1</CustomerID>
          <Name>Kunde 1</Name>
        </Customer>
      </MasterFiles>
      <SourceDocuments>
        <SalesInvoices>
          <Invoice>
            <CustomerID>K1</CustomerID>
            <DocumentTotals>
              <NetTotal>1000</NetTotal>
            </DocumentTotals>
          </Invoice>
        </SalesInvoices>
      </SourceDocuments>
      <GeneralLedgerEntries>
        <Journal>
          <Transaction>
            <Line>
              <AccountID>1500</AccountID>
              <DebitAmount>1000</DebitAmount>
              <CreditAmount>0</CreditAmount>
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
    assert customers == {"K1": "Kunde 1"}


def test_parse_saldobalanse_and_summary():
    root = build_sample_root()
    df = parse_saldobalanse(root)
    assert set(['Konto', 'UB Debet', 'UB Kredit']).issubset(df.columns)
    summary = ns4102_summary_from_tb(df)
    # Salg 1000 -> driftsinntekter, varekost 600 -> varekostnad
    assert summary['driftsinntekter'] == 1000
    assert summary['varekostnad'] == 600
    assert summary['ebitda'] == 400


def test_extract_sales_and_ar():
    root = build_sample_root()
    sales = extract_sales_taxbase_by_customer(root)
    assert sales.loc[0, 'CustomerID'] == 'K1'
    assert sales.loc[0, 'OmsetningEksMva'] == 1000
    ar = extract_ar_from_gl(root)
    assert ar.loc[0, 'AR_Debit'] == 1000
    assert ar.loc[0, 'AR_Netto'] == 1000


def test_format_helpers():
    assert format_currency(1234.5) == '1 234 kr'
    assert format_difference(2000, 1500) == '500 kr'


def test_dashboard_format_helpers():
    assert format_orgnr('999999999') == '999 999 999'
    assert format_orgnr('') == '–'
    assert format_period('2023', '01', '12') == '2023 · Perioder 01 – 12'
    assert format_period(None, '2023-01-01', '2023-12-31') == 'Perioder 01.01.2023 – 31.12.2023'


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
