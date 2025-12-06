from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from types import GeneratorType

import pytest

from nordlys.saft.reporting_utils import _ensure_date, _iter_transactions
from nordlys.saft.xml_helpers import parse_saft


def _build_root(
    tmp_path: Path, has_entries: bool
) -> tuple[ET.Element, dict[str, object]]:
    ns = "urn:StandardAuditFile-Taxation-Financial:NO"
    if has_entries:
        content = f"""
        <AuditFile xmlns=\"{ns}\">
            <GeneralLedgerEntries>
                <Journal>
                    <Transaction>
                        <TransactionID>1</TransactionID>
                    </Transaction>
                    <Transaction>
                        <TransactionID>2</TransactionID>
                    </Transaction>
                </Journal>
            </GeneralLedgerEntries>
        </AuditFile>
        """
    else:
        content = f'<AuditFile xmlns="{ns}"/>'
    xml_path = tmp_path / "sample.xml"
    xml_path.write_text(content, encoding="utf-8")
    tree, ns_map = parse_saft(xml_path)
    return tree.getroot(), ns_map


def test_iter_transactions_is_generator(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root, ns_map = _build_root(tmp_path_factory.mktemp("saft"), has_entries=True)

    transactions = _iter_transactions(root, ns_map)

    assert isinstance(transactions, GeneratorType)
    ids = [
        txn.findtext(".//{urn:StandardAuditFile-Taxation-Financial:NO}TransactionID")
        for txn in transactions
    ]
    assert ids == ["1", "2"]


def test_iter_transactions_empty(tmp_path_factory: pytest.TempPathFactory) -> None:
    root, ns_map = _build_root(tmp_path_factory.mktemp("saft_empty"), has_entries=False)

    transactions = list(_iter_transactions(root, ns_map))

    assert transactions == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2023, 1, 2, 12, 30), date(2023, 1, 2)),
        (date(2024, 2, 3), date(2024, 2, 3)),
        ("2025-03-04", date(2025, 3, 4)),
        ("ikke en dato", None),
    ],
)
def test_ensure_date_handles_common_inputs(value: object, expected: date | None) -> None:
    assert _ensure_date(value) == expected
