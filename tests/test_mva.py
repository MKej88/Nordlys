from datetime import date

from nordlys.regnskap.mva import find_vat_deviations
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
