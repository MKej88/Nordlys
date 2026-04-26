"""Samlet ekstraksjon av grunnstrukturer fra SAF-T XML."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

from .masterfiles import CustomerInfo, SupplierInfo, parse_customers_from_elements
from .masterfiles import parse_suppliers_from_elements
from .name_lookup import build_parent_map
from .xml_helpers import NamespaceMap, _find, _findall


@dataclass(frozen=True)
class SaftExtractionBundle:
    """Mellomresultater som kan deles mellom analysefunksjoner."""

    account_elements: List[ET.Element]
    customer_elements: List[ET.Element]
    supplier_elements: List[ET.Element]
    transactions: List[ET.Element]
    parent_map: Dict[ET.Element, Optional[ET.Element]]
    customers: Dict[str, CustomerInfo]
    suppliers: Dict[str, SupplierInfo]


def extract_saft_structures(root: ET.Element, ns: NamespaceMap) -> SaftExtractionBundle:
    """Ekstraherer konti, kunder, leverandører og transaksjoner i ett pass."""

    master_files = _find(root, "n1:MasterFiles", ns)
    account_elements: List[ET.Element] = []
    customer_elements: List[ET.Element] = []
    supplier_elements: List[ET.Element] = []

    if master_files is not None:
        accounts_root = _find(master_files, "n1:GeneralLedgerAccounts", ns)
        if accounts_root is not None:
            account_elements = list(_findall(accounts_root, "n1:Account", ns))
        customer_elements = list(_findall(master_files, "n1:Customer", ns))
        supplier_elements = list(_findall(master_files, "n1:Supplier", ns))

    transactions: List[ET.Element] = []
    entries = _find(root, "n1:GeneralLedgerEntries", ns)
    if entries is not None:
        for journal in _findall(entries, "n1:Journal", ns):
            transactions.extend(_findall(journal, "n1:Transaction", ns))

    return SaftExtractionBundle(
        account_elements=account_elements,
        customer_elements=customer_elements,
        supplier_elements=supplier_elements,
        transactions=transactions,
        parent_map=build_parent_map(root),
        customers=parse_customers_from_elements(customer_elements),
        suppliers=parse_suppliers_from_elements(supplier_elements),
    )
