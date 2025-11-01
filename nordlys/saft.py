"""Funksjoner for å lese og analysere SAF-T filer."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import pandas as pd

from .constants import NS
from .utils import findall_any_namespace, text_or_none, to_float


_XMLSCHEMA_SPEC = importlib.util.find_spec("xmlschema")
if _XMLSCHEMA_SPEC is not None:
    from xmlschema import XMLSchema, XMLSchemaException  # type: ignore[import]
    XMLSCHEMA_AVAILABLE = True
else:  # pragma: no cover - kjøres kun uten opsjonal avhengighet
    XMLSchema = None  # type: ignore[assignment]

    class XMLSchemaException(Exception):
        """Fallback-unntak når xmlschema ikke er tilgjengelig."""

    XMLSCHEMA_AVAILABLE = False


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
    except ET.ParseError:
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
    if not XMLSCHEMA_AVAILABLE or XMLSchema is None:
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

    return SaftHeader(
        company_name=txt(company, 'Name'),
        orgnr=txt(company, 'RegistrationNumber'),
        fiscal_year=txt(criteria, 'PeriodEndYear'),
        period_start=txt(criteria, 'PeriodStart'),
        period_end=txt(criteria, 'PeriodEnd'),
        file_version=text_or_none(header.find('n1:AuditFileVersion', NS)) if header is not None else None,
    )


def parse_saldobalanse(root: ET.Element) -> pd.DataFrame:
    """Returnerer saldobalansen som Pandas DataFrame."""
    gl = root.find('n1:MasterFiles/n1:GeneralLedgerAccounts', NS)
    rows: List[Dict[str, Optional[float]]] = []
    if gl is None:
        return pd.DataFrame(
            columns=[
                'Konto',
                'Kontonavn',
                'IB Debet',
                'IB Kredit',
                'Endring Debet',
                'Endring Kredit',
                'UB Debet',
                'UB Kredit',
            ]
        )

    def get(acct: ET.Element, tag: str) -> Optional[str]:
        return text_or_none(acct.find(f"n1:{tag}", NS))

    for account in gl.findall('n1:Account', NS):
        konto = get(account, 'AccountID')
        navn = get(account, 'AccountDescription') or ''
        opening_debit = to_float(get(account, 'OpeningDebitBalance'))
        opening_credit = to_float(get(account, 'OpeningCreditBalance'))
        closing_debit = to_float(get(account, 'ClosingDebitBalance'))
        closing_credit = to_float(get(account, 'ClosingCreditBalance'))
        rows.append(
            {
                'Konto': konto,
                'Kontonavn': navn,
                'IB Debet': opening_debit,
                'IB Kredit': opening_credit,
                'Endring Debet': 0.0,
                'Endring Kredit': 0.0,
                'UB Debet': closing_debit,
                'UB Kredit': closing_credit,
            }
        )

    df = pd.DataFrame(rows)
    df['IB_netto'] = df['IB Debet'].fillna(0) - df['IB Kredit'].fillna(0)
    df['UB_netto'] = df['UB Debet'].fillna(0) - df['UB Kredit'].fillna(0)
    endring = df['UB_netto'] - df['IB_netto']
    df['Endring Debet'] = endring.where(endring > 0, 0.0)
    df['Endring Kredit'] = (-endring).where(endring < 0, 0.0)

    def konto_to_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(float(str(value).strip()))
        except Exception:
            digits = ''.join(ch for ch in str(value) if ch.isdigit())
            return int(digits) if digits else None

    df['Konto_int'] = df['Konto'].apply(konto_to_int)
    return df


def ns4102_summary_from_tb(df: pd.DataFrame) -> Dict[str, float]:
    """Utleder nøkkeltall basert på saldobalansen."""
    work = df.copy()
    work = work[~work['Konto_int'].isna()].copy()
    work['Konto_int'] = work['Konto_int'].astype(int)
    work['IB_netto'] = work['IB Debet'].fillna(0) - work['IB Kredit'].fillna(0)
    work['UB_netto'] = work['UB Debet'].fillna(0) - work['UB Kredit'].fillna(0)
    work['END_netto'] = work['Endring Debet'].fillna(0) - work['Endring Kredit'].fillna(0)

    def sum_in_range(column: str, start: int, stop: int) -> float:
        mask = (work['Konto_int'] >= start) & (work['Konto_int'] <= stop)
        return float(work.loc[mask, column].sum())

    driftsinntekter = -sum_in_range('END_netto', 3000, 3999)
    varekostnad = sum_in_range('END_netto', 4000, 4999)
    lonn = sum_in_range('END_netto', 5000, 5999)
    avskr = sum_in_range('END_netto', 6000, 6099) + sum_in_range('END_netto', 7800, 7899)
    andre_drift = sum_in_range('END_netto', 6100, 7999) - sum_in_range('END_netto', 7800, 7899)
    ebitda = driftsinntekter - (varekostnad + lonn + andre_drift)
    ebit = ebitda - avskr
    finans = -(sum_in_range('END_netto', 8000, 8299) + sum_in_range('END_netto', 8400, 8899))
    skatt = sum_in_range('END_netto', 8300, 8399)
    ebt = ebit + finans
    arsresultat = ebt - skatt
    anlegg_UB = sum_in_range('UB_netto', 1000, 1399)
    omlop_UB = sum_in_range('UB_netto', 1400, 1999)
    eiendeler_netto = anlegg_UB + omlop_UB
    egenkap_UB = -sum_in_range('UB_netto', 2000, 2099)
    liab = work[(work['Konto_int'] >= 2100) & (work['Konto_int'] <= 2999)]
    liab_kreditt = -liab.loc[liab['UB_netto'] < 0, 'UB_netto'].sum()
    liab_debet = liab.loc[liab['UB_netto'] > 0, 'UB_netto'].sum()
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


def _approx_equal(a: float, b: float, tolerance: float = 0.5) -> bool:
    """Sammenligner to flyttall med en liten toleranse for avrunding."""

    return abs(a - b) <= tolerance


def extract_sales_taxbase_by_customer(root: ET.Element) -> pd.DataFrame:
    """Ekstraherer fakturabasert omsetning per kunde."""
    rows: List[Dict[str, float]] = []
    for invoice in root.findall('.//n1:SourceDocuments/n1:SalesInvoices/n1:Invoice', NS):
        customer_id = None
        for path in ['n1:CustomerID', 'n1:Customer/n1:CustomerID', 'n1:CustomerParty/n1:CustomerID']:
            element = invoice.find(path, NS)
            if element is not None and element.text and element.text.strip():
                customer_id = element.text.strip()
                break
        if not customer_id:
            continue
        tax_exclusive = to_float(
            text_or_none(invoice.find('n1:DocumentTotals/n1:TaxExclusiveAmount', NS))
        )
        net_total = to_float(text_or_none(invoice.find('n1:DocumentTotals/n1:NetTotal', NS)))
        invoice_net_total = to_float(
            text_or_none(invoice.find('n1:DocumentTotals/n1:InvoiceNetTotal', NS))
        )
        gross_total = to_float(text_or_none(invoice.find('n1:DocumentTotals/n1:GrossTotal', NS)))
        inclusive_total = to_float(
            text_or_none(invoice.find('n1:DocumentTotals/n1:TaxInclusiveAmount', NS))
        )
        tax_payable = to_float(text_or_none(invoice.find('n1:DocumentTotals/n1:TaxPayable', NS)))
        if tax_payable == 0.0:
            tax_payable = to_float(
                text_or_none(invoice.find('n1:DocumentTotals/n1:TaxTotal/n1:TaxAmount', NS))
            )

        line_tax_base = sum(
            to_float(text_or_none(base)) for base in findall_any_namespace(invoice, 'TaxBase')
        )
        if line_tax_base == 0.0:
            line_tax_base = sum(
                to_float(text_or_none(base))
                for base in findall_any_namespace(invoice, 'TaxableAmount')
            )

        candidates: List[float] = []
        if tax_exclusive > 0.0:
            candidates.append(tax_exclusive)

        if line_tax_base > 0.0:
            candidates.append(line_tax_base)

        if net_total > 0.0:
            if gross_total > 0.0 and tax_payable > 0.0 and _approx_equal(net_total + tax_payable, gross_total):
                candidates.append(net_total)
            elif inclusive_total > 0.0 and tax_payable > 0.0 and _approx_equal(net_total, inclusive_total):
                candidates.append(max(net_total - tax_payable, 0.0))
            elif tax_payable > 0.0 and net_total > tax_payable:
                candidates.append(max(net_total - tax_payable, 0.0))

        if invoice_net_total > 0.0:
            if gross_total > 0.0 and tax_payable > 0.0 and _approx_equal(invoice_net_total + tax_payable, gross_total):
                candidates.append(invoice_net_total)
            elif inclusive_total > 0.0 and tax_payable > 0.0 and _approx_equal(invoice_net_total, inclusive_total):
                candidates.append(max(invoice_net_total - tax_payable, 0.0))
            elif tax_payable > 0.0 and invoice_net_total > tax_payable:
                candidates.append(max(invoice_net_total - tax_payable, 0.0))

        if gross_total > 0.0 and tax_payable > 0.0:
            candidates.append(max(gross_total - tax_payable, 0.0))

        if inclusive_total > 0.0 and tax_payable > 0.0:
            candidates.append(max(inclusive_total - tax_payable, 0.0))

        amount = 0.0
        for candidate in candidates:
            if candidate and candidate > 0.0:
                amount = candidate
                break

        rows.append({'CustomerID': customer_id, 'NetExVAT': float(max(amount, 0.0))})

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    aggregated = df.groupby('CustomerID')['NetExVAT'].agg(['sum', 'count']).reset_index()
    aggregated.rename(columns={'sum': 'OmsetningEksMva', 'count': 'Fakturaer'}, inplace=True)
    return aggregated


def extract_ar_from_gl(root: ET.Element) -> pd.DataFrame:
    """Bruker hovedbokstransaksjoner for å estimere omsetning per kunde."""
    def get_amount(line: ET.Element, tag: str) -> float:
        element = line.find(f'n1:{tag}', NS)
        if element is not None and element.text and element.text.strip():
            return to_float(element.text)
        amount = line.find(f'n1:{tag}/n1:Amount', NS)
        if amount is not None and amount.text and amount.text.strip():
            return to_float(amount.text)
        return 0.0

    rows: List[Dict[str, float]] = []
    for line in root.findall('.//n1:GeneralLedgerEntries/n1:Journal/n1:Transaction/n1:Line', NS):
        customer_id = None
        for element in line.iter():
            tag = element.tag.split('}')[-1].lower()
            if 'customer' in tag and 'id' in tag and element.text and element.text.strip():
                customer_id = element.text.strip()
                break
        if not customer_id:
            continue
        account_element = line.find('n1:AccountID', NS)
        account = (account_element.text or '').strip() if account_element is not None and account_element.text else ''
        account_digits = ''.join(ch for ch in account if ch.isdigit())
        account_int = int(account_digits) if account_digits else 0
        if 1500 <= account_int <= 1599:
            debit = get_amount(line, 'DebitAmount')
            credit = get_amount(line, 'CreditAmount')
            tax_base_elements = findall_any_namespace(line, 'TaxBase')
            taxable_amount_elements = findall_any_namespace(line, 'TaxableAmount')
            tax_amount_elements = findall_any_namespace(line, 'TaxAmount')
            tax_base = sum(to_float(text_or_none(el)) for el in tax_base_elements)
            taxable_amount = sum(to_float(text_or_none(el)) for el in taxable_amount_elements)
            tax_amount = sum(to_float(text_or_none(el)) for el in tax_amount_elements)
            effective_base = tax_base or taxable_amount
            if effective_base == 0.0 and tax_amount > 0.0:
                effective_base = max(debit - tax_amount, 0.0)
            rows.append(
                {
                    'CustomerID': customer_id,
                    'AR_Debit': debit,
                    'AR_Credit': credit,
                    'TaxBase': effective_base,
                    'TaxAmount': tax_amount,
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    grouped = (
        df.groupby('CustomerID')
        .agg({'AR_Debit': 'sum', 'AR_Credit': 'sum', 'TaxBase': 'sum', 'TaxAmount': 'sum'})
        .reset_index()
    )
    grouped['AR_Netto'] = grouped['AR_Debit'] - grouped['AR_Credit']
    grouped['OmsetningEksMva'] = grouped['TaxBase']
    mask = grouped['OmsetningEksMva'] == 0
    grouped.loc[mask, 'OmsetningEksMva'] = grouped.loc[mask, 'AR_Debit'] - grouped.loc[mask, 'TaxAmount']
    grouped['OmsetningEksMva'] = grouped['OmsetningEksMva'].clip(lower=0.0)
    return grouped


__all__ = [
    'SaftHeader',
    'SaftValidationResult',
    'CustomerInfo',
    'parse_saft_header',
    'parse_saldobalanse',
    'ns4102_summary_from_tb',
    'parse_customers',
    'extract_sales_taxbase_by_customer',
    'extract_ar_from_gl',
    'validate_saft_against_xsd',
]
