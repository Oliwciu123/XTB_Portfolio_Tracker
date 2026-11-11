from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

CACHE_DIR = Path("data/cache/prices")
WARSAW_TZ = ZoneInfo("Europe/Warsaw")

_XTB_SUFFIX_TO_YAHOO = {
    ".US": "",
    ".PL": ".WA",
    ".UK": ".L",
    ".NL": ".AS",
    ".FR": ".PA",
    ".ES": ".MC",
    ".IT": ".MI",
    ".BE": ".BR",
    ".PT": ".LS",
    ".FI": ".HE",
    ".AT": ".VI",
}

_LIVE_QUOTE_TTL_SECONDS = 4.0
_LIVE_RATE_LIMIT_COOLDOWN_SECONDS = 15.0
_live_quote_lock = threading.Lock()
_live_quote_memo: dict[str, tuple[float, float]] = {}
_live_rate_limited_until: float = 0.0


def warsaw_today() -> pd.Timestamp:
    """Current calendar date in Europe/Warsaw (normalized Timestamp)."""
    return pd.Timestamp(datetime.now(WARSAW_TZ).date())


def xtb_to_yahoo(symbol: str) -> str:
    symbol = symbol.strip().upper()
    for suffix, replacement in _XTB_SUFFIX_TO_YAHOO.items():
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)] + replacement
    return symbol


def _cache_path(ticker: str, adjusted: bool = True) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", ticker)
    digest = hashlib.sha256(ticker.encode()).hexdigest()[:12]
    kind = "total" if adjusted else "spot"
    return CACHE_DIR / f"v2_{kind}_{safe}_{digest}.parquet"


def _default_end(end: str | None) -> str:
    if end:
        return end
    return (warsaw_today() + timedelta(days=1)).date().isoformat()


def _normalize_index(series: pd.Series) -> pd.Series:
    series = series.copy()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.sort_index().ffill()


def _extract_close(data: pd.DataFrame, ticker: str, adjusted: bool = True) -> pd.Series:
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
                return pd.Series(dtype=float, name=ticker)
        else:
            return pd.Series(dtype=float, name=ticker)
    elif "Close" in data.columns:
        series = data["Close"]
    else:
        series = data.iloc[:, 0]

    series = _normalize_index(series).rename(ticker)
    if not adjusted:
        key = (
            ("Stock Splits", ticker) if isinstance(data.columns, pd.MultiIndex) else "Stock Splits"
        )
        if key in data.columns:
            splits = _normalize_index(data[key]).fillna(0)
            factors = splits.replace(0, 1)
            # Yahoo Close includes split adjustments; restore the actual historical quote.
            future_factor = factors.iloc[::-1].cumprod().iloc[::-1] / factors
            series = series * future_factor.reindex(series.index).fillna(1)
            series.attrs["splits"] = {
                str(d.date()): float(v) for d, v in splits.items() if v > 0 and v != 1
            }
    return series.dropna()


def _download_close(ticker: str, start: str, end: str, adjusted: bool = True) -> pd.Series:
    data = yf.download(
        ticker, start=start, end=end, progress=False, auto_adjust=adjusted, actions=not adjusted
    )
    return _extract_close(data, ticker, adjusted)


def _download_close_batch(
    tickers: list[str], start: str, end: str, adjusted: bool = True
) -> dict[str, pd.Series]:
    if not tickers:
        return {}
    if len(tickers) == 1:
        ticker = tickers[0]
        return {ticker: _download_close(ticker, start, end, adjusted)}

    data = yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        auto_adjust=adjusted,
        actions=not adjusted,
        group_by="column",
        threads=True,
    )
    return {ticker: _extract_close(data, ticker, adjusted) for ticker in tickers}


def _load_cached_series(cache_file: Path) -> pd.Series | None:
    if not cache_file.exists():
        return None
    cached = pd.read_parquet(cache_file)
    series = cached.iloc[:, 0] if isinstance(cached, pd.DataFrame) else cached
    series.attrs = dict(cached.attrs)
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
    merged.attrs["splits"] = {
        **(cached.attrs.get("splits", {}) if cached is not None else {}),
        **fresh.attrs.get("splits", {}),
    }
    return merged


def _needs_refresh(
    cached: pd.Series | None, refresh_latest: bool, cache_file: Path | None = None
) -> bool:
    if cached is None or cached.empty:
        return True
    if not refresh_latest:
        return False
    # Avoid re-downloading multi-day history on every live tick if cache was updated recently
    if cache_file is not None and cache_file.exists():
        age_seconds = time.time() - cache_file.stat().st_mtime
        if age_seconds < 300:
            return False
    return True


