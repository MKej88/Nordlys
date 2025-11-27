from nordlys.ui.styles import build_stylesheet


def test_build_stylesheet_scales_down_font_size() -> None:
    original = build_stylesheet(1.0)
    scaled = build_stylesheet(0.9)

    assert "font-size: 14px;" in original
    assert "font-size: 13px;" in scaled


def test_build_stylesheet_scales_padding_values() -> None:
    scaled = build_stylesheet(0.9)

    assert "padding: 9px 18px;" in scaled


def test_zero_values_are_preserved() -> None:
    scaled = build_stylesheet(0.9)

    assert "padding-bottom: 0px;" in scaled
