"""Beregninger knyttet til saldobalanse og NS4102-rapportering."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from ..constants import NS
from ..helpers import lazy_pandas, text_or_none, to_float

if TYPE_CHECKING:  # pragma: no cover - kun for typekontroll
    import numpy as np
    import pandas as pd

__all__ = ["parse_saldobalanse", "ns4102_summary_from_tb"]

pd = lazy_pandas()
_NUMPY: Optional[Any] = None


def _lazy_numpy() -> Any:
    """Laster ``numpy`` først når funksjoner som trenger det kjøres."""

    global _NUMPY
    if _NUMPY is None:
        import numpy as _np  # type: ignore[import-not-found]

        _NUMPY = cast(Any, _np)
    return _NUMPY


def parse_saldobalanse(root: ET.Element) -> "pd.DataFrame":
    """Returnerer saldobalansen som Pandas DataFrame."""

    if pd is None:
        raise RuntimeError("Pandas er ikke tilgjengelig for saldobalanse-parsing.")

    gl = root.find("n1:MasterFiles/n1:GeneralLedgerAccounts", NS)
    accounts = gl.iterfind("n1:Account", NS) if gl is not None else ()

    def get(acct: ET.Element, tag: str) -> Optional[str]:
        return text_or_none(acct.find(f"n1:{tag}", NS))

    konto_pattern = re.compile(r"-?\d+")

    def konto_to_int(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        match = konto_pattern.search(value)
        if not match:
            return None
        try:
            return int(match.group())
        except ValueError:
            return None

    konto_values: List[Optional[str]] = []
    navn_values: List[str] = []
    ib_debet_values: List[float] = []
    ib_kredit_values: List[float] = []
    endring_debet_values: List[float] = []
    endring_kredit_values: List[float] = []
    ub_debet_values: List[float] = []
    ub_kredit_values: List[float] = []
    ib_netto_values: List[float] = []
    ub_netto_values: List[float] = []
    konto_int_values: List[Optional[int]] = []

    for account in accounts:
        konto = get(account, "AccountID")
        navn = get(account, "AccountDescription") or ""
        opening_debit = to_float(get(account, "OpeningDebitBalance"))
        opening_credit = to_float(get(account, "OpeningCreditBalance"))
        closing_debit = to_float(get(account, "ClosingDebitBalance"))
        closing_credit = to_float(get(account, "ClosingCreditBalance"))

        ib_netto = opening_debit - opening_credit
        ub_netto = closing_debit - closing_credit
        endring = ub_netto - ib_netto

        konto_values.append(konto)
        navn_values.append(navn)
        ib_debet_values.append(opening_debit)
        ib_kredit_values.append(opening_credit)
        endring_debet_values.append(endring if endring > 0 else 0.0)
        endring_kredit_values.append(-endring if endring < 0 else 0.0)
        ub_debet_values.append(closing_debit)
        ub_kredit_values.append(closing_credit)
        ib_netto_values.append(ib_netto)
        ub_netto_values.append(ub_netto)
        konto_int_values.append(konto_to_int(konto))

    data = {
        "Konto": konto_values,
        "Kontonavn": navn_values,
        "IB Debet": ib_debet_values,
        "IB Kredit": ib_kredit_values,
        "Endring Debet": endring_debet_values,
        "Endring Kredit": endring_kredit_values,
        "UB Debet": ub_debet_values,
        "UB Kredit": ub_kredit_values,
        "IB_netto": ib_netto_values,
        "UB_netto": ub_netto_values,
        "Konto_int": konto_int_values,
    }

    return pd.DataFrame(data, columns=list(data.keys()))


def ns4102_summary_from_tb(df: "pd.DataFrame") -> Dict[str, float]:
    """Utleder nøkkeltall basert på saldobalansen."""

    mask = df["Konto_int"].notna()
    if not mask.any():
        return {
            "driftsinntekter": 0.0,
            "varekostnad": 0.0,
            "lonn": 0.0,
            "avskrivninger": 0.0,
            "andre_drift": 0.0,
            "ebitda": 0.0,
            "ebit": 0.0,
            "finans_netto": 0.0,
            "skattekostnad": 0.0,
            "ebt": 0.0,
            "arsresultat": 0.0,
            "eiendeler_UB": 0.0,
            "egenkapital_UB": 0.0,
            "gjeld_UB": 0.0,
            "balanse_diff": 0.0,
            "eiendeler_UB_brreg": 0.0,
            "gjeld_UB_brreg": 0.0,
            "balanse_diff_brreg": 0.0,
            "liab_debet_21xx_29xx": 0.0,
        }

    subset = df.loc[mask]
    np = _lazy_numpy()

    konto_values = subset["Konto_int"].astype(int).to_numpy()
    order = np.argsort(konto_values)
    konto_sorted = konto_values[order]

    ib_debet = subset["IB Debet"].fillna(0.0).to_numpy()
    ib_kredit = subset["IB Kredit"].fillna(0.0).to_numpy()
    ub_debet = subset["UB Debet"].fillna(0.0).to_numpy()
    ub_kredit = subset["UB Kredit"].fillna(0.0).to_numpy()

    ib_values = ib_debet - ib_kredit
    ub_values = ub_debet - ub_kredit
    end_values = ub_values - ib_values

    end_sorted = end_values[order]
    ub_sorted = ub_values[order]

    end_prefix = np.cumsum(end_sorted)
    ub_prefix = np.cumsum(ub_sorted)

    def _sum_with_prefix(prefix: Any, start: int, stop: int) -> float:
        left = int(np.searchsorted(konto_sorted, start, side="left"))
        right = int(np.searchsorted(konto_sorted, stop, side="right")) - 1
        if left > right:
            return 0.0
        total = prefix[right]
        if left > 0:
            total -= prefix[left - 1]
        return float(total)

    def sum_end(start: int, stop: int) -> float:
        return _sum_with_prefix(end_prefix, start, stop)

    def sum_ub(start: int, stop: int) -> float:
        return _sum_with_prefix(ub_prefix, start, stop)

    driftsinntekter = -sum_end(3000, 3999)
    varekostnad = sum_end(4000, 4999)
    lonn = sum_end(5000, 5999)
    avskr = sum_end(6000, 6099) + sum_end(7800, 7899)
    andre_drift = sum_end(6100, 7999) - sum_end(7800, 7899)
    ebitda = driftsinntekter - (varekostnad + lonn + andre_drift)
    ebit = ebitda - avskr
    finans = -(sum_end(8000, 8299) + sum_end(8400, 8899))
    skatt = sum_end(8300, 8399)
    ebt = ebit + finans
    arsresultat = ebt - skatt
    anlegg_UB = sum_ub(1000, 1399)
    omlop_UB = sum_ub(1400, 1999)
    eiendeler_netto = anlegg_UB + omlop_UB
    egenkap_UB = -sum_ub(2000, 2099)
    liab_mask = (konto_values >= 2100) & (konto_values <= 2999)
    liab_values = ub_values[liab_mask]
    liab_kreditt = float(-liab_values[liab_values < 0].sum())
    liab_debet = float(liab_values[liab_values > 0].sum())
    gjeld_netto = liab_kreditt - liab_debet
    balanse_diff_netto = eiendeler_netto - (egenkap_UB + gjeld_netto)
    eiendeler_brreg = eiendeler_netto + liab_debet
    gjeld_brreg = liab_kreditt
    balanse_diff_brreg = eiendeler_brreg - (egenkap_UB + gjeld_brreg)

    return {
        "driftsinntekter": driftsinntekter,
        "varekostnad": varekostnad,
        "lonn": lonn,
        "avskrivninger": avskr,
        "andre_drift": andre_drift,
        "ebitda": ebitda,
        "ebit": ebit,
        "finans_netto": finans,
        "skattekostnad": skatt,
        "ebt": ebt,
        "arsresultat": arsresultat,
        "eiendeler_UB": eiendeler_netto,
        "egenkapital_UB": egenkap_UB,
        "gjeld_UB": gjeld_netto,
        "balanse_diff": balanse_diff_netto,
        "eiendeler_UB_brreg": eiendeler_brreg,
        "gjeld_UB_brreg": gjeld_brreg,
        "balanse_diff_brreg": balanse_diff_brreg,
        "liab_debet_21xx_29xx": float(liab_debet),
    }
