from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account, Position, Transaction
from xtb_analyzer.positions import apply_transaction
from xtb_analyzer.prices import fetch_prices


@dataclass
class DailyState:
    cash: dict[str, Decimal] = field(default_factory=dict)
    positions: dict[tuple[str, str], Position] = field(default_factory=dict)


def _account_currency(account_id: str, accounts: list[Account]) -> str:
    for account in accounts:
        if account.account_id == account_id:
            return account.currency
    return "USD"


def _apply_tx(state: DailyState, tx: Transaction) -> None:
    account_key = f"{tx.account_id}:{tx.currency}"
    state.cash[account_key] = state.cash.get(account_key, Decimal("0")) + tx.amount
    if tx.type != "close_trade":
        apply_transaction(state.positions, tx)


def build_nav_series(
    accounts: list[Account],
    use_cache: bool = True,
    live_prices: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    transactions = sorted(
        (tx for account in accounts for tx in account.transactions),
        key=lambda tx: tx.timestamp,
    )
    if not transactions:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    start = transactions[0].timestamp.date().isoformat()
    end = (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).date().isoformat()

    symbols = sorted({tx.symbol for tx in transactions if tx.symbol})
    prices = fetch_prices(
        symbols,
        start=start,
        end=end,
        use_cache=use_cache,
        refresh_latest=live_prices,
    )
    fx = fetch_fx_rates(start=start, end=end, use_cache=use_cache and not live_prices)

    if prices.empty:
        raise ValueError("No historical prices available for portfolio symbols")

    calendar = prices.index.union(
        pd.DatetimeIndex([pd.Timestamp(tx.timestamp.date()) for tx in transactions])
    ).unique().sort_values()

    tx_by_day: dict[pd.Timestamp, list[Transaction]] = {}
    for tx in transactions:
        day = pd.Timestamp(tx.timestamp.date())
        tx_by_day.setdefault(day, []).append(tx)

    state = DailyState()
    nav_rows: list[dict] = []
    holdings_rows: list[dict] = []

    for day in calendar:
        for tx in tx_by_day.get(day, []):
            _apply_tx(state, tx)

        day_prices = prices.loc[:day].iloc[-1]
        fx_row = fx.loc[:day].iloc[-1] if not fx.empty else pd.Series(dtype=float)

        cash_total = {"PLN": 0.0, "USD": 0.0, "EUR": 0.0}
        holdings_total = {"PLN": 0.0, "USD": 0.0, "EUR": 0.0}
        holdings_breakdown: dict[str, float] = {}

        for account_key, cash in state.cash.items():
            currency = account_key.split(":")[-1]
            for target in cash_total:
                cash_total[target] += convert_value(float(cash), currency, target, fx_row)

        for (account_id, symbol), pos in state.positions.items():
            if pos.shares <= 0:
                continue
            currency = _account_currency(account_id, accounts)
            price = float(day_prices.get(symbol, 0) or 0)
            market_value = float(pos.shares) * price
            holdings_breakdown[symbol] = holdings_breakdown.get(symbol, 0.0) + market_value
            for target in holdings_total:
                holdings_total[target] += convert_value(market_value, currency, target, fx_row)

        row: dict = {"date": day}
        for currency in ("pln", "usd", "eur"):
            upper = currency.upper()
            row[f"cash_{currency}"] = cash_total[upper]
            row[f"holdings_{currency}"] = holdings_total[upper]
            row[f"nav_{currency}"] = cash_total[upper] + holdings_total[upper]
        nav_rows.append(row)

        for symbol, value in holdings_breakdown.items():
            holdings_rows.append({"date": day, "symbol": symbol, "market_value_local": value})

    nav = pd.DataFrame(nav_rows).set_index("date")
    holdings = pd.DataFrame(holdings_rows)
    positions = _positions_frame(state, accounts, prices.iloc[-1], fx.iloc[-1] if not fx.empty else pd.Series())
    return nav, holdings, positions


def _positions_frame(
    state: DailyState,
    accounts: list[Account],
    latest_prices: pd.Series,
    fx_row: pd.Series,
) -> pd.DataFrame:
    rows = []
    for (account_id, symbol), pos in state.positions.items():
        if pos.shares <= 0:
            continue
        currency = _account_currency(account_id, accounts)
        price = float(latest_prices.get(symbol, 0) or 0)
        market_value = float(pos.shares) * price
        cost_basis = float(pos.cost_basis)
        rows.append(
            {
                "account_id": account_id,
                "symbol": symbol,
                "currency": currency,
                "shares": float(pos.shares),
                "avg_cost": float(pos.avg_cost),
                "market_price": price,
                "cost_basis": cost_basis,
                "market_value": market_value,
                "unrealized_pnl": market_value - cost_basis,
                "market_value_pln": convert_value(market_value, currency, "PLN", fx_row),
                "market_value_usd": convert_value(market_value, currency, "USD", fx_row),
                "market_value_eur": convert_value(market_value, currency, "EUR", fx_row),
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        total = frame["market_value_pln"].sum()
        frame["weight"] = frame["market_value_pln"] / total if total else 0.0
    return frame
