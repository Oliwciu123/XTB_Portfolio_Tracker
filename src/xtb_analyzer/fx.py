from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

CACHE_DIR = Path("data/cache/fx")


def _nbp_series(currency: str, start: str, end: str | None = None) -> pd.Series:
    """Return PLN per 1 unit of foreign currency (NBP table A)."""
    code = currency.lower()
    end_part = end or pd.Timestamp.today().date().isoformat()
    url = f"https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end_part}/?format=json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    rows = payload["rates"]
    index = pd.to_datetime([row["effectiveDate"] for row in rows])
    values = [row["mid"] for row in rows]
    return pd.Series(values, index=index, name=f"{currency.upper()}PLN")


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


def fetch_fx_rates(start: str, end: str | None = None, use_cache: bool = True) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "fx_rates.parquet"

    if use_cache and cache_file.exists():
        cached = pd.read_parquet(cache_file)
        cached.index = pd.to_datetime(cached.index)
        if cached.index.min() <= pd.Timestamp(start):
            return cached.loc[start:end] if end else cached.loc[start:]

    try:
        usd_pln = _nbp_series("usd", start, end)
        eur_pln = _nbp_series("eur", start, end)
    except Exception:
        usd_pln = _yahoo_fx_series("USDPLN=X", start, end).rename("USDPLN")
        eur_pln = _yahoo_fx_series("EURPLN=X", start, end).rename("EURPLN")

    eur_usd = _yahoo_fx_series("EURUSD=X", start, end)

    frame = pd.DataFrame(
        {
            "USDPLN": usd_pln,
            "EURPLN": eur_pln,
            "EURUSD": eur_usd,
        }
    ).sort_index().ffill()

    frame["USDEUR"] = 1 / frame["EURUSD"]
    frame.to_parquet(cache_file)
    return frame.loc[start:end] if end else frame.loc[start:]


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
    if direct:
        return amount * float(direct)

    if from_currency == "PLN":
        return amount
    pln_value = convert_value(amount, from_currency, "PLN", fx_row)
    return convert_value(pln_value, "PLN", to_currency, fx_row)
