"""Kommandolinjeverktøy for bransjeklassifisering."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Optional

from .industry_groups import classify_from_orgnr, classify_from_saft_path


def main(argv: Optional[list[str]] = None) -> int:
    """Enkel CLI for rask testing fra terminalen."""

    parser = argparse.ArgumentParser(description="Bransjeklassifisering for Nordlys")
    parser.add_argument("--saft", help="Sti til SAF-T XML som skal analyseres")
    parser.add_argument("--orgnr", help="Organisasjonsnummer som skal slås opp")
    parser.add_argument("--navn", help="Overstyr firmanavn ved manuell klassifisering")
    args = parser.parse_args(argv)

    if args.saft:
        classification = classify_from_saft_path(args.saft)
    elif args.orgnr:
        classification = classify_from_orgnr(args.orgnr, args.navn)
    else:
        parser.error("Du må enten oppgi --saft eller --orgnr.")
        return 2

    print(json.dumps(asdict(classification), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI brukes ved behov
    raise SystemExit(main())


__all__ = ["main"]
