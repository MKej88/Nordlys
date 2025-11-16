from __future__ import annotations

import xml.etree.ElementTree as ET

from nordlys.saft.reporting import _is_correction_transaction
from nordlys.saft.xml_helpers import NamespaceMap

SAFT_NAMESPACE = "urn:StandardAuditFile-Taxation-Financial:NO"


def _build_transaction(fragment: str) -> ET.Element:
    xml = f"""
    <Transaction xmlns=\"{SAFT_NAMESPACE}\">
      {fragment}
      <Description>Eksempel</Description>
    </Transaction>
    """
    return ET.fromstring(xml)


def _build_namespace() -> NamespaceMap:
    return {"n1": SAFT_NAMESPACE}


def test_is_correction_transaction_detects_voucher_description() -> None:
    transaction = _build_transaction("<VoucherDescription>Annet</VoucherDescription>")
    assert _is_correction_transaction(transaction, _build_namespace())


def test_is_correction_transaction_ignores_regular_voucher() -> None:
    transaction = _build_transaction("<VoucherDescription>Ordinær</VoucherDescription>")
    assert not _is_correction_transaction(transaction, _build_namespace())
