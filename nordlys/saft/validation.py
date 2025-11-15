"""XSD-validering for SAF-T filer."""

from __future__ import annotations

import importlib
import importlib.util
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .header import parse_saft_header

__all__ = [
    "SaftValidationResult",
    "validate_saft_against_xsd",
    "ensure_saft_validated",
    "XMLSCHEMA_AVAILABLE",
    "SAFT_RESOURCE_DIR",
]

SAFT_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources" / "saf_t"

_XMLSCHEMA_SPEC = importlib.util.find_spec("xmlschema")
XMLSCHEMA_AVAILABLE: bool = _XMLSCHEMA_SPEC is not None

XMLSchemaException = Exception
XMLSchema = None  # type: ignore[assignment]


def _ensure_xmlschema_loaded() -> bool:
    """Laster ``xmlschema`` først når det faktisk trengs."""

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
class SaftValidationResult:
    """Resultat av XSD-validering av en SAF-T-fil."""

    audit_file_version: Optional[str]
    version_family: Optional[str]
    schema_version: Optional[str]
    is_valid: Optional[bool]
    details: Optional[str] = None


def _detect_version_family(version: Optional[str]) -> Optional[str]:
    if not version:
        return None
    normalized = version.strip()
    if not normalized:
        return None
    if normalized.startswith(("1.3", "1.30")):
        return "1.3"
    if normalized.startswith(("1.2", "1.20", "1.1", "1.10")):
        return "1.2"
    return None


def _schema_info_for_family(family: Optional[str]) -> Optional[Tuple[Path, str]]:
    if family == "1.3":
        path = (
            SAFT_RESOURCE_DIR
            / "SAF-T_Financial_1.3"
            / "Norwegian_SAF-T_Financial_Schema_v_1.30.xsd"
        )
        return path, "1.30"
    if family == "1.2":
        path = SAFT_RESOURCE_DIR / "Norwegian_SAF-T_Financial_Schema_v_1.10.xsd"
        return path, "1.20"
    return None


def _extract_version_from_file(xml_path: Path) -> Optional[str]:
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError):
        return None
    header = parse_saft_header(root)
    return header.file_version if header else None


def validate_saft_against_xsd(
    xml_source: Path | str, version: Optional[str] = None
) -> SaftValidationResult:
    """Validerer SAF-T XML mot korrekt XSD basert på AuditFileVersion."""

    xml_path = Path(xml_source)
    audit_version = (
        version.strip() if version and version.strip() else None
    ) or _extract_version_from_file(xml_path)
    family = _detect_version_family(audit_version)
    schema_info = _schema_info_for_family(family)
    if schema_info is None:
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=None,
            is_valid=None,
            details="Ingen XSD er definert for denne SAF-T versjonen.",
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
            details=f"Fant ikke XSD-fil: {schema_path}",
        )

    try:
        assert XMLSchema is not None  # for typekontroll
        schema = XMLSchema(str(schema_path))  # type: ignore[misc]
        schema.validate(str(xml_path))
    except XMLSchemaException as exc:  # pragma: no cover - variasjon i tekst
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=False,
            details=str(exc).strip() or "Ukjent valideringsfeil.",
        )
    except OSError as exc:  # pragma: no cover - filsystemfeil sjelden i tester
        return SaftValidationResult(
            audit_file_version=audit_version,
            version_family=family,
            schema_version=schema_version,
            is_valid=False,
            details=str(exc).strip() or "Klarte ikke å lese SAF-T filen.",
        )

    return SaftValidationResult(
        audit_file_version=audit_version,
        version_family=family,
        schema_version=schema_version,
        is_valid=True,
        details="Validering mot XSD fullført uten feil.",
    )


def ensure_saft_validated(xml_path: Path) -> None:
    """Kaster feil dersom filen ikke er gyldig mot XSD."""

    result = validate_saft_against_xsd(xml_path)
    if result.is_valid is None:
        details = result.details or "Validering ble hoppet over fordi XSD-støtte mangler."
        warnings.warn(
            "Hoppet over SAF-T XSD-validering for "
            f"'{xml_path.name}': {details}",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    if result.is_valid is False:
        details = result.details or "Ukjent valideringsfeil."
        raise ValueError(
            f"XSD-validering av SAF-T mislyktes for '{xml_path.name}': {details}"
        )