def _fetch_single_live_price(ticker: str) -> tuple[str, float | None, bool]:
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None)
        if price and float(price) > 0:
            return ticker, float(price), False
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "too many requests" in msg or "rate limit" in msg:
            return ticker, None, True
    return ticker, None, False


def _fetch_live_prices(tickers: list[str]) -> dict[str, float]:
    from concurrent.futures import ThreadPoolExecutor

    global _live_rate_limited_until
    if not tickers:
        return {}

    now = time.monotonic()
    live: dict[str, float] = {}
    to_query: list[str] = []

    with _live_quote_lock:
        rate_limited = now < _live_rate_limited_until
        for ticker in sorted(set(tickers)):
            cached = _live_quote_memo.get(ticker)
            if cached is not None and (now - cached[0]) < _LIVE_QUOTE_TTL_SECONDS:
                live[ticker] = cached[1]
            elif rate_limited and cached is not None:
                live[ticker] = cached[1]
            elif not rate_limited:
                to_query.append(ticker)

    if not to_query:
        return live

    saw_rate_limit = False
    fresh: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(to_query))) as pool:
        for ticker, price, hit_limit in pool.map(_fetch_single_live_price, to_query):
            if hit_limit:
                saw_rate_limit = True
            if price is not None and price > 0:
                fresh[ticker] = price
                live[ticker] = price

    stamp = time.monotonic()
    with _live_quote_lock:
        for ticker, price in fresh.items():
            _live_quote_memo[ticker] = (stamp, price)
        if saw_rate_limit:
            _live_rate_limited_until = stamp + _LIVE_RATE_LIMIT_COOLDOWN_SECONDS
            for ticker in to_query:
                if ticker not in live and ticker in _live_quote_memo:
                    live[ticker] = _live_quote_memo[ticker][1]
    return live


def _apply_live_quote(series: pd.Series, price: float) -> pd.Series:
    if series.empty or price <= 0:
        return series
    updated = series.copy()
    today = warsaw_today()
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
    adjusted: bool = True,
) -> dict[str, pd.Series]:
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, pd.Series] = {}
    pending: list[tuple[str, str, pd.Series | None]] = []

    for ticker in tickers:
        cache_file = _cache_path(ticker, adjusted)
        cached = _load_cached_series(cache_file) if use_cache else None
        if (
            cached is None
            or cached.empty
            or cached.index.min() > pd.Timestamp(start) + pd.Timedelta(days=4)
            or cached.index.max() < pd.Timestamp(end) - pd.Timedelta(days=4)
            or _needs_refresh(cached, refresh_latest, cache_file if use_cache else None)
        ):
            fetch_start = start
            if (
                cached is not None
                and not cached.empty
                and cached.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=4)
            ):
                fetch_start = (cached.index.max() - pd.Timedelta(days=7)).date().isoformat()
            pending.append((ticker, fetch_start, cached))
        else:
            resolved[ticker] = cached.loc[pd.Timestamp(start) :]  # type: ignore[union-attr]

    if pending:
        batch_start = min(item[1] for item in pending)
        batch_tickers = [item[0] for item in pending]
        fresh_map = _download_close_batch(batch_tickers, batch_start, end, adjusted)
        for ticker, _, cached in pending:
            fresh = fresh_map.get(ticker, pd.Series(dtype=float))
            series = _merge_price_series(cached, fresh, start)
            if not series.empty and use_cache:
                series.to_frame("close").to_parquet(_cache_path(ticker, adjusted))
            if not series.empty:
                resolved[ticker] = series

    if refresh_latest and resolved:
        live_prices = _fetch_live_prices(list(resolved.keys()))
        for ticker, series in resolved.items():
            if ticker in live_prices:
                resolved[ticker] = _apply_live_quote(series, live_prices[ticker])

    return {
        ticker: series.loc[pd.Timestamp(start) : pd.Timestamp(end) - pd.Timedelta(days=1)]
        for ticker, series in resolved.items()
    }


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
    resolved = _resolve_tickers(tickers, start, end, use_cache, refresh_latest, adjusted=False)

    frames: list[pd.Series] = []
    for ticker, series in resolved.items():
        if series.empty:
            continue
        xtb_symbol = reverse_map.get(ticker, ticker)
        frames.append(series.rename(xtb_symbol))

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, axis=1).sort_index().ffill()
    result.attrs["splits"] = {
        reverse_map.get(t, t): s.attrs.get("splits", {}) for t, s in resolved.items()
    }
    return result


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
