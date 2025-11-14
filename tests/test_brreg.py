from __future__ import annotations

from nordlys import brreg
from nordlys.brreg import find_first_by_exact_endkey, map_brreg_metrics
from nordlys.integrations.brreg_service import BrregServiceResult


def test_find_first_by_exact_endkey():
    data = {
        "resultatregnskap": {
            "sumDriftsinntekter": 123,
            "arsresultat": 45,
        },
        "balanse": {
            "sumEiendeler": 1000,
            "egenkapitalOgGjeld": {
                "sumEgenkapital": 400,
                "sumGjeld": 600,
            },
            "poster": [
                {"sumGjeld": 50},
                {"sumGjeld": 70},
            ],
        },
    }
    hit = find_first_by_exact_endkey(data, ["sumDriftsinntekter"])
    assert hit == ("resultatregnskap.sumDriftsinntekter", 123)

    list_hit = find_first_by_exact_endkey(data, ["sumGjeld"])
    assert list_hit == ("balanse.egenkapitalOgGjeld.sumGjeld", 600)


def test_find_first_by_exact_endkey_disallow_contains():
    data = {
        "balanse": {
            "egenkapitalOgGjeld": {
                "sumEgenkapital": 400,
            },
            "egenkapital": {
                "sumEgenkapital": 380,
            },
        }
    }

    hit = find_first_by_exact_endkey(
        data,
        ["sumEgenkapital"],
        disallow_contains=["egenkapitaloggjeld"],
    )

    assert hit == ("balanse.egenkapital.sumEgenkapital", 380.0)


def test_map_brreg_metrics():
    data = {
        "resultatregnskap": {
            "sumDriftsinntekter": 123,
            "arsresultat": 45,
            "driftsresultatFoerFinans": 40,
        },
        "balanse": {
            "sumEiendeler": 1000,
            "egenkapitalOgGjeld": {
                "sumEgenkapital": 400,
                "sumGjeld": 600,
            },
        },
    }
    mapped = map_brreg_metrics(data)
    assert mapped["eiendeler_UB"] == 1000
    assert mapped["egenkapital_UB"] == 400
    assert mapped["gjeld_UB"] == 600
    assert mapped["driftsinntekter"] == 123
    assert mapped["arsresultat"] == 45
    assert mapped["ebit"] == 40


def test_fetch_brreg_timeout(monkeypatch):
    def fake_fetch(orgnr: str) -> BrregServiceResult:
        return BrregServiceResult(
            data=None,
            error_code="timeout",
            error_message="Regnskapsregisteret: tidsavbrudd.",
            from_cache=False,
        )

    monkeypatch.setattr(brreg, "fetch_regnskapsregister", fake_fetch)

    data, error = brreg.fetch_brreg("123456789")

    assert data is None
    assert "tidsavbrudd" in error.lower()
