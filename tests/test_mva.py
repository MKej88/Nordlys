from datetime import date

from nordlys.regnskap.mva import find_vat_deviations, summarize_vat_deviations
from nordlys.saft.models import CostVoucher, VoucherLine


def _voucher(
    *,
    tx_id: str,
    doc: str,
    tx_date: date,
    supplier: str,
    vat_code: str | None,
    account: str = "6320",
) -> CostVoucher:
    return CostVoucher(
        transaction_id=tx_id,
        document_number=doc,
        transaction_date=tx_date,
        supplier_id=f"LEV-{supplier}",
        supplier_name=supplier,
        description=f"Bilag {doc}",
        amount=1000.0,
        lines=[
            VoucherLine(
                account=account,
                account_name="Leie lokaler",
                description="Kostnadslinje",
                vat_code=vat_code,
                debit=1000.0,
                credit=0.0,
            )
        ],
    )


def test_find_vat_deviations_detects_single_outlier() -> None:
    vouchers = [
        _voucher(
            tx_id="1",
            doc="B1",
            tx_date=date(2025, 1, 10),
            supplier="Nord AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="2",
            doc="B2",
            tx_date=date(2025, 1, 11),
            supplier="Vest AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="3",
            doc="B3",
            tx_date=date(2025, 1, 12),
            supplier="Sor AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="4",
            doc="B4",
            tx_date=date(2025, 1, 13),
            supplier="Ost AS",
            vat_code="2",
        ),
    ]

    deviations = find_vat_deviations(vouchers)

    assert len(deviations) == 1
    deviation = deviations[0]
    assert deviation.account == "6320"
    assert deviation.expected_vat_code == "1"
    assert deviation.observed_vat_code == "2"
    assert deviation.voucher_number == "B4"
    assert deviation.expected_count == 3
    assert deviation.total_count == 4


def test_find_vat_deviations_skips_account_without_clear_dominant_code() -> None:
    vouchers = [
        _voucher(
            tx_id="1",
            doc="B1",
            tx_date=date(2025, 2, 10),
            supplier="Nord AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="2",
            doc="B2",
            tx_date=date(2025, 2, 11),
            supplier="Vest AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="3",
            doc="B3",
            tx_date=date(2025, 2, 12),
            supplier="Sor AS",
            vat_code="2",
        ),
        _voucher(
            tx_id="4",
            doc="B4",
            tx_date=date(2025, 2, 13),
            supplier="Ost AS",
            vat_code="2",
        ),
    ]

    deviations = find_vat_deviations(vouchers)

    assert deviations == []


def test_find_vat_deviations_aggregates_multiple_lines_per_voucher_account() -> None:
    vouchers = [
        _voucher(
            tx_id="1",
            doc="B1",
            tx_date=date(2025, 3, 1),
            supplier="Nord AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="2",
            doc="B2",
            tx_date=date(2025, 3, 2),
            supplier="Vest AS",
            vat_code="1",
        ),
        CostVoucher(
            transaction_id="3",
            document_number="B3",
            transaction_date=date(2025, 3, 3),
            supplier_id="LEV-Sor",
            supplier_name="Sor AS",
            description="Bilag B3",
            amount=2000.0,
            lines=[
                VoucherLine(
                    account="6320",
                    account_name="Leie lokaler",
                    description="Linje 1",
                    vat_code="1",
                    debit=1000.0,
                    credit=0.0,
                ),
                VoucherLine(
                    account="6320",
                    account_name="Leie lokaler",
                    description="Linje 2",
                    vat_code="2",
                    debit=1000.0,
                    credit=0.0,
                ),
            ],
        ),
    ]

    deviations = find_vat_deviations(vouchers)

    assert len(deviations) == 1
    deviation = deviations[0]
    assert deviation.voucher_number == "B3"
    assert deviation.observed_vat_code == "1 + 2"


def test_find_vat_deviations_treats_combined_and_split_vat_codes_equally() -> None:
    vouchers = [
        _voucher(
            tx_id="1",
            doc="B1",
            tx_date=date(2025, 3, 10),
            supplier="Nord AS",
            vat_code="1",
        ),
        _voucher(
            tx_id="2",
            doc="B2",
            tx_date=date(2025, 3, 11),
            supplier="Vest AS",
            vat_code="2",
        ),
        CostVoucher(
            transaction_id="3",
            document_number="B3",
            transaction_date=date(2025, 3, 12),
            supplier_id="LEV-Sor",
            supplier_name="Sor AS",
            description="Bilag B3",
            amount=2000.0,
            lines=[
                VoucherLine(
                    account="6320",
                    account_name="Leie lokaler",
                    description="Linje 1",
                    vat_code="1, 2",
                    debit=1000.0,
                    credit=0.0,
                )
            ],
        ),
    ]

    deviations = find_vat_deviations(vouchers)

    assert deviations == []


