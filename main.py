"""Inngangspunkt for Nordlys."""

from __future__ import annotations


def main() -> None:
    """Start programmet med sen import av GUI-modulen."""

    from nordlys.ui.pyside_app import run

    run()


if __name__ == "__main__":
    main()
