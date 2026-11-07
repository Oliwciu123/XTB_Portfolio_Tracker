# Verification record

Checked on 2026-11-07 on Windows with CPython 3.13.1 and uv 0.12.5.

## Clean checkout

A new local clone of the cleaned `main` was created with `git clone --no-local
--single-branch --branch main`. It contained no private inputs, caches or existing
virtual environment. The following completed successfully:

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
uv run --locked xtb-analyzer --demo
uv run --locked xtb-analyzer --demo --currency usd --output-dir output/usd
uv run --locked xtb-analyzer --demo --currency eur --output-dir output/eur
uv run --locked python scripts/make_screenshots.py
```

Ruff passed; all 48 Python/notebook files passed formatting. The test rerun passed
all 86 cases. Three report currencies generated successfully. The sample reconciles
to NAV 76,373.952 PLN and gross deposits 72,000 PLN; these are fictional values.
In the final isolated clone, 85 tests passed and one native Tk window test reported
`no display` and was skipped. All financial and headless-browser checks passed.

## Real browser capture

The screenshot script rendered the production HTML and desktop import screen in
Chromium, with HTTP(S) blocked. It saved five PNG files under `docs/images/`, checked
fixed categorical charts, exercised the one-week NAV range and reset, and detected
no JavaScript page errors. NAV, returns and the import screen were visually reviewed.
The import screenshot renders the desktop's HTML; it is not a native window capture.

## Windows distribution

The optional desktop/build environment was synchronized from uv.lock. PyInstaller
built the portable ZIP. The packaged executable's `--check-install` smoke test
verifies Parquet round trips, embedded Plotly, icons, the Windows webview import
and bundled synthetic demo files. Packaging explicitly includes only application
files, the fictional demo, the English guide and license.

## Privacy and platform boundaries

The cleaned reachable Git objects, including stashes and the checkpoint tree, were
scanned for known original identifiers and common credential patterns. ZIP/XLSX
contents were expanded; no matching identifiers or credentials remained. The older
historical PNG was visually checked and contains an import screen without account
figures. Ignored private recovery copies are intentionally outside this audit's
publishable set.

GitHub remains private and unchanged. Ubuntu/macOS and Python 3.10 checks are
configured in CI but have not been run remotely in this session. Native market-data
availability, signed installers and every possible broker format are not covered
by the deterministic offline validation.