def test_summarize_vat_deviations_groups_per_account() -> None:
    vouchers = [
        _voucher(
            tx_id="1",
            doc="B1",
            tx_date=date(2025, 4, 1),
            supplier="Nord AS",
            vat_code="1",
            account="6320",
        ),
        _voucher(
            tx_id="2",
            doc="B2",
            tx_date=date(2025, 4, 2),
            supplier="Vest AS",
            vat_code="1",
            account="6320",
        ),
        _voucher(
            tx_id="3",
            doc="B3",
            tx_date=date(2025, 4, 3),
            supplier="Sor AS",
            vat_code="2",
            account="6320",
        ),
        _voucher(
            tx_id="4",
            doc="B4",
            tx_date=date(2025, 4, 4),
            supplier="Ost AS",
            vat_code="3",
            account="6340",
        ),
        _voucher(
            tx_id="5",
            doc="B5",
            tx_date=date(2025, 4, 5),
            supplier="Midt AS",
            vat_code="3",
            account="6340",
        ),
        _voucher(
            tx_id="6",
            doc="B6",
            tx_date=date(2025, 4, 6),
            supplier="Syd AS",
            vat_code="4",
            account="6340",
        ),
    ]

    deviations = find_vat_deviations(vouchers)
    summaries = summarize_vat_deviations(deviations)

    assert len(summaries) == 2
    first = summaries[0]
    second = summaries[1]

    assert first.account == "6320"
    assert first.deviation_count == 1
    assert first.deviation_amount == 1000.0
    assert first.expected_vat_code == "1"

    assert second.account == "6340"
    assert second.deviation_count == 1
    assert second.deviation_amount == 1000.0
    assert second.expected_vat_code == "3"


def test_find_vat_deviations_uses_account_line_amount_not_voucher_total() -> None:
    vouchers = [
        CostVoucher(
            transaction_id="1",
            document_number="B1",
            transaction_date=date(2025, 5, 1),
            supplier_id="LEV-Nord",
            supplier_name="Nord AS",
            description="Bilag B1",
            amount=0.0,
            lines=[
                VoucherLine(
                    account="3000",
                    account_name="Salg",
                    description="Salg",
                    vat_code="1",
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
        ),
        CostVoucher(
            transaction_id="2",
            document_number="B2",
            transaction_date=date(2025, 5, 2),
            supplier_id="LEV-Vest",
            supplier_name="Vest AS",
            description="Bilag B2",
            amount=0.0,
            lines=[
                VoucherLine(
                    account="3000",
                    account_name="Salg",
                    description="Salg",
                    vat_code="1",
                    debit=0.0,
                    credit=1200.0,
                ),
                VoucherLine(
                    account="1500",
                    account_name="Kundefordringer",
                    description="Motpost",
                    vat_code=None,
                    debit=1200.0,
                    credit=0.0,
                ),
            ],
        ),
        CostVoucher(
            transaction_id="3",
            document_number="B3",
            transaction_date=date(2025, 5, 3),
            supplier_id="LEV-Sor",
            supplier_name="Sor AS",
            description="Bilag B3",
            amount=0.0,
            lines=[
                VoucherLine(
                    account="3000",
                    account_name="Salg",
                    description="Salg",
                    vat_code="2",
                    debit=0.0,
                    credit=900.0,
                ),
                VoucherLine(
                    account="1500",
                    account_name="Kundefordringer",
                    description="Motpost",
                    vat_code=None,
                    debit=900.0,
                    credit=0.0,
                ),
            ],
        ),
    ]

    deviations = find_vat_deviations(vouchers)
    summaries = summarize_vat_deviations(deviations)

    assert len(deviations) == 1
    sales_deviation = next(item for item in deviations if item.account == "3000")
    assert sales_deviation.voucher_amount == 900.0

    sales_summary = next(item for item in summaries if item.account == "3000")
    assert sales_summary.deviation_amount == 900.0
