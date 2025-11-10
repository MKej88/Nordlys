"""Funksjoner for å lese og analysere SAF-T filer."""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING
import xml.etree.ElementTree as ET
import re

import numpy as np

from .constants import NS
from .utils import lazy_pandas, text_or_none, to_float

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import pandas as pd

pd = lazy_pandas()


_XMLSCHEMA_SPEC = importlib.util.find_spec("xmlschema")
XMLSCHEMA_AVAILABLE: bool = _XMLSCHEMA_SPEC is not None


class XMLSchemaException(Exception):
    """Fallback-unntak når xmlschema ikke er tilgjengelig."""


XMLSchema = None  # type: ignore[assignment]


def _ensure_xmlschema_loaded() -> bool:
    """Prøver å importere ``xmlschema`` først når det trengs.

    Dette gjør at applikasjonen starter raskere for brukere som ikke
    benytter XSD-validering, siden den tunge avhengigheten ikke lastes ved
    modulimport.
    """

    global XMLSchema, XMLSchemaException, XMLSCHEMA_AVAILABLE

    if XMLSchema is not None:
        return True

    if not XMLSCHEMA_AVAILABLE:
        return False

    try:
        xmlschema_module = importlib.import_module("xmlschema")
    except Exception:  # pragma: no cover - importfeil håndteres som manglende pakke
        XMLSchema = None  # type: ignore[assignment]
        XMLSCHEMA_AVAILABLE = False
        return False

    XMLSchema = xmlschema_module.XMLSchema  # type: ignore[attr-defined,assignment]
    XMLSchemaException = xmlschema_module.XMLSchemaException  # type: ignore[attr-defined]
    return True


@dataclass
class SaftHeader:
    company_name: Optional[str]
    orgnr: Optional[str]
    fiscal_year: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    file_version: Optional[str]


@dataclass
class SaftValidationResult:
    """Resultat av XSD-validering av en SAF-T-fil."""

    audit_file_version: Optional[str]
    version_family: Optional[str]
    schema_version: Optional[str]
    is_valid: Optional[bool]
    details: Optional[str] = None


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


SAFT_RESOURCE_DIR = Path(__file__).resolve().parent / 'resources' / 'saf_t'


def _detect_version_family(version: Optional[str]) -> Optional[str]:
    """Normaliserer AuditFileVersion til hovedvariant (1.2 eller 1.3)."""

    if not version:
        return None
    normalized = version.strip()
    if not normalized:
        return None
    if normalized.startswith(('1.3', '1.30')):
        return '1.3'
    if normalized.startswith(('1.2', '1.20', '1.1', '1.10')):
        return '1.2'
    return None


def _schema_info_for_family(family: Optional[str]) -> Optional[Tuple[Path, str]]:
    """Returnerer sti og versjon på XSD for gitt hovedvariant."""

    if family == '1.3':
        path = SAFT_RESOURCE_DIR / 'SAF-T_Financial_1.3' / 'Norwegian_SAF-T_Financial_Schema_v_1.30.xsd'
        return path, '1.30'
    if family == '1.2':
        path = SAFT_RESOURCE_DIR / 'Norwegian_SAF-T_Financial_Schema_v_1.10.xsd'
        return path, '1.20'
    return None


def _extract_version_from_file(xml_path: Path) -> Optional[str]:
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError):
        return None
    header = parse_saft_header(root)
    return header.file_version if header else None


