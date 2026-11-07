# XTB Portfolio Analyzer

[![CI](https://github.com/Oliwciu123/xtb_portfolio_analyzer/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Oliwciu123/xtb_portfolio_analyzer/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg)](LICENSE)

![Portfolio dashboard: KPIs and reconstructed NAV](docs/images/dashboard.png)

**Turn an XTB account export into an interactive portfolio report.** A Python CLI
and desktop app for investors who want to understand performance across PLN, USD
and EUR accounts. It reconstructs cash and positions, separates investment and
currency effects, and compares results with deposit-matched benchmarks. Try the
offline demo below: every account, transaction, quote and FX rate is fictional.

The seeded demo spans **January 2021–November 2026**, with **15 instruments and
284 cash operations**. It deliberately includes losses and drawdowns. The familiar
tickers and index names label simulated paths, not actual historical returns.

## Features

- ROI, money-weighted return (XIRR) and daily time-weighted return (TWR).
- NAV reconstruction from cash operations, fractional positions and stock splits.
- Volatility, drawdown, Sharpe, Sortino, historical VaR and benchmark relations.
- PLN FX attribution, income, taxes, company P&L and holdings allocation.
- Interactive, self-contained HTML reports with PNG and comparison CSV export.
- Desktop ZIP import, progress feedback and live refresh; custom Yahoo symbols.

## Quickstart

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from
the repository root on Windows, macOS or Linux:

```sh
git clone https://github.com/Oliwciu123/xtb_portfolio_analyzer.git
cd xtb_portfolio_analyzer
uv sync
uv run xtb-analyzer --demo --open
```

The report is written to `output/report.html`. The demo needs no XTB account,
API key or market-data connection after dependencies are installed.

Desktop demo (native webview, optional dependencies):

```sh
uv run --extra desktop xtb-analyzer-desktop --demo
```

For your own export, run `uv run --extra desktop xtb-analyzer-desktop` and choose
an XTB ZIP. Or extract full account workbooks into the ignored `data/` folder:

```sh
uv run xtb-analyzer --data-dir data --currency pln --open
```

Real-data analysis fetches Yahoo Finance prices and NBP FX over the internet.
`--no-live` disables current quotes; it does not disable historical downloads.
See the [user guide](docs/USER_GUIDE.md) for desktop and portable Windows usage.

## Screenshots

Actual application renders using the seeded demo. Browser images are captured at
1600×1000 with 2× pixel density; desktop images capture the real pywebview HWND.

**Reconstructed NAV and funding-neutral drawdown.**
![NAV and TWR drawdown](docs/images/nav-drawdown.png)

**Deposit-matched comparison with four fictional index paths.**
![Returns and benchmarks](docs/images/returns-benchmarks.png)

**Position, currency and sector allocation, excluding cash.**
![Portfolio allocation](docs/images/allocation.png)

**Realized and unrealized position results.**
![Holdings results table](docs/images/holdings-table.png)

**Monthly TWR returns.** These are percentages, not monetary monthly P&L.
![Monthly return heatmap](docs/images/monthly-pnl.png)

**Investment and FX attribution in PLN.**
![FX attribution](docs/images/fx.png)

<details>
<summary>Native desktop windows and report sections</summary>

The actual Windows import screen and the loaded offline report, without browser chrome:
![Native desktop import window](docs/images/desktop-start.png)
![Native desktop dashboard](docs/images/desktop-dashboard.png)

The HTML report is captured in three sections, rather than one long page:
![HTML overview](docs/images/report-overview.png)
![HTML risk section](docs/images/report-risk.png)
![HTML company results section](docs/images/report-holdings.png)

Company price P&L (income is reported separately):
![Company P&L](docs/images/company-pnl.png)

</details>

## How it works

```mermaid
flowchart LR
    A[XTB ZIP / XLSX / CSV] --> B[Normalize cash operations]
    B --> C[Cash, positions and external flows]
    D[Historical prices and FX] --> E[Daily NAV]
    C --> E
    E --> F[Returns, risk and FX attribution]
    F --> G[Interactive HTML report]
    G --> H[Browser or desktop window]
```

## Input format

Use complete xStation account histories with a **CASH OPERATION HISTORY** sheet,
including funding before the first purchase. Account currency is inferred from
`PLN`, `USD`, `EUR` or `EURO` in workbook names. Supported legacy and v2 CSV
cash-operation layouts are covered by parser fixtures. Closed-position summaries
alone cannot reconstruct a portfolio. Localized column aliases remain supported.

[`examples/`](examples/README.md) includes reproducible XLSX/ZIP histories and
fictional market series. Private exports, reports and caches are gitignored.

## Methodology

- **NAV:** cash plus shares × unadjusted price, translated into the report currency.
- **ROI:** `(NAV + withdrawals − gross deposits) / gross deposits`.
- **XIRR:** solves `Σ CFᵢ / (1 + r)^(daysᵢ / 365.25) = 0`, including terminal NAV.
- **TWR:** chains `NAVₜ / (NAVₜ₋₁ + external flowₜ) − 1`; flows are assumed to
  occur at the start of each day.
- **Risk:** daily TWR observations; volatility uses `√252`, default risk-free rate 0%.
- **Benchmarks:** hypothetical purchases and sales with the same external flows,
  converted to the report currency. The comparison chart shows ROI.

Assumptions, FX decomposition and edge cases are in
[METHODOLOGY.md](docs/METHODOLOGY.md). The mathematical audit and the legacy ROI
fix are recorded in [AUDIT.md](docs/AUDIT.md).

## Project structure

```text
src/xtb_analyzer/   Parser, financial engine, report and desktop app
tests/             Reference metrics, parser and UI regression tests
examples/          Entirely fictional account and market data
scripts/           Sample generation and real screenshot capture
packaging/         PyInstaller specification and Windows release builder
docs/              Methodology, user guide, CV material and screenshots
notebooks/         Optional offline exploration of the same engine
```

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run playwright install chromium
uv run python scripts/make_screenshots.py
```

On Windows, capture the actual desktop windows as well:

```sh
uv run --extra desktop python scripts/make_screenshots.py --native
```

Regenerate the demo through today, or pin its end date for byte reproducibility:

```sh
uv run python scripts/generate_demo_data.py --seed 42 --end-date 2026-11-07
```

Small parser fixtures are maintained separately by `scripts/generate_test_fixtures.py`.

CI defines lint, formatting, tests and demo execution on Ubuntu, Windows and
macOS with Python 3.10 and 3.13. A separate job renders screenshots. Dependencies
are locked in `uv.lock`; use `uv sync --locked` to reproduce them.
See the [verification record](docs/VERIFICATION.md) for checks actually run locally.
The consolidated commit history and its actual feature dates are described in
[HISTORY.md](docs/HISTORY.md).

## Limitations

- Account valuation supports PLN, USD and EUR; broker layout changes may need new aliases.
- Daily TWR approximates intraday flows. XIRR can have no solution or multiple roots.
- Market data may be delayed, unavailable or revised. Polling does not guarantee new quotes.
- Benchmarks need sufficient Yahoo history and supported quote currency/FX. They exclude
  commissions and taxes; futures are price comparisons without a margin or roll model.
- The demo is illustrative, not an investment strategy or a record of actual performance.
- Source-based desktop commands support Windows and macOS; the portable build script targets
  Windows. Native desktop rendering depends on the platform's webview runtime.

## Roadmap

- Add fixtures for more broker export versions and corporate actions.
- Add explicit intraday cash-flow timing where source data permits it.
- Automate signed desktop release artifacts for Windows and macOS.

## License

[MIT](LICENSE). Project presentation material: [CV and interview notes](docs/CV_PROJECT_DESCRIPTION.md).
