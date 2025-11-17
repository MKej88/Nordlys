"""Parsing av SAF-T headerinformasjon."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from ..constants import NS
from ..helpers import text_or_none

__all__ = ["SaftHeader", "parse_saft_header"]


@dataclass
class SaftHeader:
    company_name: Optional[str]
    orgnr: Optional[str]
    fiscal_year: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    file_version: Optional[str]


def parse_saft_header(root: ET.Element) -> SaftHeader:
    """Henter ut basisinformasjon fra SAF-T headeren."""

    header = root.find("n1:Header", NS)
    company = header.find("n1:Company", NS) if header is not None else None
    criteria = header.find("n1:SelectionCriteria", NS) if header is not None else None

    def txt(elem: Optional[ET.Element], tag: str) -> Optional[str]:
        return text_or_none(elem.find(f"n1:{tag}", NS)) if elem is not None else None

    def txt_first(elem: Optional[ET.Element], tags: tuple[str, ...]) -> Optional[str]:
        for tag in tags:
            value = txt(elem, tag)
            if value:
                return value
        return None

    def find_company_orgnr(company_elem: Optional[ET.Element]) -> Optional[str]:
        if company_elem is None:
            return None

        search_paths = [
            "n1:RegistrationNumber",
            "n1:TaxRegistrationNumber/n1:RegistrationNumber",
            "n1:TaxRegistrationNumber",
            "n1:CompanyID",
            "n1:TaxRegistrationNumber/n1:CompanyID",
        ]

        for path in search_paths:
            candidate = company_elem.find(path, NS)
            if candidate is None:
                plain_path = path.replace("n1:", "")
                candidate = company_elem.find(plain_path)
            if candidate is not None:
                value = text_or_none(candidate)
                if value:
                    return value
        return None

    return SaftHeader(
        company_name=txt(company, "Name"),
        orgnr=find_company_orgnr(company),
        fiscal_year=txt(criteria, "PeriodEndYear"),
        period_start=txt_first(
            criteria,
            (
                "PeriodStart",
                "SelectionStartDate",
                "StartDate",
                "PeriodStartDate",
            ),
        ),
        period_end=txt_first(
            criteria,
            (
                "PeriodEnd",
                "SelectionEndDate",
                "EndDate",
                "PeriodEndDate",
            ),
        ),
        file_version=(
            text_or_none(header.find("n1:AuditFileVersion", NS))
            if header is not None
            else None
        ),
    )
