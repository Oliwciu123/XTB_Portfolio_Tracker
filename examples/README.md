# Fictional XTB portfolio

Generated with NumPy seed 42: 2021-01-01 to 2026-11-06, 284 cash operations, 15 instruments.

Every account, operation, quote, FX rate and benchmark is invented. Tickers identify instrument categories only; these paths are not historical returns.

Prices use distinct GBM parameters and a shared market factor. Deterministic drift shocks in 2022 and 2024 are scenarios, not fitted market events. FX follows log mean reversion. The calendar is business days, not exchange holidays; corporate actions are not simulated.

`instruments.csv` records parameters, sectors and quote currencies. `benchmark_metadata.csv` identifies the fictional indices and their currencies. `demo.json` records an independent cash/share ledger and cash flows for reconciliation.

Regenerate: `uv run python scripts/generate_demo_data.py --seed 42` (through today). Pin `--end-date YYYY-MM-DD` for byte-identical files. Run `uv run xtb-analyzer --demo --open`.
