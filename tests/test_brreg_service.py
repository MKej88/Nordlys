from __future__ import annotations

import logging

from nordlys.integrations import brreg_service
from nordlys.integrations import brreg_client, brreg_cache
from nordlys.integrations.brreg_service import BrregServiceResult


def test_get_company_status_network_error_returns_unknown(monkeypatch, caplog):
    def fake_fetch(orgnr: str) -> BrregServiceResult:
        return BrregServiceResult(
            data=None,
            error_code="connection_error",
            error_message="Nettverket er nede",
            from_cache=False,
        )

    monkeypatch.setattr(brreg_client, "fetch_enhetsregister", fake_fetch)

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
                "underTvangsavviklingEllerTvangsoppløsning": False,
                "registrertIMvaregisteret": "J",
            },
            error_code=None,
            error_message=None,
            from_cache=False,
        )

    monkeypatch.setattr(brreg_client, "fetch_enhetsregister", fake_fetch)

    status = brreg_service.get_company_status(" 999 999 999 ")

    assert status.orgnr == "999999999"
    assert status.konkurs is False
    assert status.avvikling is True
    assert status.mva_reg is True
    assert status.source == "Brønnøysundregistrene"


def test_fetch_enhetsregister_uses_fallback_cache(monkeypatch):
    monkeypatch.setattr(brreg_client, "REQUESTS_CACHE_AVAILABLE", False, raising=False)
    brreg_cache.clear_fallback_cache()
    brreg_cache.set_session(None)

    call_count = {"value": 0}

    class DummyResponse:
        status_code = 200
        from_cache = False

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, bool]:
            return {"konkurs": False}

    class DummySession:
        def get(self, url: str, headers: dict[str, str], timeout: int) -> DummyResponse:
            call_count["value"] += 1
            return DummyResponse()

    dummy_session = DummySession()
    monkeypatch.setattr(brreg_client, "get_session", lambda: dummy_session)

    result_first = brreg_service.fetch_enhetsregister("123456789")
    result_second = brreg_service.fetch_enhetsregister("123456789")

    assert call_count["value"] == 1
    assert result_first.from_cache is False
    assert result_second.from_cache is True


def test_fetch_enhetsregister_caches_not_found(monkeypatch):
    monkeypatch.setattr(brreg_client, "REQUESTS_CACHE_AVAILABLE", False, raising=False)
    brreg_cache.clear_fallback_cache()
    brreg_cache.set_session(None)

    call_count = {"value": 0}

    class DummyResponse:
        status_code = 404
        from_cache = False

        def raise_for_status(self) -> None:
            return None

    class DummySession:
        def get(self, url: str, headers: dict[str, str], timeout: int) -> DummyResponse:
            call_count["value"] += 1
            return DummyResponse()

    monkeypatch.setattr(brreg_client, "get_session", lambda: DummySession())

    result_first = brreg_service.fetch_enhetsregister("987654321")
    result_second = brreg_service.fetch_enhetsregister("987654321")

    assert call_count["value"] == 1
    assert result_first.error_code == "not_found"
    assert result_second.from_cache is True


def test_fetch_regnskapsregister_accepts_list_payload(monkeypatch):
    monkeypatch.setattr(brreg_client, "REQUESTS_CACHE_AVAILABLE", False, raising=False)
    brreg_cache.clear_fallback_cache()
    brreg_cache.set_session(None)

    class DummyResponse:
        status_code = 200
        from_cache = False

        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, int]]:
            return [{"sumDriftsinntekter": 123}]

    class DummySession:
        def get(self, url: str, headers: dict[str, str], timeout: int) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr(brreg_client, "get_session", lambda: DummySession())

    result = brreg_service.fetch_regnskapsregister("123456789")

    assert isinstance(result.data, list)
    assert result.error_code is None


def test_invalid_orgnr_gives_clear_error() -> None:
    result = brreg_service.fetch_enhetsregister("123")

    assert result.data is None
    assert result.error_code == "invalid_orgnr"
    assert "9" in (result.error_message or "")

    status = brreg_service.get_company_status("abc")

    assert status.orgnr == ""
    assert status.source is None
