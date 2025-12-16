from __future__ import annotations

from typing import List


def test_progress_animator_moves_while_idle(
    dummy_pyside6: None, monkeypatch
) -> None:
    import nordlys.ui.progress_display as progress_display

    times: List[float] = [0.0]

    def advance(delta: float) -> None:
        times[0] += delta

    def fake_monotonic() -> float:
        return times[0]

    monkeypatch.setattr(progress_display.time, "monotonic", fake_monotonic)

    widget = progress_display.QWidget()
    recorded: List[int] = []
    animator = progress_display._ProgressAnimator(recorded.append, widget)

    animator.report_progress(20)
    animator._on_tick()

    advance(2.0)
    for _ in range(10):
        advance(0.5)
        animator._on_tick()

    assert max(recorded) > 20

    advance(20.0)
    for _ in range(150):
        advance(0.5)
        animator._on_tick()

    assert recorded[-1] >= 99
