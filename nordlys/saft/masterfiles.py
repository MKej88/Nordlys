"""Hjelpefunksjoner for å hente kunde- og leverandørdata fra SAF-T."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict

from ..constants import NS
from ..helpers import text_or_none

__all__ = [
    "CustomerInfo",
    "SupplierInfo",
    "parse_customers",
    "parse_suppliers",
]


@dataclass
class CustomerInfo:
    """Kundedata hentet fra masterfilen."""

    customer_id: str
    customer_number: str
    name: str


@dataclass
class SupplierInfo:
    """Leverandørdata hentet fra masterfilen."""

    supplier_id: str
    supplier_number: str
    name: str


def parse_customers(root: ET.Element) -> Dict[str, CustomerInfo]:
    """Returnerer oppslag over kunder med kundenummer og navn."""

    customers: Dict[str, CustomerInfo] = {}
    for element in root.findall(".//n1:MasterFiles/n1:Customer", NS):
        cid = text_or_none(element.find("n1:CustomerID", NS))
        if not cid:
            continue
        number = (
            text_or_none(element.find("n1:CustomerNumber", NS))
            or text_or_none(element.find("n1:AccountID", NS))
            or text_or_none(element.find("n1:SupplierAccountID", NS))
            or cid
        )
        raw_name = (
            text_or_none(element.find("n1:Name", NS))
            or text_or_none(element.find("n1:CompanyName", NS))
            or text_or_none(element.find("n1:Contact/n1:Name", NS))
            or text_or_none(element.find("n1:Contact/n1:ContactName", NS))
            or ""
        )
        name = raw_name.strip()
        customers[cid] = CustomerInfo(
            customer_id=cid,
            customer_number=number or cid,
            name=name,
        )
    return customers


def parse_suppliers(root: ET.Element) -> Dict[str, SupplierInfo]:
    """Returnerer oppslag over leverandører med nummer og navn."""

    suppliers: Dict[str, SupplierInfo] = {}
    for element in root.findall(".//n1:MasterFiles/n1:Supplier", NS):
        sid = text_or_none(element.find("n1:SupplierID", NS))
        if not sid:
            continue
        number = (
            text_or_none(element.find("n1:SupplierAccountID", NS))
            or text_or_none(element.find("n1:SupplierTaxID", NS))
            or text_or_none(element.find("n1:AccountID", NS))
            or sid
        )
        raw_name = (
            text_or_none(element.find("n1:SupplierName", NS))
            or text_or_none(element.find("n1:Name", NS))
            or text_or_none(element.find("n1:CompanyName", NS))
            or text_or_none(element.find("n1:Contact/n1:Name", NS))
            or text_or_none(element.find("n1:Contact/n1:ContactName", NS))
            or ""
        )
        name = raw_name.strip()
        suppliers[sid] = SupplierInfo(
            supplier_id=sid,
            supplier_number=number or sid,
            name=name,
        )
    return suppliers
