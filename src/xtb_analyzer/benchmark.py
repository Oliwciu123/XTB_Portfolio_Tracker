from __future__ import annotations

import pandas as pd

from xtb_analyzer.flows import extract_deposits
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account
from xtb_analyzer.prices import fetch_benchmarks

SP500_TR_TICKER = "^SP500TR"
NASDAQ100_TICKER = "^NDX"
# iShares MSCI ACWI ETF - liquid proxy for the MSCI All Country World Index.
ACWI_TICKER = "ACWI"
# Philadelphia Semiconductor Index (PHLX Semiconductor Sector).
SOX_TICKER = "^SOX"
# Backward-compatible alias (XNDX is unavailable on Yahoo Finance).
NASDAQ100_TR_TICKER = NASDAQ100_TICKER

BENCHMARK_TICKERS: dict[str, str] = {
    "sp500": SP500_TR_TICKER,
    "nasdaq100": NASDAQ100_TICKER,
    "acwi": ACWI_TICKER,
    "sox": SOX_TICKER,
}


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


def build_benchmark_suite(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> dict[str, pd.Series]:
    """Deposit-matched benchmarks for all configured indices in one batch fetch.

    Returns a dict keyed by ``BENCHMARK_TICKERS`` keys (sp500, nasdaq100, acwi).
    """
    deposits = extract_deposits(accounts)
    if not deposits or calendar.empty:
        return {key: pd.Series(dtype=float) for key in BENCHMARK_TICKERS}

    first_deposit = pd.Timestamp(deposits[0].timestamp.date())
    calendar = calendar[calendar >= first_deposit]
    if calendar.empty:
        return {key: pd.Series(dtype=float) for key in BENCHMARK_TICKERS}

    start = first_deposit.date().isoformat()
    end = (calendar[-1] + pd.Timedelta(days=1)).date().isoformat()
    indices = fetch_benchmarks(
        list(BENCHMARK_TICKERS.values()),
        start=start,
        end=end,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
    fx = fetch_fx_rates(start=start, end=end, use_cache=use_cache)

    return {
        key: _simulate_deposit_benchmark(
            accounts,
            calendar,
            currency,
            indices.get(ticker, pd.Series(dtype=float)),
            f"{key}_benchmark",
            fx,
            deposits,
        )
        for key, ticker in BENCHMARK_TICKERS.items()
    }


def build_deposit_benchmarks(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = False,
) -> tuple[pd.Series, pd.Series]:
    """Backward-compatible wrapper returning (S&P 500, NASDAQ 100)."""
    suite = build_benchmark_suite(accounts, calendar, currency, use_cache, refresh_latest)
    return suite["sp500"], suite["nasdaq100"]


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
