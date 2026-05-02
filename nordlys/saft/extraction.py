"""Samlet ekstraksjon av grunnstrukturer fra SAF-T XML."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Dict, List, Optional, overload
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
    transactions: Sequence[ET.Element]
    parent_map: Dict[ET.Element, Optional[ET.Element]]
    customers: Dict[str, CustomerInfo]
    suppliers: Dict[str, SupplierInfo]


class _JournalTransactionSequence(Sequence[ET.Element]):
    """Sekvensvisning over transaksjoner uten å materialisere alle elementer."""

    def __init__(self, journals: Sequence[ET.Element], ns: NamespaceMap) -> None:
        self._journals = tuple(journals)
        self._ns = ns

    def __iter__(self) -> Iterator[ET.Element]:
        for journal in self._journals:
            yield from _findall(journal, "n1:Transaction", self._ns)

    def __len__(self) -> int:
        total = 0
        for journal in self._journals:
            total += len(self._transactions_for_journal(journal))
        return total

    @overload
    def __getitem__(self, index: int) -> ET.Element: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[ET.Element]: ...

    def __getitem__(self, index: int | slice) -> ET.Element | Sequence[ET.Element]:
        if isinstance(index, slice):
            return list(self)[index]
        return self._get_by_index(index)

    def _get_by_index(self, index: int) -> ET.Element:
        if index < 0:
            index += len(self)
        if index < 0:
            raise IndexError(index)
        offset = 0
        for journal in self._journals:
            transactions = self._transactions_for_journal(journal)
            next_offset = offset + len(transactions)
            if index < next_offset:
                return transactions[index - offset]
            offset = next_offset
        raise IndexError(index)

    def _transactions_for_journal(self, journal: ET.Element) -> List[ET.Element]:
        return list(_findall(journal, "n1:Transaction", self._ns))


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

    journals: List[ET.Element] = []
    entries = _find(root, "n1:GeneralLedgerEntries", ns)
    if entries is not None:
        journals = list(_findall(entries, "n1:Journal", ns))

    return SaftExtractionBundle(
        account_elements=account_elements,
        customer_elements=customer_elements,
        supplier_elements=supplier_elements,
        transactions=_JournalTransactionSequence(journals, ns),
        parent_map=build_parent_map(root),
        customers=parse_customers_from_elements(customer_elements),
        suppliers=parse_suppliers_from_elements(supplier_elements),
    )
