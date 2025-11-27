"""Tester for Brønnøysund-cachemodulen."""

from __future__ import annotations

import importlib
import sys

from pytest import MonkeyPatch


def test_brreg_cache_importer_definerer_logger() -> None:
    """Modulen skal kunne importeres uten NameError og ha en logger."""

    sys.modules.pop("nordlys.integrations.brreg_cache", None)
    module = importlib.import_module("nordlys.integrations.brreg_cache")
    assert module._LOGGER.name == "nordlys.integrations.brreg_cache"


def test_fallback_session_har_retry(monkeypatch: MonkeyPatch) -> None:
    """Fallback-sesjonen skal monteres med retry-adaptere."""

    module = importlib.import_module("nordlys.integrations.brreg_cache")
    monkeypatch.setattr(module, "_SESSION", None)
    monkeypatch.setattr(module, "REQUESTS_CACHE_AVAILABLE", False)
    monkeypatch.setattr(module, "requests_cache", None)
    monkeypatch.setattr(module, "_FALLBACK_WARNING_EMITTED", False)

    session = module.get_session()

    https_adapter = session.get_adapter("https://")
    http_adapter = session.get_adapter("http://")

    assert https_adapter.max_retries.total == 3
    assert http_adapter.max_retries.status_forcelist == (429, 500, 502, 503, 504)
