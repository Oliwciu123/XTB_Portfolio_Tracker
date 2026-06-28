from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path("data/cache/prices")


def xtb_to_yahoo(symbol: str) -> str:
    if symbol.endswith(".US"):
        return symbol[:-3]
    return symbol


def _cache_path(ticker: str) -> Path:
    safe = ticker.replace("^", "idx_").replace("=", "_")
    return CACHE_DIR / f"{safe}.parquet"


def _download_close(ticker: str, start: str, end: str | None) -> pd.Series:
    data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if data.empty:
        return pd.Series(dtype=float, name=ticker)

    if isinstance(data.columns, pd.MultiIndex):
        if ("Close", ticker) in data.columns:
            series = data[("Close", ticker)]
        else:
            series = data["Close"].iloc[:, 0] if isinstance(data["Close"], pd.DataFrame) else data["Close"]
    elif "Close" in data.columns:
        series = data["Close"]
    else:
        series = data.iloc[:, 0]

    series = series.copy()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.sort_index().ffill().rename(ticker)


def fetch_prices(symbols: list[str], start: str, end: str | None = None, use_cache: bool = True) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tickers = sorted({xtb_to_yahoo(symbol) for symbol in symbols})
    reverse_map = {xtb_to_yahoo(sym): sym for sym in symbols}
    frames: list[pd.Series] = []

    for ticker in tickers:
        cache_file = _cache_path(ticker)
        if use_cache and cache_file.exists():
            cached = pd.read_parquet(cache_file)
            series = cached.iloc[:, 0] if isinstance(cached, pd.DataFrame) else cached
            series.index = pd.to_datetime(series.index)
        else:
            series = _download_close(ticker, start, end)
            if series.empty:
                continue
            series.to_frame("close").to_parquet(cache_file)

        xtb_symbol = reverse_map.get(ticker, ticker)
        frames.append(series.rename(xtb_symbol))

    if not frames:
        return pd.DataFrame()

    prices = pd.concat(frames, axis=1).sort_index()
    return prices.ffill()


def fetch_benchmark(start: str, end: str | None = None, ticker: str = "^GSPC", use_cache: bool = True) -> pd.Series:
    frame = fetch_prices([ticker], start=start, end=end, use_cache=use_cache)
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.iloc[:, 0].rename("benchmark")
