"""Explicit market-data injection for deterministic, network-free demonstrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class MarketData:
    """Daily spot prices, consistent FX, and explicit quote-currency metadata."""

    prices: pd.DataFrame
    fx: pd.DataFrame
    benchmarks: dict[str, pd.Series]
    sectors: dict[str, str] = field(default_factory=dict)
    synthetic: bool = False
    quote_currencies: dict[str, str] = field(default_factory=dict)
    benchmark_currencies: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_examples(cls, folder: str | Path) -> MarketData:
        folder = Path(folder)
        prices = pd.read_csv(folder / "prices.csv", index_col="date", parse_dates=True)
        fx = pd.read_csv(folder / "fx.csv", index_col="date", parse_dates=True)
        benchmarks = pd.read_csv(folder / "benchmarks.csv", index_col="date", parse_dates=True)
        instruments = pd.read_csv(folder / "instruments.csv").set_index("symbol")
        benchmark_meta = pd.read_csv(folder / "benchmark_metadata.csv").set_index("key")
        return cls(
            prices,
            fx,
            {c: benchmarks[c] for c in benchmarks},
            instruments["sector"].to_dict(),
            synthetic=True,
            quote_currencies=instruments["currency"].to_dict(),
            benchmark_currencies=benchmark_meta["currency"].to_dict(),
        )
