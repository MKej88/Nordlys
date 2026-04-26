from __future__ import annotations

import time
import xml.etree.ElementTree as ET

from nordlys.constants import NS
from nordlys.saft import parse_saft_header, parse_saldobalanse
from nordlys.saft.customer_analysis import build_customer_supplier_analysis
from nordlys.saft.extraction import extract_saft_structures
from nordlys.saft.reporting_customers import (
    analyze_bank_postings,
    analyze_receivable_postings,
)


def _build_saft_xml(transaction_count: int) -> str:
    transactions: list[str] = []
    for index in range(1, transaction_count + 1):
        day = (index % 28) + 1
        amount = 100 + (index % 11) * 10
        vat = int(amount * 0.25)
        gross = amount + vat
        transactions.append(
            f"""
            <Transaction>
              <TransactionID>T{index}</TransactionID>
              <TransactionDate>2023-03-{day:02d}</TransactionDate>
              <Line>
                <AccountID>3000</AccountID>
                <CreditAmount>{amount}</CreditAmount>
              </Line>
              <Line>
                <AccountID>2700</AccountID>
                <CreditAmount>{vat}</CreditAmount>
              </Line>
              <Line>
                <AccountID>1500</AccountID>
                <DebitAmount>{gross}</DebitAmount>
                <CustomerID>K1</CustomerID>
              </Line>
            </Transaction>
            """
        )

    joined_transactions = "".join(transactions)
    return f"""
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
      </Header>
      <MasterFiles>
        <GeneralLedgerAccounts>
          <Account>
            <AccountID>1500</AccountID>
            <AccountDescription>Kundefordringer</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>0</ClosingDebitBalance>
            <ClosingCreditBalance>0</ClosingCreditBalance>
          </Account>
          <Account>
            <AccountID>1900</AccountID>
            <AccountDescription>Bank</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>0</ClosingDebitBalance>
            <ClosingCreditBalance>0</ClosingCreditBalance>
          </Account>
          <Account>
            <AccountID>3000</AccountID>
            <AccountDescription>Salg</AccountDescription>
            <OpeningDebitBalance>0</OpeningDebitBalance>
            <OpeningCreditBalance>0</OpeningCreditBalance>
            <ClosingDebitBalance>0</ClosingDebitBalance>
            <ClosingCreditBalance>0</ClosingCreditBalance>
          </Account>
        </GeneralLedgerAccounts>
        <Customer>
          <CustomerID>K1</CustomerID>
          <CustomerNumber>1001</CustomerNumber>
          <Name>Kunde 1</Name>
        </Customer>
      </MasterFiles>
      <GeneralLedgerEntries>
        <Journal>
          {joined_transactions}
        </Journal>
      </GeneralLedgerEntries>
    </AuditFile>
    """


def _run_without_extraction(root: ET.Element) -> float:
    start = time.perf_counter()
    ns_map = dict(NS)
    header = parse_saft_header(root)
    trial_balance = parse_saldobalanse(root)
    analysis = build_customer_supplier_analysis(header, root, ns_map)
    analyze_receivable_postings(
        root,
        ns_map,
        date_from=analysis.analysis_start_date,
        date_to=analysis.analysis_end_date,
        year=analysis.analysis_year,
        trial_balance=trial_balance,
    )
    analyze_bank_postings(
        root,
        ns_map,
        date_from=analysis.analysis_start_date,
        date_to=analysis.analysis_end_date,
        year=analysis.analysis_year,
        trial_balance=trial_balance,
    )
    return time.perf_counter() - start


def _run_with_extraction(root: ET.Element) -> tuple[float, int]:
    start = time.perf_counter()
    ns_map = dict(NS)
    header = parse_saft_header(root)
    extracted = extract_saft_structures(root, ns_map)
    trial_balance = parse_saldobalanse(
        root, account_elements=extracted.account_elements
    )
    analysis = build_customer_supplier_analysis(
        header,
        root,
        ns_map,
        parent_map=extracted.parent_map,
        transactions=extracted.transactions,
    )
    analyze_receivable_postings(
        root,
        ns_map,
        date_from=analysis.analysis_start_date,
        date_to=analysis.analysis_end_date,
        year=analysis.analysis_year,
        trial_balance=trial_balance,
        transactions=extracted.transactions,
    )
    analyze_bank_postings(
        root,
        ns_map,
        date_from=analysis.analysis_start_date,
        date_to=analysis.analysis_end_date,
        year=analysis.analysis_year,
        trial_balance=trial_balance,
        transactions=extracted.transactions,
    )
    elapsed = time.perf_counter() - start
    return elapsed, len(extracted.transactions)


def test_extraction_pipeline_gjenbruker_data_og_har_forventet_ytelse():
    small_root = ET.fromstring(_build_saft_xml(transaction_count=15))
    medium_root = ET.fromstring(_build_saft_xml(transaction_count=250))

    _ = _run_without_extraction(small_root)
    _ = _run_with_extraction(ET.fromstring(_build_saft_xml(transaction_count=15)))

    baseline_medium = _run_without_extraction(medium_root)
    extracted_medium, tx_count = _run_with_extraction(
        ET.fromstring(_build_saft_xml(transaction_count=250))
    )

    assert tx_count == 250
    assert extracted_medium <= baseline_medium * 1.6
