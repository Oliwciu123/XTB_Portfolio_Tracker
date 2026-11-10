from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

CACHE_DIR = Path("data/cache/fx")


def _nbp_series(currency: str, start: str, end: str | None = None) -> pd.Series:
    """Return PLN per 1 unit of foreign currency (NBP table A)."""
    code = currency.lower()
    last = min(
        pd.Timestamp(end or pd.Timestamp.today()).normalize(), pd.Timestamp.today().normalize()
    )
    cursor = pd.Timestamp(start) - pd.Timedelta(days=14)
    rows = []
    while cursor <= last:
        chunk_end = min(cursor + pd.Timedelta(days=92), last)
        url = f"https://api.nbp.pl/api/exchangerates/rates/a/{code}/{cursor.date()}/{chunk_end.date()}/?format=json"
        response = requests.get(url, timeout=30)
        if response.status_code != 404:
            response.raise_for_status()
            rows.extend(response.json()["rates"])
        cursor = chunk_end + pd.Timedelta(days=1)
    index = pd.to_datetime([row["effectiveDate"] for row in rows])
    values = [row["mid"] for row in rows]
    series = pd.Series(values, index=index, name=f"{currency.upper()}PLN")
    return series[~series.index.duplicated(keep="last")].sort_index()


def _yahoo_fx_series(pair: str, start: str, end: str | None = None) -> pd.Series:
    data = yf.download(pair, start=start, end=end, progress=False, auto_adjust=True)
    if data.empty:
        return pd.Series(dtype=float, name=pair)
    if isinstance(data.columns, pd.MultiIndex):
        series = data["Close", pair] if ("Close", pair) in data.columns else data.iloc[:, 0]
    else:
        series = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.sort_index().ffill().rename(pair)


def _apply_live_fx(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    from xtb_analyzer.prices import _fetch_live_prices

    live = _fetch_live_prices(["USDPLN=X", "EURPLN=X", "EURUSD=X"])
    if not live:
        return frame
    updated = frame.copy()
    today = pd.Timestamp.today().normalize()
    if today not in updated.index:
        updated.loc[today] = updated.iloc[-1]
    if "USDPLN=X" in live:
        updated.loc[today, "USDPLN"] = live["USDPLN=X"]
    if "EURPLN=X" in live:
        updated.loc[today, "EURPLN"] = live["EURPLN=X"]
    updated["EURUSD"] = updated["EURPLN"] / updated["USDPLN"]
    updated["USDEUR"] = 1.0 / updated["EURUSD"]
    return updated.sort_index().ffill()


def fetch_fx_rates(
    start: str,
    end: str | None = None,
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "fx_rates_v2.parquet"
    end = end or (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).date().isoformat()
    lookback_start = pd.Timestamp(start) - pd.Timedelta(days=14)

    if use_cache and cache_file.exists():
        cached = pd.read_parquet(cache_file)
        cached.index = pd.to_datetime(cached.index)
        needs_refresh = cached.empty or cached.index.max().date() < pd.Timestamp(
            end
        ).date() - pd.Timedelta(days=4)
        if not cached.empty and cached.index.min() <= pd.Timestamp(start) and not needs_refresh:
            nbp_snapshot = cached.copy()
            if refresh_latest:
                cached = _apply_live_fx(cached)
            cached.attrs["nbp_table_a"] = nbp_snapshot
            return cached.loc[lookback_start:end]

    nbp_sourced = False
    try:
        usd_pln = _nbp_series("usd", start, end)
        eur_pln = _nbp_series("eur", start, end)
        nbp_sourced = True
    except Exception:
        prior = lookback_start.date().isoformat()
        usd_pln = _yahoo_fx_series("USDPLN=X", prior, end).rename("USDPLN")
        eur_pln = _yahoo_fx_series("EURPLN=X", prior, end).rename("EURPLN")

    eur_usd = eur_pln / usd_pln

    frame = (
        pd.DataFrame(
            {
                "USDPLN": usd_pln,
                "EURPLN": eur_pln,
                "EURUSD": eur_usd,
            }
        )
        .sort_index()
        .ffill()
    )

    frame["USDEUR"] = 1 / frame["EURUSD"]
    if frame.empty or frame[["USDPLN", "EURPLN"]].dropna().empty:
        raise ValueError("No FX rates available. Check connectivity to NBP and Yahoo Finance.")
    nbp_snapshot = frame.copy()
    if use_cache:
        nbp_snapshot.to_parquet(cache_file)
    if refresh_latest:
        frame = _apply_live_fx(frame)
    if nbp_sourced:
        frame.attrs["nbp_table_a"] = nbp_snapshot
    return frame.loc[lookback_start:end]


def fetch_nbp_currency_series(
    currency: str,
    start: str,
    end: str | None = None,
    use_cache: bool = True,
) -> pd.Series:
    """Fetch official NBP Table A mid rates (PLN per 1 unit) with local parquet caching."""
    code = currency.upper()
    if code == "PLN":
        idx = pd.date_range(
            pd.Timestamp(start) - pd.Timedelta(days=14), end or pd.Timestamp.today()
        )
        return pd.Series(1.0, index=idx, name="PLNPLN")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"nbp_table_a_{code.lower()}.parquet"
    end_str = end or (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).date().isoformat()
    lookback_start = pd.Timestamp(start) - pd.Timedelta(days=14)

    if use_cache and cache_file.exists():
        cached_df = pd.read_parquet(cache_file)
        cached = cached_df.iloc[:, 0]
        cached.index = pd.to_datetime(cached.index)
        needs_refresh = cached.empty or cached.index.max().date() < pd.Timestamp(
            end_str
        ).date() - pd.Timedelta(days=4)
        if not cached.empty and cached.index.min() <= pd.Timestamp(start) and not needs_refresh:
            return cached.loc[lookback_start:end_str].rename(f"{code}PLN")

    series = _nbp_series(code, start, end_str)
    if use_cache and not series.empty:
        series.to_frame(name=f"{code}PLN").to_parquet(cache_file)
    return series.loc[lookback_start:end_str]


def convert_value(amount: float, from_currency: str, to_currency: str, fx_row: pd.Series) -> float:
    if from_currency == to_currency:
        return amount

    rates: dict[tuple[str, str], float | None] = {
        ("USD", "PLN"): fx_row.get("USDPLN"),
        ("EUR", "PLN"): fx_row.get("EURPLN"),
        ("EUR", "USD"): fx_row.get("EURUSD"),
        ("USD", "EUR"): fx_row.get("USDEUR"),
        ("PLN", "USD"): 1 / fx_row.get("USDPLN") if fx_row.get("USDPLN") else None,
        ("PLN", "EUR"): 1 / fx_row.get("EURPLN") if fx_row.get("EURPLN") else None,
    }
    direct = rates.get((from_currency, to_currency))
    if direct is not None and pd.notna(direct) and direct > 0:
        return amount * float(direct)
    raise ValueError(
        f"Missing valid exchange rate {from_currency}/{to_currency}; valuation stopped."
    )
