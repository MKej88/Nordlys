import pandas as pd

from nordlys.regnskap.driftsmidler import (
    AssetAccession,
    AssetMovement,
    CapitalizationCandidate,
    find_asset_accessions,
    find_capitalization_candidates,
    find_possible_disposals,
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
            amount=50_000,
            description="Ny maskin",
        )
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
