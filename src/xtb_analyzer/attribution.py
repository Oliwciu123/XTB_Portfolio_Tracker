"""FX attribution: split total PLN gain into investment gain vs currency gain.

For every currency c the assets denominated in c are worth V_c (in c),
D_c units of c were bought with P_c PLN. With the current rate fx_c (PLN per
unit of c):

- investment gain = (V_c - D_c) * fx_c   (what the investments earned, in PLN
  at today's rate)
- currency gain   = D_c * fx_c - P_c     (what holding the currency itself
  earned or lost, including XTB conversion spread vs the market rate)

The two components sum exactly to NAV_pln - deposits_pln.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from xtb_analyzer.comment_parser import TRANSFER_RE, parse_exchange_rate
from xtb_analyzer.flows import extract_deposits
from xtb_analyzer.fx import fetch_fx_rates
from xtb_analyzer.models import Account

_FX_COLUMN = {"USD": "USDPLN", "EUR": "EURPLN"}


@dataclass
class FxAttribution:
    series: pd.DataFrame
    """Daily decomposition: investment_gain_pln, fx_gain_pln, total_gain_pln."""
    by_currency: pd.DataFrame
    """Final decomposition per currency."""
    investment_gain_pln: float
    fx_gain_pln: float
    total_gain_pln: float


def _cumulative_deposits_by_currency(
    accounts: list[Account],
    calendar: pd.DatetimeIndex,
    fx: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cumulative foreign units received (D_c) and PLN spent (P_c) per currency."""
    deposits = extract_deposits(accounts, fx=fx)
    currencies = ("PLN", "USD", "EUR")
    foreign = pd.DataFrame(0.0, index=calendar, columns=currencies)
    pln_cost = pd.DataFrame(0.0, index=calendar, columns=currencies)

    for deposit in deposits:
        day = pd.Timestamp(deposit.timestamp.date())
        mask = calendar >= day
        currency = deposit.currency if deposit.currency in currencies else "PLN"
        foreign.loc[mask, currency] += float(deposit.amount_foreign)
        pln_cost.loc[mask, currency] += float(deposit.pln_spent)
    present = {account.currency for account in accounts}
    transactions = sorted(
        (tx for account in accounts for tx in account.transactions), key=lambda tx: tx.timestamp
    )
    for tx in transactions:
        conversion = TRANSFER_RE.search(tx.comment)
        if not conversion or tx.amount <= 0:
            continue
        source, target = conversion.group("source").upper(), conversion.group("currency").upper()
        if source not in present or target not in present or tx.currency != target:
            continue
        rate = parse_exchange_rate(tx.comment)
        if not rate or rate <= 0:
            raise ValueError("Missing internal conversion rate; FX attribution is unavailable.")
        day = pd.Timestamp(tx.timestamp.date())
        mask = calendar >= day
        if not mask.any():
            continue
        row = foreign.loc[mask].iloc[0]
        cost = pln_cost.loc[mask].iloc[0]
        source_amount = float(tx.amount / rate)
        basis = source_amount * cost[source] / row[source] if row[source] else 0.0
        foreign.loc[mask, source] -= source_amount
        foreign.loc[mask, target] += float(tx.amount)
        pln_cost.loc[mask, source] -= basis
        pln_cost.loc[mask, target] += basis
    return foreign, pln_cost


def compute_fx_attribution(
    accounts: list[Account],
    nav: pd.DataFrame,
    fx: pd.DataFrame | None = None,
    use_cache: bool = True,
) -> FxAttribution:
    if nav.empty or "local_usd" not in nav.columns:
        raise ValueError("NAV must include local_* columns. Rebuild it with build_nav_series().")
    if "deposits_pln" not in nav.columns:
        raise ValueError("NAV must include deposit columns. Run attach_deposits_to_nav() first.")

    active = nav["deposits_pln"] > 0
    if not active.any():
        raise ValueError("No deposits found; FX attribution is undefined.")
    view = nav.loc[nav.index[active][0] :]

    if fx is None:
        fx = fetch_fx_rates(
            start=view.index[0].date().isoformat(),
            end=(view.index[-1] + pd.Timedelta(days=1)).date().isoformat(),
            use_cache=use_cache,
        )
    fx_aligned = fx.reindex(view.index, method="ffill").ffill().bfill()

    foreign, pln_cost = _cumulative_deposits_by_currency(accounts, view.index, fx=fx)

    investment = pd.Series(0.0, index=view.index)
    fx_gain = pd.Series(0.0, index=view.index)
    currency_rows: list[dict] = []

    for currency in ("PLN", "USD", "EUR"):
        local_value = view[f"local_{currency.lower()}"].astype(float)
        deposited_units = foreign[currency]
        spent_pln = pln_cost[currency]
        rate = (
            fx_aligned[_FX_COLUMN[currency]]
            if currency in _FX_COLUMN
            else pd.Series(1.0, index=view.index)
        )

        inv_c = (local_value - deposited_units) * rate
        fx_c = deposited_units * rate - spent_pln
        investment += inv_c
        fx_gain += fx_c

        final_units = float(deposited_units.iloc[-1])
        if final_units == 0 and float(local_value.iloc[-1]) == 0:
            continue
        currency_rows.append(
            {
                "currency": currency,
                "pln_spent": float(spent_pln.iloc[-1]),
                "units_received": final_units,
                "avg_deposit_rate": float(spent_pln.iloc[-1]) / final_units
                if final_units
                else None,
                "current_rate": float(rate.iloc[-1]),
                "current_value_local": float(local_value.iloc[-1]),
                "investment_gain_pln": float(inv_c.iloc[-1]),
                "fx_gain_pln": float(fx_c.iloc[-1]),
                "total_gain_pln": float(inv_c.iloc[-1] + fx_c.iloc[-1]),
            }
        )

    series = pd.DataFrame(
        {
            "investment_gain_pln": investment,
            "fx_gain_pln": fx_gain,
            "total_gain_pln": investment + fx_gain,
        }
    )
    return FxAttribution(
        series=series,
        by_currency=pd.DataFrame(currency_rows),
        investment_gain_pln=float(investment.iloc[-1]),
        fx_gain_pln=float(fx_gain.iloc[-1]),
        total_gain_pln=float(investment.iloc[-1] + fx_gain.iloc[-1]),
    )
