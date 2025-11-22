import nordlys.brreg as brreg


def test_find_numbers_in_nested_structures():
    data = {
        "a": 1,
        "b": [{"c": 2.5}, {"d": "ignored"}],
        "e": {"f": False, "g": 3},
    }

    result = brreg.find_numbers(data)

    assert ("a", 1.0) in result
    assert ("b[0].c", 2.5) in result
    assert ("e.g", 3.0) in result
    assert all(path != "e.f" for path, _ in result)


def test_find_first_by_exact_endkey_respects_disallowed_paths():
    data = {
        "sumEgenkapital": 100,
        "sumEgenkapitalOgGjeld": 250,
    }

    hit = brreg.find_first_by_exact_endkey(
        data,
        ["sumEgenkapital"],
        disallow_contains=["EgenkapitalOgGjeld"],
    )

    assert hit == ("sumEgenkapital", 100.0)


def test_map_brreg_metrics_basic_fields():
    json_obj = {
        "balance": {"sumEiendeler": 42},
        "income": {"driftsinntekter": 300},
        "result": {"resultatEtterSkatt": 12},
    }

    mapped = brreg.map_brreg_metrics(json_obj)

    assert mapped["eiendeler_UB"] == 42
    assert mapped["driftsinntekter"] == 300
    assert mapped["arsresultat"] == 12
