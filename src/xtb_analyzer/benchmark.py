from __future__ import annotations

import pandas as pd

from xtb_analyzer.flows import Deposit, extract_deposits
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account
from xtb_analyzer.prices import fetch_benchmark


def build_sp500_deposit_benchmark(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    currency: str = "pln",
    use_cache: bool = True,
) -> pd.Series:
    """Benchmark: buy S&P 500 with each deposit at the moment of deposit."""
    currency = currency.lower()
    deposits = extract_deposits(accounts)
    if not deposits or calendar.empty:
        return pd.Series(dtype=float, name=f"sp500_benchmark_{currency}")

    first_deposit = pd.Timestamp(deposits[0].timestamp.date())
    calendar = calendar[calendar >= first_deposit]
    if calendar.empty:
        return pd.Series(dtype=float, name=f"sp500_benchmark_{currency}")

    start = first_deposit.date().isoformat()
    end = (calendar[-1] + pd.Timedelta(days=1)).date().isoformat()
    sp500 = fetch_benchmark(start=start, end=end, use_cache=use_cache, refresh_latest=True)
    if sp500.empty:
        return pd.Series(dtype=float, name=f"sp500_benchmark_{currency}")

    sp500 = sp500.reindex(calendar, method="ffill")
    fx = fetch_fx_rates(start=start, end=end, use_cache=use_cache)

    units = 0.0
    values: list[float] = []
    deposit_idx = 0

    while deposit_idx < len(deposits) and deposits[deposit_idx].timestamp.date() < calendar[0].date():
        deposit_idx += 1

    for day in calendar:
        while deposit_idx < len(deposits) and deposits[deposit_idx].timestamp.date() <= day.date():
            deposit = deposits[deposit_idx]
            dep_day = pd.Timestamp(deposit.timestamp.date())
            price = float(sp500.loc[dep_day])
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

        values.append(units * float(sp500.loc[day]))

    return pd.Series(values, index=calendar, name=f"sp500_benchmark_{currency}")
