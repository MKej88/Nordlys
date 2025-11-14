from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtGui import QIcon

__all__ = [
    "SAFT_STREAMING_ENABLED",
    "SAFT_STREAMING_VALIDATE",
    "REVISION_TASKS",
    "NAV_ICON_FILENAMES",
    "PRIMARY_UI_FONT_FAMILY",
    "icon_for_navigation",
]


def _env_flag(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "ja", "on", "yes"}


SAFT_STREAMING_ENABLED = _env_flag("NORDLYS_SAFT_STREAMING")
SAFT_STREAMING_VALIDATE = _env_flag("NORDLYS_SAFT_STREAMING_VALIDATE")

REVISION_TASKS: Dict[str, List[str]] = {
    "rev.innkjop": [
        "Avstem leverandørreskontro mot hovedbok",
        "Analysér kredittider og identifiser avvik",
        "Undersøk store engangskjøp",
    ],
    "rev.lonn": [
        "Kontroller lønnsarter og arbeidsgiveravgift",
        "Stem av mot a-meldinger",
        "Bekreft feriepengene",
    ],
    "rev.kostnad": [
        "Kartlegg større kostnadsdrivere",
        "Analyser periodiseringer",
        "Vurder avgrensninger mot investeringer",
    ],
    "rev.driftsmidler": [
        "Bekreft nyanskaffelser",
        "Stem av avskrivninger mot regnskap",
        "Test disposisjoner ved salg/utrangering",
    ],
    "rev.finans": [
        "Avstem bank og lånesaldo",
        "Test renteberegning og covenants",
        "Bekreft finansielle instrumenter",
    ],
    "rev.varelager": [
        "Vurder telling og lagerforskjeller",
        "Test nedskrivninger",
        "Analyser bruttomarginer",
    ],
    "rev.salg": [
        "Analysér omsetning mot kunderegister",
        "Bekreft vesentlige kontrakter",
        "Test cut-off rundt periodeslutt",
    ],
    "rev.mva": [
        "Stem av mva-koder mot innleverte oppgaver",
        "Kontroller mva-grunnlag",
        "Verifiser justeringer og korrigeringer",
    ],
}

NAV_ICON_FILENAMES: Dict[str, str] = {
    "import": "import.svg",
    "dashboard": "dashboard.svg",
    "plan.saldobalanse": "balance-scale.svg",
    "plan.kontroll": "shield-check.svg",
    "plan.regnskapsanalyse": "analytics.svg",
    "plan.vesentlighet": "target.svg",
    "plan.sammenstilling": "layers.svg",
    "rev.innkjop": "shopping-bag.svg",
    "rev.lonn": "people.svg",
    "rev.kostnad": "chart-pie.svg",
    "rev.driftsmidler": "factory.svg",
    "rev.finans": "bank.svg",
    "rev.varelager": "boxes.svg",
    "rev.salg": "trend-up.svg",
    "rev.mva": "percent.svg",
}

PRIMARY_UI_FONT_FAMILY = "Roboto"

_ICON_CACHE: Dict[str, Optional[QIcon]] = {}


def icon_for_navigation(key: str) -> Optional[QIcon]:
    """Returnerer ikon for navigasjonsnøkkelen dersom tilgjengelig."""

    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    filename = NAV_ICON_FILENAMES.get(key)
    if not filename:
        _ICON_CACHE[key] = None
        return None

    icon_path = Path(__file__).resolve().parent.parent / "resources" / "icons" / filename
    if not icon_path.exists():
        _ICON_CACHE[key] = None
        return None

    icon = QIcon(str(icon_path))
    _ICON_CACHE[key] = icon
    return icon
