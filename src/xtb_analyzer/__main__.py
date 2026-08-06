"""CLI: python -m xtb_analyzer [--data-dir data] [--output-dir output] [--currency pln]"""

from __future__ import annotations

import argparse
import sys
import webbrowser

from xtb_analyzer.report import generate_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xtb_analyzer",
        description="Generuje interaktywny raport HTML z eksportów XTB (XLSX/CSV).",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="folder z XTB_USD_cs.xlsx / XTB_EURO_cs.xlsx (domyślnie: data)",
    )
    parser.add_argument("--output-dir", default="output", help="folder wynikowy (domyślnie: output)")
    parser.add_argument("--currency", default="pln", choices=["pln", "usd", "eur"], help="waluta raportu")
    parser.add_argument("--no-cache", action="store_true", help="pomiń cache cen i kursów")
    parser.add_argument("--no-live", action="store_true", help="nie pobieraj bieżących notowań")
    parser.add_argument("--open", action="store_true", help="otwórz raport w przeglądarce po wygenerowaniu")
    args = parser.parse_args(argv)

    try:
        path = generate_report(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            currency=args.currency,
            use_cache=not args.no_cache,
            refresh_latest=not args.no_live,
        )
    except FileNotFoundError as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1

    print(f"Raport zapisany: {path.resolve()}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
