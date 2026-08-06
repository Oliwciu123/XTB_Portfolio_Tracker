# AGENTS.md

## Cursor Cloud specific instructions

This is a single Python CLI/library product — **XTB Portfolio Analyzer** (`xtb-analyzer`).
It parses XTB broker CSV cash-operation exports and generates an interactive HTML report.
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
- Tests: `python -m pytest`. On a fresh checkout **5 tests fail** (`tests/test_parser.py::test_load_*`
  and `tests/test_flows.py::*`) because they load the user's real private exports at
  `data/XTB_USD_account_cs.csv` / `data/XTB_EURO_account_cs.csv`, which are **gitignored and not in
  the repo**. The other tests pass offline and require no data. This is a data availability gap, not
  a code defect — do not "fix" these tests.

### Running the app end-to-end (report generation)

- The CLI reads `data/XTB_*_account_cs.csv` (semicolon-delimited, European decimals). Each file must
  contain a `CASH OPERATION HISTORY` section followed by a transaction table whose header row starts
  with `ID`. Files are matched by the glob `XTB_*_account_cs.csv`; currency is inferred from the
  filename (`USD`/`EURO`/`PLN`).
- `data/` is gitignored and holds private data, so a fresh clone has no input. To demo/test the full
  pipeline without real user data, drop synthetic `data/XTB_*_account_cs.csv` exports in and run
  `python -m xtb_analyzer --currency pln`; the report is written to `output/report.html`.
- Report generation needs **outbound network**: Yahoo Finance (prices/benchmarks via `yfinance`) and
  the NBP API (`api.nbp.pl`, PLN FX rates). Use `--no-live` and/or `--no-cache` to control fetching.
  Charts in the HTML load Plotly.js from a CDN, so viewing the report also needs internet.
