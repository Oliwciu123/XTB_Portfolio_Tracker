# Contributor instructions

This is one Python CLI/library and desktop product, **XTB Portfolio Tracker**.
It parses XTB exports and writes interactive HTML. There is no server or database.

- Work on `main` for this repository; do not delete other branches without approval.
- Keep application text, documentation, comments and new commit messages in English.
- Preserve localized parser aliases: these recognize input, not UI language.
- Never commit real exports, account details, generated private reports, caches,
  secrets or `.env` files. Use `examples/` for fictional data and `data/` for private data.
- Do not change financial definitions without a documented reason and regression case.
- Use cross-platform paths and the existing src layout.

## Setup and checks

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run xtb-analyzer --demo
```

The offline demo uses synthetic market data and needs no network after setup.
Real-data reports require Yahoo Finance and NBP. `--no-live` only skips current quotes.
Plotly.js is embedded in generated HTML.

## Screenshots and desktop

```sh
uv run playwright install chromium
uv run python scripts/make_screenshots.py
uv run --extra desktop xtb-analyzer-desktop --demo
uv run --extra desktop python scripts/make_screenshots.py --native
```

The screenshot script must capture actual UI using fictional data. Do not use
placeholders. Windows builds use `build_windows.bat` and the specification under
`packaging/`; only application files belong in the distributable archive.

`scripts/generate_demo_data.py --seed 42 --end-date YYYY-MM-DD` regenerates the
examples byte-for-byte for a fixed end date. It must not read private inputs.
Keep the small fixtures in `scripts/generate_test_fixtures.py` separate.
