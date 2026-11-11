# XTB Portfolio Tracker v1.2.0

Portable desktop and CLI release for Windows and macOS delivering UX refinements from desktop testing, offline typeset math formulas, collapsible ledgers, Polish `Europe/Warsaw` timestamps, 5-second live polling, Windows Desktop shortcut automation, and financial/tax engine hardening.

## What's New in v1.2.0

### 1. Click-to-Activate Chart Wheel Zoom
- **Smooth page scrolling by default:** hovering over any chart and scrolling the mouse wheel now scrolls the page normally instead of trapping scroll inside the plot.
- **Explicit zoom mode:** click inside any chart to enable mouse-wheel zoom (with a subtle `"Wheel zoom active · Esc to exit"` status badge and glowing border); click anywhere outside the chart or press `Escape` to deactivate wheel zoom.

### 2. Modernized Hover Readouts, Enlarged Navigation & Clean Chrome
- **Redesigned time-series hover card:** hovering the benchmark comparison or NAV chart displays a sleek, single-date glassmorphic readout listing each visible series with its color dot, clean series name, and right-aligned tabular values sorted from highest to lowest.
- **Enlarged navigation cards with smooth hover scale:** top-level section tabs (`Overview`, `Deposits`, `Benchmarks`, `Holdings`, `FX, costs & income`, `PIT-38`) are larger and smoothly elevate and scale on hover.
- **Cleaner page layout:** removed the top data-source notice line, the bottom generation footer, and the `Operation details` column from the Deposit operations table. Report metadata, generation time, data-source attribution, and the educational non-advice disclaimer are available anytime via the unobtrusive header **About** popover.

### 3. Offline Typeset Math in Indicator Guide Popovers
- **Typeset equations without external CDNs:** every KPI, risk, FX, and PIT-38 indicator popover renders stacked fractions, connected square-root radicals, summation/product limits, overbars, and subscripts completely offline on both desktop and mobile viewports.

### 4. Collapsible Previews for Long Tables
- **Fast vertical navigation:** the PIT-38 FIFO lot-matching ledger, foreign dividend table, deposit operations table, and company P&L table now display a concise row preview with an explicit row counter (`Showing X of Y rows`) and an expand/collapse toggle, while search, filters, sorting, and CSV exports continue to cover 100% of rows.

### 5. Polish Time (`Europe/Warsaw`), 5-Second Live Refresh & Audit Hardening
- **DST-safe Polish timestamps:** header `"As of"`, `"Live updates: ON · HH:MM:SS CET/CEST"`, and valuation day boundaries use `ZoneInfo("Europe/Warsaw")` (with bundled IANA `tzdata` verified in frozen Windows and macOS builds).
- **5-second live polling:** desktop live refresh now polls every 5 seconds with cached export parsing, non-blocking lock protection, a 4-second live quote memo, and automatic Yahoo `429` rate-limit cooldown.
- **Engine & parser hardening:** mapped Eurozone XTB suffixes (`.NL`→`.AS`, `.FR`→`.PA`, `.ES`→`.MC`, `.IT`→`.MI`, `.BE`→`.BR`, `.PT`→`.LS`, `.FI`→`.HE`, `.AT`→`.VI`) for live Yahoo valuation, isolated cached statutory NBP Table A series from Yahoo fallback/live quotes, enforced 7-day prior-year lookback validation on early-January FX cache hits, guarded FIFO stock-split boundary dates, widened dividend-to-WHT pairing across weekends, and translated remaining Polish strings in charts and start screens to English.

### 6. One-Step Windows Desktop Shortcut
- `build_windows.bat` now automatically creates or refreshes **`XTB Portfolio Analyzer.lnk`** (with `app.ico`) on the active Windows Desktop (including OneDrive-redirected Desktop folders), and `scripts/create_desktop_shortcut.py` can be run standalone anytime without committing binaries.

## Requirements & Running

- **Windows (`XTBPortfolioAnalyzer-Windows.zip`):** Windows 10/11 (64-bit) with Microsoft Edge WebView2 Runtime. Extract all files (keeping `_internal` beside `XTBPortfolioAnalyzer.exe`) and launch `XTBPortfolioAnalyzer.exe`.
- **macOS (`XTBPortfolioAnalyzer-macOS.zip`):** macOS 13+ (Apple Silicon). Extract the archive and open `XTBPortfolioAnalyzer/XTBPortfolioAnalyzer.app` (right-click → *Open* on first launch, as the binary is unsigned).
- **Offline synthetic demo:** run `XTBPortfolioAnalyzer.exe --demo` on Windows or `XTBPortfolioAnalyzer.app/Contents/MacOS/XTBPortfolioAnalyzer --demo` on macOS.
