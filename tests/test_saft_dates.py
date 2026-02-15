from datetime import date

from nordlys.saft import dates


def test_parse_saft_date_parses_common_formats() -> None:
    assert dates.parse_saft_date("2023-12-31") == date(2023, 12, 31)
    assert dates.parse_saft_date("31.12.2023") == date(2023, 12, 31)
    assert dates.parse_saft_date("20231231") == date(2023, 12, 31)


def test_parse_saft_date_uses_cache_for_repeated_values() -> None:
    dates._parse_saft_date_cached.cache_clear()

    dates.parse_saft_date("2023-12-31")
    dates.parse_saft_date("2023-12-31")
    cache_info = dates._parse_saft_date_cached.cache_info()

    assert cache_info.hits >= 1
    assert cache_info.currsize >= 1
