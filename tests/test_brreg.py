from __future__ import annotations

from nordlys.brreg import find_first_by_exact_endkey, map_brreg_metrics


def test_find_first_by_exact_endkey():
    data = {
        'resultatregnskap': {
            'sumDriftsinntekter': 123,
            'arsresultat': 45,
        },
        'balanse': {
            'sumEiendeler': 1000,
            'egenkapitalOgGjeld': {
                'sumEgenkapital': 400,
                'sumGjeld': 600,
            },
            'poster': [
                {'sumGjeld': 50},
                {'sumGjeld': 70},
            ],
        },
    }
    hit = find_first_by_exact_endkey(data, ['sumDriftsinntekter'])
    assert hit == ('resultatregnskap.sumDriftsinntekter', 123)

    list_hit = find_first_by_exact_endkey(data, ['sumGjeld'])
    assert list_hit == ('balanse.egenkapitalOgGjeld.sumGjeld', 600)


def test_map_brreg_metrics():
    data = {
        'resultatregnskap': {
            'sumDriftsinntekter': 123,
            'arsresultat': 45,
            'driftsresultatFoerFinans': 40,
        },
        'balanse': {
            'sumEiendeler': 1000,
            'egenkapitalOgGjeld': {
                'sumEgenkapital': 400,
                'sumGjeld': 600,
            },
        },
    }
    mapped = map_brreg_metrics(data)
    assert mapped['eiendeler_UB'] == 1000
    assert mapped['egenkapital_UB'] == 400
    assert mapped['gjeld_UB'] == 600
    assert mapped['driftsinntekter'] == 123
    assert mapped['arsresultat'] == 45
    assert mapped['ebit'] == 40
