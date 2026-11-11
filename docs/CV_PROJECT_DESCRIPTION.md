# CV and interview material

## One-line title

**XTB Portfolio Tracker — Python portfolio reconstruction and interactive financial reporting**

## CV bullets

- Built a Python/pandas pipeline that reconstructs multi-currency cash, fractional
  holdings and daily NAV from XTB account exports, producing interactive Plotly reports.
- Implemented ROI, XIRR, TWR, risk metrics and FX attribution, with pytest reference
  cases for cash flows, withdrawals, conversions and portfolio valuation.
- Packaged CLI and desktop workflows with reproducible synthetic demos, uv dependency
  locking, Ruff checks and a GitHub Actions matrix for Windows, macOS and Ubuntu.

## Technologies and skills

Python, pandas, NumPy, Decimal, Plotly, financial time series, portfolio accounting,
XIRR, TWR, NAV, FX attribution, risk statistics, XLSX/CSV parsing, openpyxl,
yfinance, NBP API, Parquet, pyarrow, pywebview, Tkinter, PyInstaller, pytest,
Playwright, Ruff, uv, Git, GitHub Actions, data validation, reproducible analysis.

## LinkedIn Projects

Built a Python application that turns XTB account histories into interactive
portfolio reports and a desktop workflow. It reconstructs cash and holdings in
PLN, USD and EUR, calculates money- and time-weighted performance, and separates
investment and currency effects. Reports include risk statistics and hypothetical
benchmark portfolios funded with the same cash flows. The repository includes
fictional offline examples, financial regression tests and cross-platform CI configuration.

## 30-second interview pitch

I built XTB Portfolio Tracker to turn broker exports into a portfolio history
that is easier to inspect. The difficult part was distinguishing investment
results from deposits, withdrawals and currency conversions. I used Python,
pandas and Decimal for the accounting pipeline, then added XIRR, daily TWR and
Plotly reports. A synthetic offline demo and reference tests let someone verify
the calculations without sharing a real brokerage account.

## Likely interview questions

1. **Why show ROI, XIRR and TWR?** ROI measures profit against gross deposits;
   XIRR accounts for cash-flow timing; TWR removes the effect of external funding
   under a daily start-of-day convention. They answer different questions.
2. **How do you avoid counting transfers as profit?** Cash operations reconstruct
   balances; external funding is identified separately. Transfers between included
   accounts move capital internally and do not become a new external deposit.
3. **How do you test the calculations?** Small reference cases check known results,
   and the distributed sample reconciles cash plus positions to NAV. An independent
   daily product checks TWR and the XIRR result is substituted into the NPV equation.
4. **Why Decimal and pandas?** Decimal represents exported monetary amounts and
   share quantities during accounting. pandas aligns daily valuations and market
   series; return and risk calculations use floating-point arrays with tolerances.
5. **What would you improve next?** Support more export versions and corporate
   actions, improve intraday-flow treatment when data permits it, and automate signed
   desktop releases. Market data quality remains an explicit limitation.
