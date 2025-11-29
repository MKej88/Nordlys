import pandas as pd
import pytest

try:  # pragma: no cover - miljøavhengig
    from PySide6.QtWidgets import QApplication
except (ImportError, OSError) as exc:  # pragma: no cover - miljøavhengig
    pytest.skip(f"PySide6 er ikke tilgjengelig: {exc}", allow_module_level=True)

from nordlys.ui.data_manager import SaftDatasetStore
from nordlys.ui.page_state_handler import PageStateHandler


@pytest.fixture(scope="session")
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_build_brreg_comparison_rows_suggests_matching_account(
    _qapp: QApplication,
) -> None:
    store = SaftDatasetStore()
    # Manuelt sett nødvendige felter for testen
    store._saft_summary = {  # type: ignore[attr-defined]
        "eiendeler_UB_brreg": 1100.0,
        "egenkapital_UB": 500.0,
        "gjeld_UB_brreg": 600.0,
    }
    store._brreg_map = {  # type: ignore[attr-defined]
        "eiendeler_UB": 1000.0,
        "egenkapital_UB": 500.0,
        "gjeld_UB": 600.0,
    }
    store._saft_df = pd.DataFrame(  # type: ignore[attr-defined]
        {
            "Konto": ["1920"],
            "Kontonavn": ["Bank"],
            "UB_netto": [100.0],
        }
    )

    handler = PageStateHandler(store, {}, lambda: None)

    result = handler.build_brreg_comparison_rows()
    assert result is not None
    rows, suggestions = result

    assets_row = next(row for row in rows if row[0] == "Eiendeler")
    _, saf_value, brreg_value, diff = assets_row

    assert saf_value == pytest.approx(1100.0)
    assert brreg_value == pytest.approx(1000.0)
    assert diff == pytest.approx(100.0)
    assert suggestions
    assert any("1920" in text for text in suggestions)


def test_build_brreg_comparison_rows_finds_combination(_qapp: QApplication) -> None:
    store = SaftDatasetStore()
    store._saft_summary = {  # type: ignore[attr-defined]
        "eiendeler_UB_brreg": 200.0,
        "egenkapital_UB": 0.0,
        "gjeld_UB_brreg": 0.0,
    }
    store._brreg_map = {  # type: ignore[attr-defined]
        "eiendeler_UB": 50.0,
        "egenkapital_UB": 0.0,
        "gjeld_UB": 0.0,
    }
    store._saft_df = pd.DataFrame(  # type: ignore[attr-defined]
        {
            "Konto": ["1900", "1910"],
            "Kontonavn": ["Bank A", "Bank B"],
            "UB_netto": [80.0, 70.5],
        }
    )

    handler = PageStateHandler(store, {}, lambda: None)

    result = handler.build_brreg_comparison_rows()
    assert result is not None
    rows, suggestions = result

    assets_row = next(row for row in rows if row[0] == "Eiendeler")
    _, saf_value, brreg_value, diff = assets_row

    assert saf_value == pytest.approx(200.0)
    assert brreg_value == pytest.approx(50.0)
    assert diff == pytest.approx(150.0)
    assert any("1900" in text and "1910" in text for text in suggestions)
