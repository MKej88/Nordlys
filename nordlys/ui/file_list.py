"""Hjelpefunksjoner for å vise filnavn i UI-komponenter."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

__all__ = ["format_file_list"]


def format_file_list(file_paths: Sequence[str]) -> str | None:
    """Lag en kort punktliste over filer som lastes uten å fylle hele dialogen."""

    if not file_paths:
        return None

    names = [Path(path).name for path in file_paths]
    max_visible = 6
    overflow = len(names) - max_visible
    displayed = names[:max_visible]
    if overflow > 0:
        displayed.append(f"… og {overflow} til")

    bullet_lines = "\n".join(f"• {name}" for name in displayed)
    return f"Filer som lastes:\n{bullet_lines}"
