from __future__ import annotations

import pandas as pd
import pytest

from nordlys.regnskap import (
    AnalysisRow,
    compute_balance_analysis,
    compute_result_analysis,
    prepare_regnskap_dataframe,
)
from nordlys.regnskap.analysis import _clean_value


def build_sample_tb() -> pd.DataFrame:
    rows = [
        {"Konto": "1000", "Kontonavn": "Immaterielle", "IB Debet": 50, "UB Debet": 60},
        {"Konto": "1100", "Kontonavn": "Tomter", "IB Debet": 100, "UB Debet": 120},
        {"Konto": "1200", "Kontonavn": "Maskiner", "IB Debet": 80, "UB Debet": 90},
        {
            "Konto": "1300",
            "Kontonavn": "Finansielle anlegg",
            "IB Debet": 40,
            "UB Debet": 55,
        },
        {"Konto": "1400", "Kontonavn": "Varelager", "IB Debet": 200, "UB Debet": 220},
        {
            "Konto": "1500",
            "Kontonavn": "Kundefordringer",
            "IB Debet": 150,
            "UB Debet": 180,
        },
        {"Konto": "1580", "Kontonavn": "Avsetning tap", "IB Debet": 20, "UB Debet": 30},
        {
            "Konto": "1505",
            "Kontonavn": "Andre fordringer",
            "IB Debet": 30,
            "UB Debet": 40,
        },
        {"Konto": "1600", "Kontonavn": "MVA", "IB Debet": 10, "UB Debet": 15},
        {"Konto": "1700", "Kontonavn": "Forskudd", "IB Debet": 5, "UB Debet": 7},
        {"Konto": "1800", "Kontonavn": "Finansielle", "IB Debet": 12, "UB Debet": 20},
        {"Konto": "1900", "Kontonavn": "Bank", "IB Debet": 300, "UB Debet": 350},
        {
            "Konto": "2000",
            "Kontonavn": "Egenkapital",
            "IB Kredit": 750,
            "UB Kredit": 892,
        },
        {"Konto": "2100", "Kontonavn": "Avsetning", "IB Kredit": 28, "UB Kredit": 25},
        {
            "Konto": "2200",
            "Kontonavn": "Langsiktig gjeld",
            "IB Kredit": 80,
            "UB Kredit": 100,
        },
        {
            "Konto": "2300",
            "Kontonavn": "Kortsiktig gjeld",
            "IB Kredit": 50,
            "UB Kredit": 70,
        },
        {
            "Konto": "2400",
            "Kontonavn": "Leverandørgjeld",
            "IB Kredit": 40,
            "UB Kredit": 50,
        },
        {
            "Konto": "2500",
            "Kontonavn": "Skyldig skattetrekk",
            "IB Kredit": 20,
            "UB Kredit": 15,
        },
        {
            "Konto": "2900",
            "Kontonavn": "Annen kortsiktig gjeld",
            "IB Kredit": 29,
            "UB Kredit": 35,
        },
        {
            "Konto": "3000",
            "Kontonavn": "Salgsinntekter",
            "IB Kredit": 900,
            "UB Kredit": 1000,
        },
        {
            "Konto": "3800",
            "Kontonavn": "Annen inntekt",
            "IB Kredit": 40,
            "UB Kredit": 50,
        },
        {
            "Konto": "3900",
            "Kontonavn": "Annen inntekt",
            "IB Kredit": 10,
            "UB Kredit": 20,
        },
        {"Konto": "4000", "Kontonavn": "Varekost", "IB Debet": 500, "UB Debet": 550},
        {"Konto": "5000", "Kontonavn": "Lønn", "IB Debet": 200, "UB Debet": 220},
        {"Konto": "6000", "Kontonavn": "Avskrivning", "IB Debet": 150, "UB Debet": 160},
        {
            "Konto": "6100",
            "Kontonavn": "Andre driftskost",
            "IB Debet": 80,
            "UB Debet": 90,
        },
        {"Konto": "7000", "Kontonavn": "Annen kost", "IB Debet": 60, "UB Debet": 65},
        {
            "Konto": "8000",
            "Kontonavn": "Finansinntekt",
            "IB Kredit": 30,
            "UB Kredit": 40,
        },
        {"Konto": "8100", "Kontonavn": "Finanskost", "IB Debet": 25, "UB Debet": 35},
        {"Konto": "8300", "Kontonavn": "Skatt", "IB Kredit": 15, "UB Kredit": 18},
    ]

    for row in rows:
        row.setdefault("IB Debet", 0.0)
        row.setdefault("IB Kredit", 0.0)
        row.setdefault("UB Debet", 0.0)
        row.setdefault("UB Kredit", 0.0)

    return pd.DataFrame(rows)


def row_by_label(rows: list[AnalysisRow], label: str) -> AnalysisRow:
    for row in rows:
        if row.label == label:
            return row
    raise AssertionError(f"Fant ikke rad: {label}")


