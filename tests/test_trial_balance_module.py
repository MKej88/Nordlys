from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from nordlys.saft import trial_balance


def test_compute_trial_balance_handles_none(monkeypatch, tmp_path):
    dummy_file = tmp_path / "dummy.xml"
    dummy_file.write_text("innhold")

    monkeypatch.setattr(trial_balance, "SAFT_STREAMING_ENABLED", True)
    monkeypatch.setattr(trial_balance, "SAFT_STREAMING_VALIDATE", False)
    monkeypatch.setattr(
        trial_balance.saft, "check_trial_balance", lambda *args, **kwargs: None
    )

    result = trial_balance.compute_trial_balance(str(dummy_file))

    assert result.balance is None
    assert result.error is not None
    assert Path(dummy_file).name in result.error
    assert "mottok ingen data" in result.error


def test_compute_trial_balance_handles_missing_diff(monkeypatch, tmp_path):
    dummy_file = tmp_path / "dummy_missing_diff.xml"
    dummy_file.write_text("innhold")

    monkeypatch.setattr(trial_balance, "SAFT_STREAMING_ENABLED", True)
    monkeypatch.setattr(trial_balance, "SAFT_STREAMING_VALIDATE", False)
    monkeypatch.setattr(
        trial_balance.saft,
        "check_trial_balance",
        lambda *args, **kwargs: {"debet": Decimal("1.0"), "kredit": Decimal("1.0")},
    )

    result = trial_balance.compute_trial_balance(str(dummy_file))

    assert result.balance is None
    assert result.error is not None
    assert "manglet diff-felt" in result.error
