# XTB Portfolio Tracker v1.1.0

Portable desktop and CLI release for Windows and macOS with interactive deposit analytics, plain-English KPI indicator guides, and automated Polish PIT-38 tax settlements.

## What's New in v1.1.0

### 1. Deposit Analytics (`Deposits` Tab)
- **Interactive monthly deposit histogram** visualizing inbound cash contributions across your full investment history or selected years.
- **Flexible year & multi-year filtering:** inspect total deposits across all history, isolate a single year, or combine any subset of years (for example `2024 + 2025`), switching between chronological monthly bars (`YYYY-MM`) and calendar-month sums (`Jan`–`Dec`).
- **Month-level drill-down:** click any histogram bar, month filter pill, or Top 10 ranking row to inspect exact monthly totals and underlying deposit operations.
- **Dynamic Top 10 Months ranking** displaying your highest-contribution months, operation counts, and share of scope capital.

### 2. Interactive Metric Definitions
- **Hover, click, and keyboard-accessible `i` badges** across portfolio KPIs, risk statistics, trade efficiency cards (`Win rate`, `Profit factor`, `Calmar ratio`, `Daily VaR 95%`), FX attribution, and PIT-38 tax cards.
- Every indicator popover includes:
  - **Plain-English explanation** of what the indicator measures,
  - **Concrete numerical example** with step-by-step inputs and result,
  - **Color-coded reference benchmarks** for interpreting portfolio values on desktop and mobile viewports.

### 3. Polish PIT-38 Tax Settlement (`PIT-38` Tab)
- **Strict FIFO capital-gains accounting (PIT-38 Section C, Art. 30b):** matches partial and multi-lot equity/ETF disposals First-In, First-Out per account, converting acquisition costs, sale proceeds, and brokerage commissions into PLN at the official **NBP Table A mid rate from the last business day preceding each transaction (`D-1`)**, with full weekend and Polish holiday lookback.
- **Foreign dividends & withholding tax credit (`Podatek u źródła`, Art. 30a):** converts gross dividends and foreign WHT at `D-1` NBP rates, calculates the 19% Polish flat tax, applies foreign WHT credit capped at 19% per dividend payment, and reports net Polish dividend tax to pay (`do dopłaty`).
- **Any-year & current YTD estimation:** switch instantly between the current year-to-date (`YTD`) tax estimate and any historical tax year, filter by ticker/currency, inspect every matched FIFO slice and dividend row, and export a PIT-38 settlement CSV.

### 4. Automated Windows & macOS Release Archives
- **Cross-platform portable builds:** automated GitHub Actions release pipeline producing both `XTBPortfolioAnalyzer-Windows.zip` (64-bit Windows `.exe` folder) and `XTBPortfolioAnalyzer-macOS.zip` (macOS `.app` bundle).

## Requirements & Running

- **Windows (`XTBPortfolioAnalyzer-Windows.zip`):** Windows 10/11 (64-bit) with Microsoft Edge WebView2 Runtime. Extract all files (keeping `_internal` beside `XTBPortfolioAnalyzer.exe`) and launch `XTBPortfolioAnalyzer.exe`.
- **macOS (`XTBPortfolioAnalyzer-macOS.zip`):** macOS 13+ (Apple Silicon). Extract the archive and open `XTBPortfolioAnalyzer/XTBPortfolioAnalyzer.app` (right-click → *Open* on first launch, as the binary is unsigned).
- **Offline synthetic demo:** run `XTBPortfolioAnalyzer.exe --demo` on Windows or `XTBPortfolioAnalyzer.app/Contents/MacOS/XTBPortfolioAnalyzer --demo` on macOS. No Python installation or network connection is needed for the demo; internet access is required for Yahoo Finance quotes and NBP Table A exchange rates on personal exports.