def test_prepare_regnskap_dataframe_builds_expected_columns():
    df = build_sample_tb()
    prepared = prepare_regnskap_dataframe(df)
    assert set(["konto", "navn", "IB", "endring", "UB", "forrige"]).issubset(
        prepared.columns
    )
    first = prepared.iloc[0]
    assert first["konto"] == "1000"
    assert pytest.approx(first["UB"], rel=1e-6) == 60
    assert pytest.approx(first["forrige"], rel=1e-6) == 50


def test_prepare_regnskap_dataframe_handles_missing_text_columns():
    df = pd.DataFrame(
        [
            {
                "IB Debet": 10.0,
                "IB Kredit": 0.0,
                "UB Debet": 12.0,
                "UB Kredit": 0.0,
            }
        ]
    )

    prepared = prepare_regnskap_dataframe(df)

    assert prepared.loc[0, "konto"] == ""
    assert prepared.loc[0, "navn"] == ""
    assert prepared.loc[0, "UB"] == pytest.approx(12.0)


def test_compute_balance_analysis_matches_expected_totals():
    prepared = prepare_regnskap_dataframe(build_sample_tb())
    rows = compute_balance_analysis(prepared)

    immaterielle = row_by_label(rows, "Immaterielle eiendeler")
    assert immaterielle.current == pytest.approx(60)
    assert immaterielle.previous == pytest.approx(50)

    kundefordr = row_by_label(rows, "Kundefordringer")
    assert kundefordr.current == pytest.approx(210)
    assert kundefordr.previous == pytest.approx(170)

    korts_fordringer = row_by_label(rows, "Andre kortsiktige fordringer")
    assert korts_fordringer.current == pytest.approx(40)
    assert korts_fordringer.previous == pytest.approx(30)

    kortsiktig_gjeld = row_by_label(rows, "Sum kortsiktig gjeld")
    assert kortsiktig_gjeld.current == pytest.approx(170)
    assert kortsiktig_gjeld.previous == pytest.approx(139)

    sum_eiendeler = row_by_label(rows, "Sum eiendeler")
    sum_ek_gjeld = row_by_label(rows, "Sum egenkapital og gjeld")
    assert sum_eiendeler.current == pytest.approx(1187)
    assert sum_ek_gjeld.current == pytest.approx(1187)
    assert row_by_label(rows, "Avvik").current == pytest.approx(0)


def test_compute_balance_analysis_uses_cleaned_values_in_totals():
    df = pd.DataFrame(
        [
            {"Konto": "1900", "UB Debet": 0.4},
            {"Konto": "2000", "UB Kredit": 0.4},
        ]
    )

    prepared = prepare_regnskap_dataframe(df)
    rows = compute_balance_analysis(prepared)

    sum_eiendeler = row_by_label(rows, "Sum eiendeler")
    sum_ek_gjeld = row_by_label(rows, "Sum egenkapital og gjeld")
    avvik = row_by_label(rows, "Avvik")

    assert sum_eiendeler.current == 0.0
    assert sum_ek_gjeld.current == 0.0
    assert avvik.current == 0.0


def test_compute_result_analysis_calculates_income_statement_lines():
    prepared = prepare_regnskap_dataframe(build_sample_tb())
    rows = compute_result_analysis(prepared)

    annen_inntekt = row_by_label(rows, "Annen inntekt")
    assert annen_inntekt.current == pytest.approx(70)
    assert annen_inntekt.previous == pytest.approx(50)

    salgsinntekter = row_by_label(rows, "Salgsinntekter")
    assert salgsinntekter.current == pytest.approx(1000)
    assert salgsinntekter.previous == pytest.approx(900)

    sum_inntekter = row_by_label(rows, "Sum inntekter")
    assert sum_inntekter.current == pytest.approx(1070)
    assert sum_inntekter.previous == pytest.approx(950)

    resultat = row_by_label(rows, "Resultat før skatt")
    assert resultat.current == pytest.approx(-10)
    assert resultat.previous == pytest.approx(-35)


def test_compute_result_analysis_rounds_negative_values_to_nearest_integer():
    df = pd.DataFrame(
        [
            {
                "Konto": "4000",
                "Kontonavn": "Varekostnad",
                "IB Debet": 0.0,
                "IB Kredit": 0.0,
                "UB Debet": 100.2,
                "UB Kredit": 0.0,
            },
            {
                "Konto": "5000",
                "Kontonavn": "Lønn",
                "IB Debet": 0.0,
                "IB Kredit": 0.0,
                "UB Debet": 50.0,
                "UB Kredit": 0.0,
            },
        ]
    )

    prepared = prepare_regnskap_dataframe(df)
    rows = compute_result_analysis(prepared)
    resultat = row_by_label(rows, "Resultat før skatt")
    assert resultat.current == -150


def test_clean_value_rounds_negative_numbers_to_nearest_integer():
    """Sikrer symmetrisk avrunding for negative verdier."""

    value = _clean_value(-100.2)

    assert value == -100
