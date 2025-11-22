from types import SimpleNamespace
from pathlib import Path

from nordlys.saft import loader


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
