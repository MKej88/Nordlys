import json

import pytest

from nordlys import industry_groups


def _sample_json(code: str, description: str = "") -> dict:
    return {
        "navn": "Testbedrift AS",
        "naeringskode1": {"kode": code, "beskrivelse": description or "Beskrivelse"},
    }


def test_classify_from_brreg_json_retail() -> None:
    data = _sample_json("47.110", "Butikkhandel")
    result = industry_groups.classify_from_brreg_json("123456789", "Testbutikk AS", data)
    assert result.group == "Salg av varer (detaljhandel)"
    assert result.sn2 == "47"
    assert result.naringskode == "47.110"


def test_name_override_prioritised() -> None:
    data = _sample_json("68.200", "Utleie av egen eller leid fast eiendom")
    result = industry_groups.classify_from_brreg_json("987654321", "Solgløtt Borettslag", data)
    assert result.group == "Borettslag og sameier"


def test_code_zero_maps_to_holding() -> None:
    data = _sample_json("0", "Uspesifisert næringskode")
    result = industry_groups.classify_from_brreg_json("111222333", "Invest AS", data)
    assert result.group == "Holding og investeringsselskap"


def test_secondary_hint_changes_fallback() -> None:
    data = _sample_json("70.100", "Hovedkontortjenester")
    result = industry_groups.classify_from_brreg_json("222333444", "Bygg og Anlegg Konsulent", data)
    assert result.group == "Salg av varer og tjenester"


def test_cache_prevents_double_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(industry_groups, "CACHE_PATH", cache_path)

    calls: list[str] = []

    def fake_fetch(orgnr: str) -> dict:
        calls.append(orgnr)
        return _sample_json("47.910", "Butikkhandel ikke nevnt annet sted")

    monkeypatch.setattr(industry_groups, "fetch_brreg", fake_fetch)

    first = industry_groups.classify_from_orgnr("333444555", "Cache Test AS")
    assert first.group == "Salg av varer (detaljhandel)"
    assert calls == ["333444555"]

    second = industry_groups.classify_from_orgnr("333444555", "Cache Test AS")
    assert second.group == "Salg av varer (detaljhandel)"
    assert calls == ["333444555"], "Forventet at cache hindrer nytt API-kall"

    with cache_path.open("r", encoding="utf-8") as fh:
        cached = json.load(fh)
    assert "333444555" in cached
