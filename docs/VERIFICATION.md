# Verification record

Checked on 2026-11-07 on Windows with CPython 3.13.1 and uv 0.12.5.

## Seeded demo

The committed seed-42 scenario spans 2021-01-01 to 2026-11-06 (the last business
day before generation), with 15 instruments and 284 operations. It includes
72 external deposits, four withdrawals, internal currency conversions, income,
taxes, fees and both profitable and loss-making sales. All figures are fictional.

- Final NAV: 224,950.98 PLN.
- Gross deposits: 279,484.21 PLN; withdrawals: 11,548.35 PLN.
- ROI: -15.38%; cumulative TWR: -25.34%; annualized XIRR: -4.32%.
- Raw NAV maximum drawdown: -34.19% (affected by external cash flows).
- TWR wealth-index maximum drawdown: -52.54% (funding-neutral).

Tests independently reconcile the final cash/share ledger, substitute XIRR into
NPV, compound daily TWR, and regenerate every example file twice with the same
seed and end date. Losses and drawdowns are deliberately retained.

## Clean clone commands

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run xtb-analyzer --demo
uv run playwright install chromium
uv run python scripts/make_screenshots.py
```

The final tree is checked from a fresh local clone with an empty virtual
environment. Native Tk tests can skip when Windows cannot initialize a display;
financial tests and Chromium rendering do not require a visible desktop.

## Real screenshots

The report is rendered at a 1600x1000 viewport and device scale 2, after all nine
Plotly figures finish rendering. Screenshots exercise the one-week range and
reset, verify fixed categorical charts, and reject JavaScript page errors.
HTTP(S) requests are blocked. The overview shows KPIs and NAV above the fold;
three section captures replace the old full-page image. Every PNG is below 1 MB.

On Windows, `uv run --extra desktop python scripts/make_screenshots.py --native`
launches the actual start screen and `xtb_analyzer.desktop --demo`, waits for the
WebView DOM/Plotly readiness signal, and captures their verified process HWNDs
with Windows Graphics Capture. Both native client areas are 1600x1000, without
browser chrome. No desktop-region fallback is allowed. These images were visually
reviewed and are actual native windows, not HTML stand-ins.
The capture backend follows the [Windows Capture API](https://github.com/NiiightmareXD/windows-capture/tree/main/windows-capture-python).

## Privacy, history and platforms

`backup/pre-rewrite` preserves the already-sanitized prior history locally. The
consolidated main uses actual feature dates, including August for XIRR/TWR. The
intended final tree is compared to the rewritten tip. All referenced commits and
expanded ZIP/XLSX contents are scanned for known original identifiers and common
credential patterns; every commit patch is scanned as well.

No push or visibility change is performed. Ubuntu/macOS and Python 3.10 are
configured in CI; remote CI runs require the owner's push. This session validates
the source desktop app, not a newly signed installer or every market-data service.
