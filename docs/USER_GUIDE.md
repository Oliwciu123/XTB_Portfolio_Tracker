# User guide

## Try the demo

Install uv and download or clone the project. From its root run:

```sh
uv sync
uv run xtb-analyzer --demo --open
```

All data is fictional. To open the same demo in a native desktop window:

```sh
uv run --extra desktop xtb-analyzer-desktop --demo
```

## Analyze an account

Export the full account history from xStation, including cash operations and all
funding before the first purchase. Keep complete PLN/USD/EUR accounts together
so internal transfers are recognized. Do not upload exports to GitHub.

Run `uv run --extra desktop xtb-analyzer-desktop`, then drop or choose the ZIP.
Generation shows progress; the report opens in the desktop window. Choose report
currency, inspect Overview, Benchmarks, Holdings and Costs, and use the benchmark
symbol field to download a supported Yahoo Finance instrument. The saved HTML
snapshot also opens in an ordinary browser; live controls need the desktop bridge.

For CLI usage, extract workbooks into `data/`, retaining currency labels in names:

```sh
uv run xtb-analyzer --data-dir data --output-dir output --currency pln --open
```

`--currency usd` and `--currency eur` are also supported. `--no-live` skips current
quotes; historical prices may still be downloaded. `--no-cache` disables disk cache.
If valuation fails, check history coverage, symbol mapping and the network message.

## Charts

NAV and return charts have day/week/month/year ranges, drag selection, reset and
PNG export. Monthly returns, company P&L and allocation charts stay fixed and offer
PNG export. Hover shows values without permanently drawing points on each line.
Comparison CSV export saves the selected benchmark series.

## Share a Windows desktop build

On Windows, install uv, then run `build_windows.bat`. It builds a PyInstaller
application and `dist/XTBPortfolioAnalyzer-Windows.zip` with a SHA-256 checksum.
Share that ZIP, not your repository's `data/` or `output/` directories. The builder
includes application binaries and this guide, not user histories or caches.

The recipient extracts the entire ZIP and opens `XTBPortfolioAnalyzer.exe` inside
the application folder. Keep `_internal` beside the executable. Windows may ask
about an unsigned app; signed distribution is a roadmap item. Microsoft Edge
WebView2 must be available for the native report window. No Python installation
is needed for the packaged build. Market-data access still needs internet.

Starting the executable with `--demo` opens the bundled fictional example offline.

On macOS, extract `XTBPortfolioAnalyzer-macOS.zip` and open `XTBPortfolioAnalyzer.app`
(right-click and select **Open** on first launch, as the app bundle is unsigned). Native
webview rendering uses macOS WebKit; source runs via `uv` are also supported.

## Local files

Source runs use ignored `data/` for imports/cache and `output/` for reports.
Packaged runs use the operating system's per-user application-data directory.
Exports and reports contain financial information. Share only the synthetic
examples and screenshots included in the repository.
