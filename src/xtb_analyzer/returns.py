"""Return measures: ROI (simple), XIRR (money-weighted) and TWR (time-weighted).

All three answer "how did the portfolio perform?" but from different angles:

- ROI  – final value / total deposits - 1. Ignores timing of deposits.
- XIRR – annualized internal rate of return of the external cash flows.
  Reflects the investor's actual money-weighted experience.
- TWR  – chain-linked daily returns with deposits neutralized. Measures the
  quality of investment decisions independent of deposit timing, which makes
  it directly comparable with benchmark indices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from xtb_analyzer.flows import extract_deposits
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account

DAYS_IN_YEAR = 365.25


@dataclass
class CashFlow:
    date: pd.Timestamp
    amount: float  # negative = money invested, positive = money received / final value


@dataclass
class ReturnMeasures:
    currency: str
    as_of: str
    invested: float
    final_value: float
    gain: float
    period_days: int
    roi: float
    mwr: float | None
    """Money-weighted return over the whole holding period (not annualized)."""
    xirr: float | None
    """Annualized money-weighted return (IRR)."""
    twr: float
    twr_annualized: float | None


def xirr(flows: list[CashFlow]) -> float | None:
    """Annualized internal rate of return (ACT/365.25), solved by bisection."""
    if len(flows) < 2:
        return None
    amounts = np.array([flow.amount for flow in flows], dtype=float)
    if not (amounts > 0).any() or not (amounts < 0).any():
        return None

    t0 = min(flow.date for flow in flows)
    years = np.array([(flow.date - t0).days / DAYS_IN_YEAR for flow in flows])

    def npv(rate: float) -> float:
        return float(np.sum(amounts / np.power(1.0 + rate, years)))

    low, high = -0.9999, 100.0
    f_low, f_high = npv(low), npv(high)
    if np.isnan(f_low) or np.isnan(f_high) or f_low * f_high > 0:
        return None

    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def build_external_cash_flows(
    accounts: list[Account],
    nav: pd.DataFrame,
    currency: str = "pln",
    fx: pd.DataFrame | None = None,
    use_cache: bool = True,
) -> list[CashFlow]:
    """External flows in the report currency: deposits (negative) + final NAV (positive)."""
    currency = currency.lower()
    deposits = extract_deposits(accounts)
    if not deposits or nav.empty:
        return []

    if currency != "pln" and fx is None:
        fx = fetch_fx_rates(
            start=pd.Timestamp(deposits[0].timestamp.date()).date().isoformat(),
            end=(nav.index[-1] + pd.Timedelta(days=1)).date().isoformat(),
            use_cache=use_cache,
        )

    flows: list[CashFlow] = []
    for deposit in deposits:
        day = pd.Timestamp(deposit.timestamp.date())
        if currency == "pln":
            amount = float(deposit.pln_spent)
        else:
            fx_row = fx.loc[:day].iloc[-1] if fx is not None and not fx.empty else pd.Series(dtype=float)
            amount = convert_value(float(deposit.amount_foreign), deposit.currency, currency.upper(), fx_row)
        flows.append(CashFlow(date=day, amount=-amount))

    final_value = float(nav[f"nav_{currency}"].iloc[-1])
    flows.append(CashFlow(date=nav.index[-1], amount=final_value))
    return flows


def twr_daily_returns(nav: pd.DataFrame, currency: str = "pln") -> pd.Series:
    """Daily sub-period returns with deposits treated as start-of-day inflows.

    r_t = NAV_t / (NAV_{t-1} + F_t) - 1, starting from the first deposit day.
    """
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    if dep_col not in nav.columns:
        raise ValueError("NAV must include deposit columns. Run attach_deposits_to_nav() first.")

    active = nav[dep_col] > 0
    if not active.any():
        return pd.Series(dtype=float)
    view = nav.loc[nav.index[active][0] :, [nav_col, dep_col]].dropna(subset=[nav_col])

    values = view[nav_col].to_numpy(dtype=float)
    flows = view[dep_col].diff().fillna(view[dep_col].iloc[0]).to_numpy(dtype=float)

    returns = np.zeros(len(view))
    prev_nav = 0.0
    for i in range(len(view)):
        base = prev_nav + flows[i]
        returns[i] = values[i] / base - 1 if base > 0 else 0.0
        prev_nav = values[i]
    return pd.Series(returns, index=view.index, name=f"twr_{currency}")


def twr_wealth_index(daily_returns: pd.Series) -> pd.Series:
    """Cumulative growth of 1 unit invested (deposit-timing neutral)."""
    return (1 + daily_returns).cumprod()


def compute_return_measures(
    accounts: list[Account],
    nav: pd.DataFrame,
    currency: str = "pln",
    fx: pd.DataFrame | None = None,
    use_cache: bool = True,
) -> ReturnMeasures:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"

    invested = float(nav[dep_col].iloc[-1])
    final_value = float(nav[nav_col].iloc[-1])
    roi = final_value / invested - 1 if invested > 0 else 0.0

    flows = build_external_cash_flows(accounts, nav, currency, fx=fx, use_cache=use_cache)
    xirr_annual = xirr(flows)

    daily = twr_daily_returns(nav, currency)
    twr_total = float((1 + daily).prod() - 1) if not daily.empty else 0.0

    period_days = int((nav.index[-1] - flows[0].date).days) if flows else 0
    twr_annual = None
    if period_days >= 30 and twr_total > -1:
        twr_annual = float((1 + twr_total) ** (DAYS_IN_YEAR / period_days) - 1)

    # De-annualize XIRR to the actual holding period: the money-weighted
    # return "as of today", directly comparable with ROI and cumulative TWR.
    mwr_period = None
    if xirr_annual is not None and period_days > 0:
        mwr_period = float((1 + xirr_annual) ** (period_days / DAYS_IN_YEAR) - 1)

    return ReturnMeasures(
        currency=currency.upper(),
        as_of=nav.index[-1].strftime("%Y-%m-%d"),
        invested=invested,
        final_value=final_value,
        gain=final_value - invested,
        period_days=period_days,
        roi=roi,
        mwr=mwr_period,
        xirr=xirr_annual,
        twr=twr_total,
        twr_annualized=twr_annual,
    )
