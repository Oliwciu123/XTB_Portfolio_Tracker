from __future__ import annotations

import pandas as pd

from xtb_analyzer.flows import extract_deposits
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account
from xtb_analyzer.prices import fetch_benchmarks

SP500_TR_TICKER = "^SP500TR"
NASDAQ100_TICKER = "^NDX"
# Backward-compatible alias (XNDX is unavailable on Yahoo Finance).
NASDAQ100_TR_TICKER = NASDAQ100_TICKER


def _simulate_deposit_benchmark(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str,
    index: pd.Series,
    series_name: str,
    fx: pd.DataFrame,
    deposits: list,
) -> pd.Series:
    currency = currency.lower()
    if calendar.empty or index.empty:
        return pd.Series(dtype=float, name=f"{series_name}_{currency}")

    index = index.reindex(calendar, method="ffill")
    units = 0.0
    values: list[float] = []
    deposit_idx = 0

    while deposit_idx < len(deposits) and deposits[deposit_idx].timestamp.date() < calendar[0].date():
        deposit_idx += 1

    for day in calendar:
        while deposit_idx < len(deposits) and deposits[deposit_idx].timestamp.date() <= day.date():
            deposit = deposits[deposit_idx]
            dep_day = pd.Timestamp(deposit.timestamp.date())
            price = float(index.loc[dep_day])
            if price <= 0:
                deposit_idx += 1
                continue
            fx_row = fx.loc[:dep_day].iloc[-1] if not fx.empty else pd.Series(dtype=float)
            amount = convert_value(
                float(deposit.amount_foreign),
                deposit.currency,
                currency.upper(),
                fx_row,
            )
            units += amount / price
            deposit_idx += 1

        values.append(units * float(index.loc[day]))

    return pd.Series(values, index=calendar, name=f"{series_name}_{currency}")


def build_deposit_benchmark(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    *,
    ticker: str = SP500_TR_TICKER,
    series_name: str = "sp500_benchmark",
    use_cache: bool = True,
    refresh_latest: bool = False,
    index_series: pd.Series | None = None,
    fx: pd.DataFrame | None = None,
) -> pd.Series:
    """Benchmark: buy index with each deposit at the moment of deposit."""
    deposits = extract_deposits(accounts)
    if not deposits or calendar.empty:
        return pd.Series(dtype=float, name=f"{series_name}_{currency.lower()}")

    first_deposit = pd.Timestamp(deposits[0].timestamp.date())
    calendar = calendar[calendar >= first_deposit]
    if calendar.empty:
        return pd.Series(dtype=float, name=f"{series_name}_{currency.lower()}")

    start = first_deposit.date().isoformat()
    end = (calendar[-1] + pd.Timedelta(days=1)).date().isoformat()

    if index_series is None:
        indices = fetch_benchmarks(
            [ticker],
            start=start,
            end=end,
            use_cache=use_cache,
            refresh_latest=refresh_latest,
        )
        index_series = indices.get(ticker, pd.Series(dtype=float))

    if fx is None:
        fx = fetch_fx_rates(start=start, end=end, use_cache=use_cache)

    return _simulate_deposit_benchmark(
        accounts,
        calendar,
        currency,
        index_series,
        series_name,
        fx,
        deposits,
    )


def build_deposit_benchmarks(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> tuple[pd.Series, pd.Series]:
    """Build S&P 500 and NASDAQ-100 benchmarks with one index batch fetch and one FX fetch."""
    deposits = extract_deposits(accounts)
    if not deposits or calendar.empty:
        empty = pd.Series(dtype=float)
        return empty, empty

    first_deposit = pd.Timestamp(deposits[0].timestamp.date())
    calendar = calendar[calendar >= first_deposit]
    if calendar.empty:
        empty = pd.Series(dtype=float)
        return empty, empty

    start = first_deposit.date().isoformat()
    end = (calendar[-1] + pd.Timedelta(days=1)).date().isoformat()
    indices = fetch_benchmarks(
        [SP500_TR_TICKER, NASDAQ100_TICKER],
        start=start,
        end=end,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
    fx = fetch_fx_rates(start=start, end=end, use_cache=use_cache)

    sp500 = _simulate_deposit_benchmark(
        accounts,
        calendar,
        currency,
        indices.get(SP500_TR_TICKER, pd.Series(dtype=float)),
        "sp500_benchmark",
        fx,
        deposits,
    )
    nasdaq = _simulate_deposit_benchmark(
        accounts,
        calendar,
        currency,
        indices.get(NASDAQ100_TICKER, pd.Series(dtype=float)),
        "nasdaq100_benchmark",
        fx,
        deposits,
    )
    return sp500, nasdaq


def build_sp500_deposit_benchmark(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> pd.Series:
    return build_deposit_benchmark(
        accounts,
        calendar,
        currency,
        ticker=SP500_TR_TICKER,
        series_name="sp500_benchmark",
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )


def build_nasdaq100_deposit_benchmark(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> pd.Series:
    return build_deposit_benchmark(
        accounts,
        calendar,
        currency,
        ticker=NASDAQ100_TICKER,
        series_name="nasdaq100_benchmark",
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
