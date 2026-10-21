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

1. Export account data from XTB for each currency (USD / EUR / PLN).
2. Put these files in `data/`:
   - `XTB_USD_cs.xlsx`
   - `XTB_EURO_cs.xlsx`

   Supported exports (auto-detected):
   - Full account XLSX (Historia → Eksportuj jako XLSX)
   - Cash Operations CSV/XLSX from the newer xStation export (also OK if Excel
     put each row into one cell — the parser splits it)

3. From the project root (branch **main**):

```bash
git checkout main
git pull
python -m xtb_analyzer --currency pln --open
```

Or open the notebook and run all cells. Replacing files in `data/` and re-running is enough — the whole pipeline rebuilds from the latest exports.

## Desktop app (Windows, portable)

A real Windows window — not a website. Drop a ZIP with XTB account history; the same stats, comparisons, and benchmarks as the CLI run locally with live quotes. The report opens inside the program.

### What Oliwier copies / clicks

1. **One-time build** (on any Windows PC that has Python 3.10+ from [python.org](https://www.python.org/downloads/), with “Add to PATH”):
   ```text
   build_windows.bat
   ```
   This creates `dist\XTBPortfolioAnalyzer\` (PyInstaller one-folder: `.exe` + `_internal`).

2. **Copy the whole folder** `dist\XTBPortfolioAnalyzer` to a USB stick or zip it for a colleague. You do **not** need Python on the target PC.

3. **Double-click** `XTBPortfolioAnalyzer.exe`.

4. Drop the history ZIP onto the window (or click **Wybierz archiwum ZIP**). A progress bar runs while prices, FX, and the report are calculated. You can switch the report currency (`PLN` / `USD` / `EUR`) directly inside the interactive report. Internet is required for Yahoo Finance and NBP.

### Developer run (source)

```powershell
pip install -e ".[dev]"
python -m xtb_analyzer.desktop
```

Optional flags: `--currency pln`, `--zip path\to\file.zip`. On Linux/macOS the same module works when a WebView backend is available.

### ZIP layout

USD, EUR, and PLN account files are accepted (PLN may be absent). Example:

```text
<account>/USD_<account>_<from>_<to>.xlsx
<account>/EUR_<account>_<from>_<to>.xlsx
<account>/PLN_<account>_<from>_<to>.xlsx
```

Each workbook’s **Cash Operations** sheet is used. Closed Positions / Open Positions sheets are ignored. If several date ranges exist for one account, the file with the latest end date is used. Canonical names also work: `XTB_USD_cs.xlsx`, `XTB_EURO_cs.xlsx`.

Unpacked uploads and price/FX caches are written under `data/` next to the `.exe` (or project root in source). That folder is gitignored — do not commit private exports.
## Features

### Returns (three methods, easy to compare)

- **ROI** — simple return on deposited capital (value ÷ deposits − 1)
- **MWR / XIRR** — annualized money-weighted return of the actual cash flows (bisection solver)
- **TWR** — time-weighted return with deposits neutralized; cumulative and annualized, directly comparable with indices

### Benchmarks

- **Deposit-matched benchmarks** — S&P 500 Total Return (^SP500TR), NASDAQ 100 (^NDX), MSCI ACWI, and Philadelphia Semiconductor Index (^SOX), plus interactive comparison with any index, ETF, commodity, or company ticker

### FX attribution

- Splits total PLN gain into **investment gain** (what the assets earned) and **currency gain** (what holding USD/EUR earned or lost, including the XTB conversion spread) — exact decomposition, per currency and over time

### Risk (computed on TWR daily returns)

- Annualized volatility, Sharpe, Sortino, Alpha, Beta, Calmar, VaR 95%
- Max drawdown with dates, monthly returns heatmap, rolling volatility

### Portfolio structure & costs

- Company profit & loss ranking (realized + unrealized P&L sorted from largest profit to largest loss)
- Allocation by position, by account currency and by sector
- Dividends, interest and withholding taxes per currency
- FX conversion cost — XTB 0.5% commission on PLN → USD/EUR conversions

### Engine

- Parses multi-section XTB CSV/XLSX exports
- Reconstructs daily portfolio NAV in PLN, USD, EUR through today
- FX rates from NBP (table A) with Yahoo Finance fallback; on-disk price/FX caches

## Project layout

```
src/xtb_analyzer/
  parser.py         # XTB CSV/XLSX parsing
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
  risk.py           # risk statistics on TWR returns (Sharpe, Sortino, Alpha, Beta)
  attribution.py    # FX vs investment gain decomposition
  metrics.py        # company P&L ranking + summary metrics
  sectors.py        # sector enrichment (Yahoo)
  charts.py         # Plotly figures (dark theme)
  report.py         # Interactive 4-section HTML report generator
  session.py        # history zip → HTML report
  desktop.py        # desktop window (zip picker + report)
  paths.py          # portable / frozen app paths
  __main__.py       # CLI: python -m xtb_analyzer
packaging/
  xtb_portfolio_analyzer.spec   # PyInstaller one-folder
build_windows.bat               # one-time Windows build
run_desktop.py                  # PyInstaller entry
```

## Tests

```bash
pytest
```

## Data privacy

The `data/` and `output/` folders are gitignored. Do not commit your transaction files or uploaded zips. The desktop app stores unpacked uploads under `data/uploads/`.
