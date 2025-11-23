from __future__ import annotations

import importlib

import nordlys.settings as settings
import pytest


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    monkeypatch.delenv("NORDLYS_NAV_WIDTH", raising=False)
    yield
    monkeypatch.delenv("NORDLYS_NAV_WIDTH", raising=False)
    importlib.reload(settings)


def test_nav_width_override(monkeypatch):
    monkeypatch.setenv("NORDLYS_NAV_WIDTH", "280")
    reloaded = importlib.reload(settings)
    assert reloaded.NAV_PANEL_WIDTH_OVERRIDE == 280


def test_nav_width_override_invalid(monkeypatch):
    monkeypatch.setenv("NORDLYS_NAV_WIDTH", "abc")
    reloaded = importlib.reload(settings)
    assert reloaded.NAV_PANEL_WIDTH_OVERRIDE is None
