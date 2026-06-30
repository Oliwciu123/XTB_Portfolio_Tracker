# xtb_portfolio_analyzer

Analyze your XTB portfolio from CSV cash-operation exports.

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

1. Export cash operation history from XTB (CSV) for each account.
2. Place files in `data/` (e.g. `XTB_USD_account_cs.csv`, `XTB_EURO_account_cs.csv`).
3. Open the notebook:

```bash
jupyter notebook notebooks/portfolio_analysis.ipynb
```

4. Run all cells. Results are saved to `output/`.

## Features

- Parses multi-section XTB CSV exports (semicolon, European decimals)
- Tracks positions (average cost), cash, dividends, transfers
- Reconstructs daily portfolio NAV in PLN, USD, EUR **through today** using live Yahoo Finance prices
- Metrics: total return, CAGR, Sharpe, Sortino, max drawdown, ATH, beta/alpha vs S&P 500
- **Deposit-matched S&P 500 Total Return benchmark** (SP500TR, buy index at each deposit time)
- **FX conversion cost** — XTB 0.5% commission on PLN → USD/EUR conversions
- Sector allocation pie chart via Yahoo Finance
- Dark-theme Plotly charts: return gauge, NAV vs deposits, benchmark comparison, sector pie

## Data privacy

The `data/` and `output/` folders are gitignored. Do not commit your transaction files.
