from pathlib import Path


def test_logo_svg_exists() -> None:
    logo_path = (
        Path(__file__).resolve().parent.parent
        / "nordlys"
        / "resources"
        / "icons"
        / "nordlys-logo.svg"
    )
    assert logo_path.exists()
    assert "<svg" in logo_path.read_text()
