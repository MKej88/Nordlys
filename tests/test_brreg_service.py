from __future__ import annotations

import logging

from nordlys.integrations import brreg_service
from nordlys.integrations.brreg_service import BrregServiceResult


def test_get_company_status_network_error_returns_unknown(monkeypatch, caplog):
    def fake_fetch(orgnr: str) -> BrregServiceResult:
        return BrregServiceResult(
            data=None,
            error_code="connection_error",
            error_message="Nettverket er nede",
            from_cache=False,
        )

    monkeypatch.setattr(brreg_service, "fetch_enhetsregister", fake_fetch)

    with caplog.at_level(logging.WARNING):
        status = brreg_service.get_company_status("123456789")

    assert status.konkurs is None
    assert status.avvikling is None
    assert status.mva_reg is None
    assert status.source is None
    assert "Nettverket er nede" in caplog.text


def test_get_company_status_maps_flags(monkeypatch):
    def fake_fetch(orgnr: str) -> BrregServiceResult:
        return BrregServiceResult(
            data={
                "konkurs": False,
                "underAvvikling": "ja",
                "underTvangsavviklingEllerTvangsopplosning": False,
                "registrertIMvaregisteret": "J",
            },
            error_code=None,
            error_message=None,
            from_cache=False,
        )

    monkeypatch.setattr(brreg_service, "fetch_enhetsregister", fake_fetch)

    status = brreg_service.get_company_status(" 999 999 999 ")

    assert status.orgnr == "999999999"
    assert status.konkurs is False
    assert status.avvikling is True
    assert status.mva_reg is True
    assert status.source == "Brønnøysundregistrene"
