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


def test_build_stylesheet_includes_secondary_button_style() -> None:
    stylesheet = build_stylesheet()

    assert "QPushButton[secondary='true']" in stylesheet


def test_build_stylesheet_includes_invalid_input_state() -> None:
    stylesheet = build_stylesheet()

    assert "QLineEdit[invalid='true']" in stylesheet


def test_build_stylesheet_includes_ghost_button_variant() -> None:
    stylesheet = build_stylesheet()

    assert "QPushButton[variant='ghost']" in stylesheet


def test_build_stylesheet_includes_groupbox_style() -> None:
    stylesheet = build_stylesheet()

    assert "QGroupBox::title" in stylesheet


def test_build_stylesheet_includes_combo_focus_state() -> None:
    stylesheet = build_stylesheet()

    assert "QComboBox:focus" in stylesheet
