from datetime import date

import pandas as pd

from nordlys.regnskap.driftsmidler import (
    AssetAccession,
    AssetAccessionSummary,
    AssetMovement,
    CapitalizationCandidate,
    find_asset_accessions,
    find_capitalization_candidates,
    find_possible_disposals,
    summarize_asset_accessions_by_account,
)
from nordlys.saft.models import CostVoucher, VoucherLine


def test_find_asset_accessions_collects_debits_on_asset_accounts():
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="Maskinkjøp",
            amount=50_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name=None,
                    description="Ny maskin",
                    vat_code=None,
                    debit=50_000,
                    credit=0,
                ),
                VoucherLine(
                    account="4000",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=0,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="2",
            document_number="A2",
            transaction_date=None,
            supplier_id="S2",
            supplier_name="Andre",
            description=None,
            amount=10_000,
            lines=[
                VoucherLine(
                    account="1200",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=0,
                    credit=10_000,
                ),
            ],
        ),
    ]

    additions = find_asset_accessions(vouchers)

    assert additions == [
        AssetAccession(
            date=None,
            supplier="Leverandør",
            document="A1",
            account="1100",
            account_name=None,
            amount=50_000,
            description="Ny maskin",
            comment=None,
        )
    ]


def test_find_asset_accessions_skips_reversals_with_same_amount():
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="Maskinkjøp",
            amount=50_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name=None,
                    description="Ny maskin",
                    vat_code=None,
                    debit=50_000,
                    credit=0,
                ),
                VoucherLine(
                    account="1100",
                    account_name=None,
                    description="Tilbakeført",
                    vat_code=None,
                    debit=0,
                    credit=50_000,
                ),
            ],
        )
    ]

    additions = find_asset_accessions(vouchers)

    assert additions == []


def test_find_asset_accessions_skips_reversals_across_vouchers():
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="Maskinkjøp",
            amount=50_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name="Maskin",
                    description="Ny maskin",
                    vat_code=None,
                    debit=50_000,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="2",
            document_number="A2",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="Reversering",
            amount=50_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name="Maskin",
                    description="Reversering",
                    vat_code=None,
                    debit=0,
                    credit=50_000,
                ),
            ],
        ),
    ]

    additions = find_asset_accessions(vouchers)

    assert additions == []


def test_find_asset_accessions_reduces_partial_reversals():
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="Maskinkjøp",
            amount=50_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name="Maskin",
                    description="Ny maskin",
                    vat_code=None,
                    debit=50_000,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="2",
            document_number="A2",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="Reversering",
            amount=30_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name="Maskin",
                    description="Delvis reversering",
                    vat_code=None,
                    debit=0,
                    credit=30_000,
                ),
            ],
        ),
    ]

    additions = find_asset_accessions(vouchers)

    assert additions == [
        AssetAccession(
            date=None,
            supplier="Leverandør",
            document="A1",
            account="1100",
            account_name="Maskin",
            amount=20_000.0,
            description="Ny maskin",
            comment=None,
        )
    ]


