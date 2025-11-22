"""Tester for XML-hjelpefunksjoner."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from nordlys.helpers.xml_helpers import findall_any_namespace


def test_finnes_med_standard_namespace() -> None:
    root = ET.Element("root")
    ET.SubElement(root, "{urn:test}Item")
    ET.SubElement(root, "Item")

    resultat = findall_any_namespace(root, "Item")

    assert len(resultat) == 2
    assert all(elem.tag.lower().endswith("item") for elem in resultat)


def test_finnes_med_prefiks_uten_braces() -> None:
    root = ET.Element("root")
    ET.SubElement(root, "abc:Item")
    ET.SubElement(root, "def:item")

    resultat = findall_any_namespace(root, "item")

    assert len(resultat) == 2
    assert {elem.tag for elem in resultat} == {"abc:Item", "def:item"}