def validate_saft_against_xsd(xml_source: Path | str, version: Optional[str] = None) -> SaftValidationResult:
    """Validerer SAF-T XML mot korrekt XSD basert på AuditFileVersion."""

    xml_path = Path(xml_source)
    audit_version = (version.strip() if version and version.strip() else None) or _extract_version_from_file(xml_path)
    family = _detect_version_family(audit_version)
    schema_info = _schema_info_for_family(family)
    if schema_info is None:
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=None,
            is_valid=None,
            details='Ingen XSD er definert for denne SAF-T versjonen.',
        )

    schema_path, schema_version = schema_info
    if not _ensure_xmlschema_loaded():
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=None,
            details=(
                "XSD-validering er ikke tilgjengelig fordi pakken "
                "`xmlschema` ikke er installert. Installer den for full validering."
            ),
        )

    if not schema_path.exists():
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=None,
            details=f'Fant ikke XSD-fil: {schema_path}',
        )

    try:
        schema = XMLSchema(schema_path)
        schema.validate(str(xml_path))
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=True,
            details='Validering mot XSD fullført uten feil.',
        )
    except XMLSchemaException as exc:  # pragma: no cover - detaljert feiltekst varierer
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=False,
            details=str(exc).strip() or 'Ukjent valideringsfeil.',
        )
    except OSError as exc:  # pragma: no cover - filsystemfeil sjelden i tester
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=False,
            details=str(exc).strip() or 'Klarte ikke å lese SAF-T filen.',
        )


def parse_saft_header(root: ET.Element) -> SaftHeader:
    """Henter ut basisinformasjon fra SAF-T headeren."""
    header = root.find('n1:Header', NS)
    company = header.find('n1:Company', NS) if header is not None else None
    criteria = header.find('n1:SelectionCriteria', NS) if header is not None else None

    def txt(elem: Optional[ET.Element], tag: str) -> Optional[str]:
        return text_or_none(elem.find(f"n1:{tag}", NS)) if elem is not None else None

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
        company_name=txt(company, 'Name'),
        orgnr=find_company_orgnr(company),
        fiscal_year=txt(criteria, 'PeriodEndYear'),
        period_start=txt(criteria, 'PeriodStart'),
        period_end=txt(criteria, 'PeriodEnd'),
        file_version=text_or_none(header.find('n1:AuditFileVersion', NS)) if header is not None else None,
    )


