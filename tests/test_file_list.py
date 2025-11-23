from nordlys.ui.file_list import format_file_list


def test_format_file_list_empty_returns_none() -> None:
    assert format_file_list([]) is None


def test_format_file_list_shows_basenames() -> None:
    text = format_file_list(["/tmp/data/a.xml", "b.xml"])

    assert text is not None
    assert text.startswith("Filer som lastes:")
    assert "a.xml" in text and "b.xml" in text


def test_format_file_list_truncates_and_counts_overflow() -> None:
    files = [f"/tmp/file_{index}.xml" for index in range(8)]
    text = format_file_list(files)

    assert text is not None
    assert "… og 2 til" in text
    assert text.count("•") == 7
    assert "file_6.xml" not in text and "file_7.xml" not in text
