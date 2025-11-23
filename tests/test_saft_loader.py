from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pandas as pd

from nordlys.saft import loader
from nordlys.saft.brreg_enrichment import BrregEnrichment
from nordlys.saft.customer_analysis import CustomerSupplierAnalysis
from nordlys.saft.validation import SaftValidationResult


def test_suggest_max_workers_caps_for_heavy_dummy_paths(monkeypatch):
    size_map = {
        "heavy_a": loader.HEAVY_SAFT_FILE_BYTES,
        "heavy_b": loader.HEAVY_SAFT_FILE_BYTES + 1,
        "heavy_c": loader.HEAVY_SAFT_FILE_BYTES * 2,
    }

    def fake_stat(self: Path) -> SimpleNamespace:
        return SimpleNamespace(st_size=size_map.get(str(self), 0))

    monkeypatch.setattr(Path, "stat", fake_stat)

    dummy_paths = list(size_map)
    suggested = loader._suggest_max_workers(dummy_paths, cpu_limit=8)

    assert suggested == loader.HEAVY_SAFT_MAX_WORKERS


def test_loader_triggers_validation_and_enrichment_early(tmp_path, monkeypatch):
    xml_content = """
    <AuditFile xmlns="urn:StandardAuditFile-Taxation-Financial:NO">
      <Header>
        <Company>
          <Name>Test</Name>
          <RegistrationNumber>999999999</RegistrationNumber>
        </Company>
        <SelectionCriteria>
          <PeriodStart>2023-01-01</PeriodStart>
          <PeriodEnd>2023-12-31</PeriodEnd>
          <PeriodEndYear>2023</PeriodEndYear>
        </SelectionCriteria>
        <AuditFileVersion>1.3</AuditFileVersion>
      </Header>
      <MasterFiles />
      <GeneralLedgerEntries />
    </AuditFile>
    """

    xml_path = tmp_path / "sample.xml"
    xml_path.write_text(xml_content)

    validation_started = Event()
    enrichment_started = Event()

    def fake_validate(path: str, version: str | None) -> SaftValidationResult:
        validation_started.set()
        return SaftValidationResult(
            audit_file_version=version,
            version_family=None,
            schema_version=None,
            is_valid=None,
            details=None,
        )

    def fake_enrich(header) -> BrregEnrichment:
        enrichment_started.set()
        return BrregEnrichment(
            brreg_json=None,
            brreg_map=None,
            brreg_error=None,
            industry=None,
            industry_error=None,
        )

    def fake_parse_saldobalanse(root) -> pd.DataFrame:
        assert validation_started.wait(timeout=1)
        assert enrichment_started.wait(timeout=1)
        return pd.DataFrame(
            {
                "Konto": [],
                "Kontonavn": [],
                "IB Debet": [],
                "IB Kredit": [],
                "Endring Debet": [],
                "Endring Kredit": [],
                "UB Debet": [],
                "UB Kredit": [],
                "IB_netto": [],
                "UB_netto": [],
                "Konto_int": [],
            }
        )

    monkeypatch.setattr(loader.saft, "validate_saft_against_xsd", fake_validate)
    monkeypatch.setattr(loader, "enrich_from_header", fake_enrich)
    monkeypatch.setattr(loader.saft, "parse_saldobalanse", fake_parse_saldobalanse)
    monkeypatch.setattr(loader.saft, "parse_customers", lambda root: {})
    monkeypatch.setattr(loader.saft, "parse_suppliers", lambda root: {})
    monkeypatch.setattr(
        loader,
        "build_customer_supplier_analysis",
        lambda header, root, ns: CustomerSupplierAnalysis(
            analysis_year=None,
            customer_sales=None,
            supplier_purchases=None,
            cost_vouchers=[],
        ),
    )
    monkeypatch.setattr(loader.saft, "ns4102_summary_from_tb", lambda df: {})

    result = loader.load_saft_file(str(xml_path))

    assert result.validation.audit_file_version == "1.3"
    assert validation_started.is_set()
    assert enrichment_started.is_set()


def test_suggest_max_workers_caps_for_two_heavy_files(monkeypatch):
    size_map = {
        "heavy_a": loader.HEAVY_SAFT_FILE_BYTES + 5,
        "heavy_b": loader.HEAVY_SAFT_FILE_BYTES * 2,
        "small": loader.HEAVY_SAFT_FILE_BYTES - 1,
    }

    def fake_stat(self: Path) -> SimpleNamespace:
        return SimpleNamespace(st_size=size_map.get(str(self), 0))

    monkeypatch.setattr(Path, "stat", fake_stat)

    dummy_paths = list(size_map)
    suggested = loader._suggest_max_workers(dummy_paths, cpu_limit=8)

    assert suggested == loader.HEAVY_SAFT_MAX_WORKERS