def parse_saldobalanse(root: ET.Element) -> pd.DataFrame:
    """Returnerer saldobalansen som Pandas DataFrame."""
    gl = root.find('n1:MasterFiles/n1:GeneralLedgerAccounts', NS)
    accounts = gl.iterfind('n1:Account', NS) if gl is not None else ()

    def get(acct: ET.Element, tag: str) -> Optional[str]:
        return text_or_none(acct.find(f"n1:{tag}", NS))

    konto_pattern = re.compile(r'-?\d+')

    def konto_to_int(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        match = konto_pattern.search(value)
        if not match:
            return None
        try:
            return int(match.group())
        except ValueError:
            return None

    konto_values: List[Optional[str]] = []
    navn_values: List[str] = []
    ib_debet_values: List[float] = []
    ib_kredit_values: List[float] = []
    endring_debet_values: List[float] = []
    endring_kredit_values: List[float] = []
    ub_debet_values: List[float] = []
    ub_kredit_values: List[float] = []
    ib_netto_values: List[float] = []
    ub_netto_values: List[float] = []
    konto_int_values: List[Optional[int]] = []

    for account in accounts:
        konto = get(account, 'AccountID')
        navn = get(account, 'AccountDescription') or ''
        opening_debit = to_float(get(account, 'OpeningDebitBalance'))
        opening_credit = to_float(get(account, 'OpeningCreditBalance'))
        closing_debit = to_float(get(account, 'ClosingDebitBalance'))
        closing_credit = to_float(get(account, 'ClosingCreditBalance'))

        ib_netto = opening_debit - opening_credit
        ub_netto = closing_debit - closing_credit
        endring = ub_netto - ib_netto

        konto_values.append(konto)
        navn_values.append(navn)
        ib_debet_values.append(opening_debit)
        ib_kredit_values.append(opening_credit)
        endring_debet_values.append(endring if endring > 0 else 0.0)
        endring_kredit_values.append(-endring if endring < 0 else 0.0)
        ub_debet_values.append(closing_debit)
        ub_kredit_values.append(closing_credit)
        ib_netto_values.append(ib_netto)
        ub_netto_values.append(ub_netto)
        konto_int_values.append(konto_to_int(konto))

    data = {
        'Konto': konto_values,
        'Kontonavn': navn_values,
        'IB Debet': ib_debet_values,
        'IB Kredit': ib_kredit_values,
        'Endring Debet': endring_debet_values,
        'Endring Kredit': endring_kredit_values,
        'UB Debet': ub_debet_values,
        'UB Kredit': ub_kredit_values,
        'IB_netto': ib_netto_values,
        'UB_netto': ub_netto_values,
        'Konto_int': konto_int_values,
    }

    return pd.DataFrame(data, columns=list(data.keys()))


def ns4102_summary_from_tb(df: pd.DataFrame) -> Dict[str, float]:
    """Utleder nøkkeltall basert på saldobalansen."""
    mask = df['Konto_int'].notna()
    if not mask.any():
        return {
            'driftsinntekter': 0.0,
            'varekostnad': 0.0,
            'lonn': 0.0,
            'avskrivninger': 0.0,
            'andre_drift': 0.0,
            'ebitda': 0.0,
            'ebit': 0.0,
            'finans_netto': 0.0,
            'skattekostnad': 0.0,
            'ebt': 0.0,
            'arsresultat': 0.0,
            'eiendeler_UB': 0.0,
            'egenkapital_UB': 0.0,
            'gjeld_UB': 0.0,
            'balanse_diff': 0.0,
            'eiendeler_UB_brreg': 0.0,
            'gjeld_UB_brreg': 0.0,
            'balanse_diff_brreg': 0.0,
            'liab_debet_21xx_29xx': 0.0,
        }

    subset = df.loc[mask]
    konto_values = subset['Konto_int'].astype(int).to_numpy()
    ib_debet = subset['IB Debet'].fillna(0.0).to_numpy()
    ib_kredit = subset['IB Kredit'].fillna(0.0).to_numpy()
    ub_debet = subset['UB Debet'].fillna(0.0).to_numpy()
    ub_kredit = subset['UB Kredit'].fillna(0.0).to_numpy()

    ib_values = ib_debet - ib_kredit
    ub_values = ub_debet - ub_kredit
    end_values = ub_values - ib_values

    order = np.argsort(konto_values)
    sorted_konto = konto_values[order]
    sorted_end = end_values[order]
    sorted_ub = ub_values[order]

    end_prefix = np.concatenate(([0.0], np.cumsum(sorted_end)))
    ub_prefix = np.concatenate(([0.0], np.cumsum(sorted_ub)))

    def _sum_prefix(prefix: np.ndarray, sorted_accounts: np.ndarray, start: int, stop: int) -> float:
        left = int(np.searchsorted(sorted_accounts, start, side='left'))
        right = int(np.searchsorted(sorted_accounts, stop, side='right'))
        if left >= right:
            return 0.0
        return float(prefix[right] - prefix[left])

    def sum_in_range_end(start: int, stop: int) -> float:
        return _sum_prefix(end_prefix, sorted_konto, start, stop)

    def sum_in_range_ub(start: int, stop: int) -> float:
        return _sum_prefix(ub_prefix, sorted_konto, start, stop)

    driftsinntekter = -sum_in_range_end(3000, 3999)
    varekostnad = sum_in_range_end(4000, 4999)
    lonn = sum_in_range_end(5000, 5999)
    avskr = sum_in_range_end(6000, 6099) + sum_in_range_end(7800, 7899)
    andre_drift = sum_in_range_end(6100, 7999) - sum_in_range_end(7800, 7899)
    ebitda = driftsinntekter - (varekostnad + lonn + andre_drift)
    ebit = ebitda - avskr
    finans = -(sum_in_range_end(8000, 8299) + sum_in_range_end(8400, 8899))
    skatt = sum_in_range_end(8300, 8399)
    ebt = ebit + finans
    arsresultat = ebt - skatt
    anlegg_UB = sum_in_range_ub(1000, 1399)
    omlop_UB = sum_in_range_ub(1400, 1999)
    eiendeler_netto = anlegg_UB + omlop_UB
    egenkap_UB = -sum_in_range_ub(2000, 2099)
    liab_mask = (konto_values >= 2100) & (konto_values <= 2999)
    liab_values = ub_values[liab_mask]
    liab_kreditt = float(-liab_values[liab_values < 0].sum())
    liab_debet = float(liab_values[liab_values > 0].sum())
    gjeld_netto = liab_kreditt - liab_debet
    balanse_diff_netto = eiendeler_netto - (egenkap_UB + gjeld_netto)
    eiendeler_brreg = eiendeler_netto + liab_debet
    gjeld_brreg = liab_kreditt
    balanse_diff_brreg = eiendeler_brreg - (egenkap_UB + gjeld_brreg)

    return {
        'driftsinntekter': driftsinntekter,
        'varekostnad': varekostnad,
        'lonn': lonn,
        'avskrivninger': avskr,
        'andre_drift': andre_drift,
        'ebitda': ebitda,
        'ebit': ebit,
        'finans_netto': finans,
        'skattekostnad': skatt,
        'ebt': ebt,
        'arsresultat': arsresultat,
        'eiendeler_UB': eiendeler_netto,
        'egenkapital_UB': egenkap_UB,
        'gjeld_UB': gjeld_netto,
        'balanse_diff': balanse_diff_netto,
        'eiendeler_UB_brreg': eiendeler_brreg,
        'gjeld_UB_brreg': gjeld_brreg,
        'balanse_diff_brreg': balanse_diff_brreg,
        'liab_debet_21xx_29xx': float(liab_debet),
    }


def parse_customers(root: ET.Element) -> Dict[str, CustomerInfo]:
    """Returnerer oppslag over kunder med kundenummer og navn."""

    customers: Dict[str, CustomerInfo] = {}
    for element in root.findall('.//n1:MasterFiles/n1:Customer', NS):
        cid = text_or_none(element.find('n1:CustomerID', NS))
        if not cid:
            continue
        number = (
            text_or_none(element.find('n1:CustomerNumber', NS))
            or text_or_none(element.find('n1:AccountID', NS))
            or text_or_none(element.find('n1:SupplierAccountID', NS))
            or cid
        )
        raw_name = (
            text_or_none(element.find('n1:Name', NS))
            or text_or_none(element.find('n1:CompanyName', NS))
            or text_or_none(element.find('n1:Contact/n1:Name', NS))
            or text_or_none(element.find('n1:Contact/n1:ContactName', NS))
            or ''
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
    for element in root.findall('.//n1:MasterFiles/n1:Supplier', NS):
        sid = text_or_none(element.find('n1:SupplierID', NS))
        if not sid:
            continue
        number = (
            text_or_none(element.find('n1:SupplierAccountID', NS))
            or text_or_none(element.find('n1:SupplierTaxID', NS))
            or text_or_none(element.find('n1:AccountID', NS))
            or sid
        )
        raw_name = (
            text_or_none(element.find('n1:SupplierName', NS))
            or text_or_none(element.find('n1:Name', NS))
            or text_or_none(element.find('n1:CompanyName', NS))
            or text_or_none(element.find('n1:Contact/n1:Name', NS))
            or text_or_none(element.find('n1:Contact/n1:ContactName', NS))
            or ''
        )
        name = raw_name.strip()
        suppliers[sid] = SupplierInfo(
            supplier_id=sid,
            supplier_number=number or sid,
            name=name,
        )
    return suppliers


__all__ = [
    'SaftHeader',
    'SaftValidationResult',
    'CustomerInfo',
    'SupplierInfo',
    'parse_saft_header',
    'parse_saldobalanse',
    'ns4102_summary_from_tb',
    'parse_customers',
    'parse_suppliers',
    'validate_saft_against_xsd',
]
