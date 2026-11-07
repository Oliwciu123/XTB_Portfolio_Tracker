"""CLI: python -m xtb_analyzer [--data-dir data] [--output-dir output] [--currency pln]"""

from __future__ import annotations

import argparse
import sys
import webbrowser

from xtb_analyzer.report import generate_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xtb_analyzer",
        description="Generate an interactive HTML portfolio report from XTB exports (XLSX/CSV).",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="directory containing XTB cash-operation exports (default: data)",
    )
    parser.add_argument(
        "--output-dir", default="output", help="report output directory (default: output)"
    )
    parser.add_argument(
        "--currency", default="pln", choices=["pln", "usd", "eur"], help="report currency"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="skip reading and writing the price and FX cache"
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="disable live quotes (historical data can still require a network connection)",
    )
    parser.add_argument(
        "--open", action="store_true", help="open the generated report in a browser"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate an offline report using fictional exports and market data in examples/.",
    )
    parser.epilog = "Desktop app (ZIP import): python -m xtb_analyzer.desktop"
    args = parser.parse_args(argv)

    try:
        from xtb_analyzer.market_data import MarketData

        data_dir = "examples" if args.demo and args.data_dir == "data" else args.data_dir
        path = generate_report(
            data_dir=data_dir,
            output_dir=args.output_dir,
            currency=args.currency,
            use_cache=not args.no_cache,
            refresh_latest=not args.no_live,
            market_data=MarketData.from_examples(data_dir) if args.demo else None,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Report saved: {path.resolve()}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
