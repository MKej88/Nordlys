"""Tester for Brønnøysund-cachemodulen."""

from __future__ import annotations

import importlib
import sys


def test_brreg_cache_importer_definerer_logger() -> None:
    """Modulen skal kunne importeres uten NameError og ha en logger."""

    sys.modules.pop("nordlys.integrations.brreg_cache", None)
    module = importlib.import_module("nordlys.integrations.brreg_cache")
    assert module._LOGGER.name == "nordlys.integrations.brreg_cache"
