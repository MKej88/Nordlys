import pytest

from nordlys.industry_groups import IndustryClassification
from nordlys.saft.brreg_enrichment import (
    _clear_enrichment_cache,
    enrich_from_header,
)
from nordlys.saft import brreg_enrichment
from nordlys.saft.header import SaftHeader


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    _clear_enrichment_cache()


def test_enrich_from_header_caches_by_orgnr(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"fetch": 0, "classify": 0}

    def fake_fetch(orgnr: str):
        calls["fetch"] += 1
        return {"orgnr": orgnr}, None

    def fake_classify(orgnr: str, company_name: str | None):
        calls["classify"] += 1
        return IndustryClassification(
            orgnr=orgnr,
            name=company_name,
            naringskode="01",
            description="",
            sn2="01",
            group="Test",
            source="stub",
        )

    monkeypatch.setattr(brreg_enrichment, "fetch_brreg", fake_fetch)
    monkeypatch.setattr(brreg_enrichment, "classify_from_orgnr", fake_classify)

    header = SaftHeader(
        company_name="Testbed AS",
        orgnr="123456789",
        fiscal_year=None,
        period_start=None,
        period_end=None,
        file_version=None,
    )

    first = enrich_from_header(header)
    second = enrich_from_header(header)

    assert first is second
    assert calls == {"fetch": 1, "classify": 1}


def test_enrich_from_header_normalizes_orgnr_for_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"fetch": 0, "classify": 0}

    def fake_fetch(orgnr: str):
        calls["fetch"] += 1
        return {"orgnr": orgnr}, None

    def fake_classify(orgnr: str, company_name: str | None):
        calls["classify"] += 1
        return IndustryClassification(
            orgnr=orgnr,
            name=company_name,
            naringskode="01",
            description="",
            sn2="01",
            group="Test",
            source="stub",
        )

    monkeypatch.setattr(brreg_enrichment, "fetch_brreg", fake_fetch)
    monkeypatch.setattr(brreg_enrichment, "classify_from_orgnr", fake_classify)

    header_with_spaces = SaftHeader(
        company_name="Testbed AS",
        orgnr="123 456 789",
        fiscal_year=None,
        period_start=None,
        period_end=None,
        file_version=None,
    )

    header_compact = SaftHeader(
        company_name="Testbed AS",
        orgnr="123456789",
        fiscal_year=None,
        period_start=None,
        period_end=None,
        file_version=None,
    )

    first = enrich_from_header(header_with_spaces)
    second = enrich_from_header(header_compact)

    assert first is second
    assert calls == {"fetch": 1, "classify": 1}


def test_enrich_from_header_bypasses_cache_without_orgnr() -> None:
    header = SaftHeader(
        company_name="Testbed AS",
        orgnr=None,
        fiscal_year=None,
        period_start=None,
        period_end=None,
        file_version=None,
    )

    result = enrich_from_header(header)

    assert result.brreg_error == "SAF-T mangler organisasjonsnummer."
    assert result.industry_error == "SAF-T mangler organisasjonsnummer."


def test_enrich_from_header_falls_back_to_name_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_classify(orgnr: str, company_name: str | None):
        raise RuntimeError("Brreg nede")

    monkeypatch.setattr(brreg_enrichment, "fetch_brreg", lambda orgnr: ({}, None))
    monkeypatch.setattr(brreg_enrichment, "classify_from_orgnr", failing_classify)
    monkeypatch.setattr(brreg_enrichment, "load_cached_brreg", lambda orgnr: None)

    header = SaftHeader(
        company_name="Bygg og Anlegg AS",
        orgnr="123456789",
        fiscal_year=None,
        period_start=None,
        period_end=None,
        file_version=None,
    )

    result = enrich_from_header(header)

    assert result.industry is not None
    assert result.industry.group == "Salg av varer og tjenester"
    assert result.industry_error == "Brreg nede"
