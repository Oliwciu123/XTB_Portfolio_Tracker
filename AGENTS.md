# AGENTS.md

## Cursor Cloud specific instructions

This is a single Python CLI/library product — **XTB Portfolio Analyzer** (`xtb-analyzer`).
It parses XTB broker account exports and generates an interactive HTML report.
There is no long-running server or database. See `README.md` for full usage and options.

### Environment

- Python dependencies are installed into a virtualenv at `.venv/` (Ubuntu's system Python is
  externally managed / PEP 668, so a venv is used). Activate it before running anything:
  `source .venv/bin/activate` (or prefix commands with `.venv/bin/`).
- The startup update script refreshes the venv, so dependencies are already installed — no need
  to reinstall on a fresh session.
- `pyarrow` is required at runtime for the on-disk price/FX cache (`data/cache/`); it is installed
  in addition to `pyproject.toml` deps because the README lists it but `pyproject.toml` omits it.

### Lint / test / build / run

- Standard commands live in `README.md` (`pytest`, `python -m xtb_analyzer ...`). There is no
  lint config or separate build step (editable install only).
- Tests: `python -m pytest`. Parser/unit tests use fixtures under `tests/fixtures/` (including
  full-account XLSX samples). Real user exports in `data/` are gitignored and not required for CI.

### Running the app end-to-end (report generation)

- Canonical inputs (preferred): `data/XTB_USD_cs.xlsx` and `data/XTB_EURO_cs.xlsx` — full xStation
  account XLSX reports. Currency is taken from the filename (`USD` / `EURO` / `EUR` / `PLN`).
  The parser reads the `CASH OPERATION HISTORY` sheet.
- When those canonical files are present, `discover_export_files()` uses **only** them and ignores
  leftover Closed Positions / broken CSV files in `data/`.
- `data/` is gitignored. To demo the full pipeline, copy fixtures:
  `cp tests/fixtures/legacy_usd_account.xlsx data/XTB_USD_cs.xlsx`
  `cp tests/fixtures/legacy_eur_account.xlsx data/XTB_EURO_cs.xlsx`
  then run `python -m xtb_analyzer --currency pln`.
- Report generation needs **outbound network**: Yahoo Finance (prices/benchmarks via `yfinance`) and
  the NBP API (`api.nbp.pl`, PLN FX rates). Use `--no-live` and/or `--no-cache` to control fetching.
  Charts in the HTML load Plotly.js from a CDN, so viewing the report also needs internet.

### Portable Windows desktop app

- Preferred user path: on Windows run `build_windows.bat` once → copy
  `dist/XTBPortfolioAnalyzer/` → double-click `XTBPortfolioAnalyzer.exe`.
- Spec: `packaging/xtb_portfolio_analyzer.spec` (PyInstaller one-folder). Entry: `run_desktop.py`.
- Desktop module: `python -m xtb_analyzer.desktop` (always live quotes; ZIP drop + progress).
- Do not treat `pip install -e .` + system Python as the end-user path.
