from __future__ import annotations

from datetime import date, timedelta
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


def _default_end(end: str | None) -> str:
    if end:
        return end
    return (date.today() + timedelta(days=1)).isoformat()


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


def _load_cached_series(cache_file: Path) -> pd.Series | None:
    if not cache_file.exists():
        return None
    cached = pd.read_parquet(cache_file)
    series = cached.iloc[:, 0] if isinstance(cached, pd.DataFrame) else cached
    series.index = pd.to_datetime(series.index)
    return series.sort_index()


def _merge_price_series(cached: pd.Series | None, fresh: pd.Series, start: str) -> pd.Series:
    if cached is not None and not cached.empty and not fresh.empty:
        merged = pd.concat([cached, fresh])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    elif not fresh.empty:
        merged = fresh
    elif cached is not None:
        merged = cached
    else:
        return pd.Series(dtype=float)
    return merged.loc[pd.Timestamp(start) :]


def _resolve_series(
    ticker: str,
    start: str,
    end: str,
    use_cache: bool,
    refresh_latest: bool,
) -> pd.Series:
    cache_file = _cache_path(ticker)
    cached = _load_cached_series(cache_file) if use_cache else None

    if refresh_latest or cached is None or cached.empty:
        fetch_start = start
        if cached is not None and not cached.empty:
            fetch_start = (cached.index.max() - pd.Timedelta(days=7)).date().isoformat()
        series = _merge_price_series(cached, _download_close(ticker, fetch_start, end), start)
    else:
        series = cached.loc[pd.Timestamp(start) :]

    if not series.empty:
        series.to_frame("close").to_parquet(cache_file)
    return series


def fetch_prices(
    symbols: list[str],
    start: str,
    end: str | None = None,
    use_cache: bool = True,
    refresh_latest: bool = True,
) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    end = _default_end(end)
    tickers = sorted({xtb_to_yahoo(symbol) for symbol in symbols})
    reverse_map = {xtb_to_yahoo(sym): sym for sym in symbols}
    frames: list[pd.Series] = []

    for ticker in tickers:
        series = _resolve_series(ticker, start, end, use_cache, refresh_latest)
        if series.empty:
            continue
        xtb_symbol = reverse_map.get(ticker, ticker)
        frames.append(series.rename(xtb_symbol))

    if not frames:
        return pd.DataFrame()

    prices = pd.concat(frames, axis=1).sort_index()
    return prices.ffill()


def fetch_benchmark(
    start: str,
    end: str | None = None,
    ticker: str = "^SP500TR",
    use_cache: bool = True,
    refresh_latest: bool = True,
) -> pd.Series:
    frame = fetch_prices(
        [ticker],
        start=start,
        end=end,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.iloc[:, 0].rename("benchmark")
