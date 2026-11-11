# XTB Portfolio Tracker v1.3.0

## What's new

- Chart hover shows one card. The native Plotly hover label is hidden on every chart, including the NAV and benchmark charts that previously drew both.
- Indicator buttons stay short: name, one-line meaning, this portfolio's value, and Learn more. Learn more opens an in-report guide with a MathJax formula, a calculation from this portfolio that ends on the dashboard value, a generic example, and the reference band for that value. The MathJax SVG renderer is embedded, so the report stays offline.
- The application icon is redrawn for 16, 32, 48, 64, 128, and 256 pixels, with a macOS `.icns` for the window, executable, shortcut, and release archive.
- The README is rewritten around the current demo, the Windows and macOS downloads, and the v1.3.0 report.

The Windows shortcut display name is now **XTB Portfolio Tracker**. The executable and zip names remain `XTBPortfolioAnalyzer`.

## Checks

`uv sync --locked`, Ruff, pytest, `xtb-analyzer --demo`, and `scripts/make_screenshots.py` against the fictional demo.
