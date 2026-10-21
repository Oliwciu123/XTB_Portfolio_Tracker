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


def _normalize_index(series: pd.Series) -> pd.Series:
    series = series.copy()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.sort_index().ffill()


def _extract_close(data: pd.DataFrame, ticker: str) -> pd.Series:
    if data.empty:
        return pd.Series(dtype=float, name=ticker)

    if isinstance(data.columns, pd.MultiIndex):
        if ("Close", ticker) in data.columns:
            series = data[("Close", ticker)]
        elif "Close" in data.columns.get_level_values(0):
            close = data["Close"]
            if isinstance(close, pd.DataFrame) and ticker in close.columns:
                series = close[ticker]
            else:
                series = close.iloc[:, 0]
        else:
            series = data.iloc[:, 0]
    elif "Close" in data.columns:
        series = data["Close"]
    else:
        series = data.iloc[:, 0]

    return _normalize_index(series).rename(ticker)


def _download_close(ticker: str, start: str, end: str) -> pd.Series:
    data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    return _extract_close(data, ticker)


def _download_close_batch(tickers: list[str], start: str, end: str) -> dict[str, pd.Series]:
    if not tickers:
        return {}
    if len(tickers) == 1:
        ticker = tickers[0]
        return {ticker: _download_close(ticker, start, end)}

    data = yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        group_by="column",
        threads=True,
    )
    return {ticker: _extract_close(data, ticker) for ticker in tickers}


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


def _needs_refresh(cached: pd.Series | None, refresh_latest: bool, cache_file: Path | None = None) -> bool:
    if cached is None or cached.empty:
        return True
    if not refresh_latest:
        return False
    # Avoid re-downloading multi-day history on every live tick if cache was updated recently
    if cache_file is not None and cache_file.exists():
        import time

        age_seconds = time.time() - cache_file.stat().st_mtime
        if age_seconds < 300:
            return False
    return True


def _fetch_single_live_price(ticker: str) -> tuple[str, float | None]:
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None)
        if price and float(price) > 0:
            return ticker, float(price)
    except Exception:
        pass
    return ticker, None


def _fetch_live_prices(tickers: list[str]) -> dict[str, float]:
    from concurrent.futures import ThreadPoolExecutor

    if not tickers:
        return {}
    live: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as pool:
        for ticker, price in pool.map(_fetch_single_live_price, tickers):
            if price is not None and price > 0:
                live[ticker] = price
    return live


def _apply_live_quote(series: pd.Series, price: float) -> pd.Series:
    if series.empty or price <= 0:
        return series
    updated = series.copy()
    today = pd.Timestamp.today().normalize()
    if today > updated.index.max():
        updated.loc[today] = price
    else:
        updated.iloc[-1] = price
    return updated.sort_index()


def _resolve_tickers(
    tickers: list[str],
    start: str,
    end: str,
    use_cache: bool,
    refresh_latest: bool,
) -> dict[str, pd.Series]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, pd.Series] = {}
    pending: list[tuple[str, str, pd.Series | None]] = []

    for ticker in tickers:
        cache_file = _cache_path(ticker)
        cached = _load_cached_series(cache_file) if use_cache else None
        if _needs_refresh(cached, refresh_latest, cache_file if use_cache else None):
            fetch_start = start
            if cached is not None and not cached.empty:
                fetch_start = (cached.index.max() - pd.Timedelta(days=7)).date().isoformat()
            pending.append((ticker, fetch_start, cached))
        else:
            resolved[ticker] = cached.loc[pd.Timestamp(start) :]  # type: ignore[union-attr]

    if pending:
        batch_start = min(item[1] for item in pending)
        batch_tickers = [item[0] for item in pending]
        fresh_map = _download_close_batch(batch_tickers, batch_start, end)
        for ticker, _, cached in pending:
            fresh = fresh_map.get(ticker, pd.Series(dtype=float))
            series = _merge_price_series(cached, fresh, start)
            if not series.empty and use_cache:
                series.to_frame("close").to_parquet(_cache_path(ticker))
            if not series.empty:
                resolved[ticker] = series

    if refresh_latest and resolved:
        live_prices = _fetch_live_prices(list(resolved.keys()))
        for ticker, series in resolved.items():
            if ticker in live_prices:
                resolved[ticker] = _apply_live_quote(series, live_prices[ticker])

    return resolved


def fetch_prices(
    symbols: list[str],
    start: str,
    end: str | None = None,
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> pd.DataFrame:
    end = _default_end(end)
    tickers = sorted({xtb_to_yahoo(symbol) for symbol in symbols})
    reverse_map = {xtb_to_yahoo(sym): sym for sym in symbols}
    resolved = _resolve_tickers(tickers, start, end, use_cache, refresh_latest)

    frames: list[pd.Series] = []
    for ticker, series in resolved.items():
        if series.empty:
            continue
        xtb_symbol = reverse_map.get(ticker, ticker)
        frames.append(series.rename(xtb_symbol))

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, axis=1).sort_index().ffill()


def fetch_benchmark(
    start: str,
    end: str | None = None,
    ticker: str = "^SP500TR",
    use_cache: bool = True,
    refresh_latest: bool = False,
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


def fetch_benchmarks(
    tickers: list[str],
    start: str,
    end: str | None = None,
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> dict[str, pd.Series]:
    end = _default_end(end)
    return _resolve_tickers(sorted(set(tickers)), start, end, use_cache, refresh_latest)
