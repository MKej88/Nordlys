"""Oppslagstabeller for kunde- og leverandørnavn."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Optional

from .xml_helpers import _clean_text, _find, _findall, _local_name, NamespaceMap

__all__ = [
    "build_parent_map",
    "build_customer_name_map",
    "build_supplier_name_map",
]


def build_parent_map(root: ET.Element) -> Dict[ET.Element, Optional[ET.Element]]:
    """Bygger et oppslag fra barn til forelder for hele SAF-T-treet."""

    parent_map: Dict[ET.Element, Optional[ET.Element]] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent
    return parent_map


def build_customer_name_map(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> Dict[str, str]:
    """Bygger oppslag fra CustomerID til navn med fallback når masterfil mangler."""

    names: Dict[str, str] = {}
    for customer in _findall(root, ".//n1:MasterFiles/n1:Customer", ns):
        cid_element = _find(customer, "n1:CustomerID", ns)
        cid = _clean_text(cid_element.text if cid_element is not None else None)
        name_element = _find(customer, "n1:Name", ns)
        if name_element is None:
            name_element = _find(customer, "n1:CompanyName", ns)
        if name_element is None:
            contact = _find(customer, "n1:Contact", ns)
            if contact is not None:
                name_element = _find(contact, "n1:Name", ns)
                if name_element is None:
                    name_element = _find(contact, "n1:ContactName", ns)
        name = _clean_text(name_element.text if name_element is not None else None)
        if cid and name and cid not in names:
            names[cid] = name

    lookup_map = parent_map if parent_map is not None else build_parent_map(root)

    def lookup_name(node: ET.Element) -> Optional[str]:
        current: Optional[ET.Element] = node
        visited = set()
        while current is not None and current not in visited:
            visited.add(current)
            tag_name = _local_name(current.tag).lower()
            if tag_name == "name":
                text = _clean_text(current.text)
                if text:
                    return text
            for child in current:
                if _local_name(child.tag).lower() == "name":
                    text = _clean_text(child.text)
                    if text:
                        return text
            current = lookup_map.get(current)
        return None

    for element in root.iter():
        if _local_name(element.tag) != "CustomerID":
            continue
        cid = _clean_text(element.text)
        if not cid or cid in names:
            continue
        name = lookup_name(element)
        if name:
            names[cid] = name

    return names


def build_supplier_name_map(
    root: ET.Element,
    ns: NamespaceMap,
    *,
    parent_map: Optional[Dict[ET.Element, Optional[ET.Element]]] = None,
) -> Dict[str, str]:
    """Bygger oppslag fra SupplierID til navn med fallback når masterfil mangler."""

    names: Dict[str, str] = {}
    for supplier in _findall(root, ".//n1:MasterFiles/n1:Supplier", ns):
        sid_element = _find(supplier, "n1:SupplierID", ns)
        sid = _clean_text(sid_element.text if sid_element is not None else None)
        name_element: Optional[ET.Element] = None
        for path in ("n1:SupplierName", "n1:Name", "n1:CompanyName"):
            candidate = _find(supplier, path, ns)
            if candidate is not None:
                name_element = candidate
                break
        if name_element is None:
            contact = _find(supplier, "n1:Contact", ns)
            if contact is not None:
                for path in ("n1:Name", "n1:ContactName"):
                    candidate = _find(contact, path, ns)
                    if candidate is not None:
                        name_element = candidate
                        break
        name = _clean_text(name_element.text if name_element is not None else None)
        if sid and name and sid not in names:
            names[sid] = name

    lookup_map = parent_map if parent_map is not None else build_parent_map(root)

    def lookup_name(node: ET.Element) -> Optional[str]:
        current: Optional[ET.Element] = node
        visited = set()
        while current is not None and current not in visited:
            visited.add(current)
            tag_name = _local_name(current.tag).lower()
            if tag_name in {"name", "suppliername"}:
                text = _clean_text(current.text)
                if text:
                    return text
            for child in current:
                child_tag = _local_name(child.tag).lower()
                if child_tag in {"name", "suppliername"}:
                    text = _clean_text(child.text)
                    if text:
                        return text
            current = lookup_map.get(current)
        return None

    for element in root.iter():
        if _local_name(element.tag) != "SupplierID":
            continue
        sid = _clean_text(element.text)
        if not sid or sid in names:
            continue
        name = lookup_name(element)
        if name:
            names[sid] = name

    return names
