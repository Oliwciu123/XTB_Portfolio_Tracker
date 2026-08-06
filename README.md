# xtb_portfolio_analyzer

Analyze your XTB portfolio from CSV cash-operation exports and generate a professional, interactive HTML report.

## Setup

From the project root:

```bash
pip install -e ".[dev]"
```

If the full install fails on Windows (long paths), install core dependencies manually:

```bash
pip install pandas numpy yfinance matplotlib plotly requests pyarrow notebook ipykernel pytest
pip install -e . --no-deps
```

### Notebook in Cursor / VS Code

1. Run `pip install -e ".[dev]"` from the project root.
2. Select the **same Python interpreter** that received the install (Command Palette → *Python: Select Interpreter*).
3. Open `notebooks/portfolio_analysis.ipynb` and **restart the kernel**.
4. Run all cells.

The notebook also bootstraps `src/` on `sys.path`, so it works without a formal install during local development. For tests and CLI usage, prefer the editable install.

Verify the package is available:

```bash
python -c "import xtb_analyzer; print(xtb_analyzer.__file__)"
```

## Usage

1. Export cash operation history from XTB for each account currency (USD / EUR / …).
2. Place files in `data/`. Supported formats (auto-detected):
   - **Modern flat CSV** (recommended): xStation → *Account history* → *Cash operations* → *Export* → *Cash Operations* → *CSV*. Name files so the currency is visible, e.g. `XTB_USD_cash_ops.csv`, `XTB_EURO_cash_ops.csv`.
   - **Legacy multi-section CSV** with a `CASH OPERATION HISTORY` block (older exports).
   - **Full account XLSX** report — drop the `.xlsx` straight into `data/` (the `CASH OPERATION HISTORY` sheet is read automatically).
3. Generate the report:

```bash
python -m xtb_analyzer --currency pln --open
```

Or open the notebook and run all cells. Replacing files in `data/` and re-running is enough — the whole pipeline rebuilds from the latest exports.

## Features

### Returns (three methods, easy to compare)

- **ROI** — simple return on deposited capital (value ÷ deposits − 1)
- **MWR / XIRR** — annualized money-weighted return of the actual cash flows (bisection solver)
- **TWR** — time-weighted return with deposits neutralized; cumulative and annualized, directly comparable with indices

### Benchmarks

- **Deposit-matched benchmarks** — S&P 500 Total Return (^SP500TR) and NASDAQ 100 (^NDX): every deposit buys the index on the deposit day, so timing and size of flows match your portfolio exactly

### FX attribution

- Splits total PLN gain into **investment gain** (what the assets earned) and **currency gain** (what holding USD/EUR earned or lost, including the XTB conversion spread) — exact decomposition, per currency and over time

### Risk (computed on TWR daily returns)

- Annualized volatility, Sharpe, Sortino, Calmar, VaR 95%
- Max drawdown with dates, drawdown chart, monthly returns heatmap, rolling volatility
- Beta, alpha and correlation vs S&P 500 TR and NASDAQ 100

### Portfolio structure & costs

- Positions with average cost, market value and unrealized P&L (live Yahoo Finance prices)
- Allocation by position, by account currency and by sector
- Dividends, interest and withholding taxes per currency
- FX conversion cost — XTB 0.5% commission on PLN → USD/EUR conversions

### Engine

- Parses multi-section XTB CSV exports (semicolon, European decimals)
- Reconstructs daily portfolio NAV in PLN, USD, EUR through today
- FX rates from NBP (table A) with Yahoo Finance fallback; on-disk price/FX caches

## Project layout

```
src/xtb_analyzer/
  parser.py         # XTB CSV parsing
  comment_parser.py # trade/transfer comment parsing
  models.py         # dataclasses
  positions.py      # position tracking (average cost)
  portfolio.py      # daily NAV reconstruction
  flows.py          # deposits, conversion costs
  cash.py           # cash ledger, income by currency
  fx.py             # NBP / Yahoo FX rates
  prices.py         # price fetching + cache
  benchmark.py      # deposit-matched index benchmarks
  returns.py        # ROI, XIRR (MWR), TWR
  risk.py           # risk statistics on TWR returns
  attribution.py    # FX vs investment gain decomposition
  metrics.py        # legacy metrics + tables + JSON report
  sectors.py        # sector enrichment (Yahoo)
  charts.py         # Plotly figures (dark theme)
  report.py         # HTML report generator
  __main__.py       # CLI: python -m xtb_analyzer
```

## Tests

```bash
pytest
```

## Data privacy

The `data/` and `output/` folders are gitignored. Do not commit your transaction files.
