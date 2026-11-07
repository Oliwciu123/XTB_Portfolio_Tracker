# XTB Portfolio Analyzer v1.0.0

Portable Windows application for analyzing XTB account histories.

## Features

- Import XTB ZIP, XLSX and CSV Cash Operations histories.
- Reconstruct NAV and calculate ROI, XIRR/MWR, TWR and risk statistics in PLN, USD or EUR.
- View NAV, benchmarks, monthly returns, company P&L and allocation charts.
- Inspect FX attribution cards/tables, dividends, interest and taxes.
- Save interactive HTML reports, chart PNGs and benchmark comparison CSV files.
- Explore a bundled fictional demo offline; use online market data for personal exports.

## Requirements

- Windows 10 or Windows 11, 64-bit.
- Microsoft Edge WebView2 Runtime.
- Internet access for market prices, FX and custom benchmark downloads.
- No Python installation is required. The bundled demo works offline.

The application is unsigned. Windows may display an unknown-publisher warning.

## Run

Download `XTBPortfolioAnalyzer-Windows.zip`, extract all files, then open
`XTBPortfolioAnalyzer/XTBPortfolioAnalyzer.exe`. Keep `_internal` beside the EXE.
For the offline demo, run `XTBPortfolioAnalyzer.exe --demo` from that folder.

## Artifact integrity

File: `XTBPortfolioAnalyzer-Windows.zip`

Size: 95,789,354 bytes

SHA-256:

```text
718dfaf156e07797866a3a4c24a946fabcd06325acb1c29475b92df79a8dc468
```

Built with `build_windows.bat`. Normal startup and the offline demo were verified
from an extracted copy of this ZIP. The release and tag are created separately by
the maintainer; the ZIP is not committed to Git.
