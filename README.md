# xtb_portfolio_analyzer

Analyze your XTB portfolio from CSV cash-operation exports.

## Setup

```bash
pip install -e ".[dev]"
```

If the full install fails on Windows (long paths), install core dependencies manually:

```bash
pip install pandas numpy yfinance matplotlib plotly requests pyarrow notebook ipykernel pytest
pip install -e . --no-deps
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
- Reconstructs daily portfolio NAV in PLN, USD, EUR
- Metrics: total return, CAGR, Sharpe, Sortino, max drawdown, ATH, beta/alpha vs S&P 500
- **Deposit-matched S&P 500 benchmark** (buy index at each deposit time)
- **FX conversion cost analysis** (0.5% XTB fee + spread vs NBP)
- Sector allocation via Yahoo Finance
- Clear Plotly charts: deposit step-line, return gauge, benchmark comparison

## Data privacy

The `data/` and `output/` folders are gitignored. Do not commit your transaction files.