def test_find_asset_accessions_sorts_by_account_and_date():
    vouchers = [
        CostVoucher(
            transaction_id="2",
            document_number="A2",
            transaction_date=date(2024, 3, 20),
            supplier_id="S2",
            supplier_name="B leverandør",
            description=None,
            amount=10_000,
            lines=[
                VoucherLine(
                    account="1200",
                    account_name="Bil",
                    description=None,
                    vat_code=None,
                    debit=10_000,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=date(2024, 4, 1),
            supplier_id="S1",
            supplier_name="A leverandør",
            description=None,
            amount=5_000,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name="Maskin",
                    description=None,
                    vat_code=None,
                    debit=5_000,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="3",
            document_number="A3",
            transaction_date=date(2024, 3, 25),
            supplier_id="S3",
            supplier_name="C leverandør",
            description=None,
            amount=7_500,
            lines=[
                VoucherLine(
                    account="1100",
                    account_name="Maskin",
                    description=None,
                    vat_code=None,
                    debit=7_500,
                    credit=0,
                ),
            ],
        ),
    ]

    additions = find_asset_accessions(vouchers)

    assert additions == [
        AssetAccession(
            date=date(2024, 3, 25),
            supplier="C leverandør",
            document="A3",
            account="1100",
            account_name="Maskin",
            amount=7_500,
            description=None,
            comment=None,
        ),
        AssetAccession(
            date=date(2024, 4, 1),
            supplier="A leverandør",
            document="A1",
            account="1100",
            account_name="Maskin",
            amount=5_000,
            description=None,
            comment=None,
        ),
        AssetAccession(
            date=date(2024, 3, 20),
            supplier="B leverandør",
            document="A2",
            account="1200",
            account_name="Bil",
            amount=10_000,
            description=None,
            comment=None,
        ),
    ]


def test_summarize_asset_accessions_by_account_groups_totals():
    accessions = [
        AssetAccession(
            date=None,
            supplier="Leverandør",
            document="A1",
            account="1100",
            account_name="Maskiner",
            amount=50_000,
            description="Ny maskin",
            comment=None,
        ),
        AssetAccession(
            date=None,
            supplier="Leverandør",
            document="A2",
            account="1100",
            account_name=None,
            amount=5_000,
            description="Tilleggsdel",
            comment=None,
        ),
        AssetAccession(
            date=None,
            supplier="Bilimport",
            document="B1",
            account="1200",
            account_name="Biler",
            amount=100_000,
            description="Ny bil",
            comment=None,
        ),
    ]

    summary = summarize_asset_accessions_by_account(accessions)

    assert summary == [
        AssetAccessionSummary(
            account="1100",
            account_name="Maskiner",
            total_amount=55_000,
        ),
        AssetAccessionSummary(
            account="1200",
            account_name="Biler",
            total_amount=100_000,
        ),
    ]


def test_find_possible_disposals_filters_accounts():
    df = pd.DataFrame(
        {
            "Konto": ["1100", "1200", "3000"],
            "Kontonavn": ["Maskiner", "Biler", "Salg"],
            "IB_netto": [100_000, 50_000, 10_000],
            "UB_netto": [150_000, 0, 11_000],
        }
    )

    disposals = find_possible_disposals(df)

    assert disposals == [
        AssetMovement(
            account="1200",
            name="Biler",
            opening_balance=50_000,
            closing_balance=0,
            change=-50_000,
        )
    ]


def test_find_capitalization_candidates_filters_by_account_and_threshold():
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="",
            amount=40_000,
            lines=[
                VoucherLine(
                    account="6500",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=40_000,
                    credit=0,
                ),
                VoucherLine(
                    account="3000",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=0,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="2",
            document_number="A2",
            transaction_date=None,
            supplier_id="S2",
            supplier_name="",
            description="",
            amount=20_000,
            lines=[
                VoucherLine(
                    account="6590",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=20_000,
                    credit=0,
                ),
            ],
        ),
    ]

    candidates = find_capitalization_candidates(vouchers, threshold=30_000)

    assert candidates == [
        CapitalizationCandidate(
            date=None,
            supplier="Leverandør",
            document="A1",
            account="6500",
            amount=40_000,
            description=None,
        )
    ]


def test_find_capitalization_candidates_aggregates_per_voucher():
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="A1",
            transaction_date=None,
            supplier_id="S1",
            supplier_name="Leverandør",
            description="",
            amount=40_000,
            lines=[
                VoucherLine(
                    account="6500",
                    account_name=None,
                    description="Del 1",
                    vat_code=None,
                    debit=20_000,
                    credit=0,
                ),
                VoucherLine(
                    account="6510",
                    account_name=None,
                    description="Del 2",
                    vat_code=None,
                    debit=20_000,
                    credit=0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="2",
            document_number="A2",
            transaction_date=None,
            supplier_id="S2",
            supplier_name="",
            description="",
            amount=25_000,
            lines=[
                VoucherLine(
                    account="6500",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=15_000,
                    credit=0,
                ),
                VoucherLine(
                    account="6500",
                    account_name=None,
                    description=None,
                    vat_code=None,
                    debit=10_000,
                    credit=0,
                ),
            ],
        ),
    ]

    candidates = find_capitalization_candidates(vouchers, threshold=30_000)

    assert candidates == [
        CapitalizationCandidate(
            date=None,
            supplier="Leverandør",
            document="A1",
            account="6500",
            amount=20_000,
            description="Del 1",
        ),
        CapitalizationCandidate(
            date=None,
            supplier="Leverandør",
            document="A1",
            account="6510",
            amount=20_000,
            description="Del 2",
        ),
    ]
