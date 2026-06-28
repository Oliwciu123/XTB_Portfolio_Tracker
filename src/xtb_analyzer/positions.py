from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from xtb_analyzer.models import Account, Position, Transaction


def _position_key(account_id: str, symbol: str) -> tuple[str, str]:
    return (account_id, symbol)


def apply_transaction(positions: dict[tuple[str, str], Position], tx: Transaction) -> None:
    if tx.type == "buy" and tx.symbol and tx.shares:
        key = _position_key(tx.account_id, tx.symbol)
        price = tx.price or (abs(tx.amount) / tx.shares)
        if key in positions:
            pos = positions[key]
            total_shares = pos.shares + tx.shares
            if total_shares > 0:
                pos.avg_cost = ((pos.shares * pos.avg_cost) + (tx.shares * price)) / total_shares
            pos.shares = total_shares
        else:
            positions[key] = Position(
                symbol=tx.symbol,
                account_id=tx.account_id,
                currency=tx.currency,
                shares=tx.shares,
                avg_cost=price,
            )
    elif tx.type == "sell" and tx.symbol and tx.shares:
        key = _position_key(tx.account_id, tx.symbol)
        if key not in positions:
            return
        pos = positions[key]
        pos.shares -= tx.shares
        if pos.shares <= 0:
            del positions[key]


def build_positions(accounts: list[Account]) -> dict[tuple[str, str], Position]:
    positions: dict[tuple[str, str], Position] = {}
    transactions = sorted(
        (tx for account in accounts for tx in account.transactions),
        key=lambda tx: tx.timestamp,
    )
    for tx in transactions:
        apply_transaction(positions, tx)
    return positions


def positions_dataframe(positions: dict[tuple[str, str], Position]):
    import pandas as pd

    rows = []
    for pos in positions.values():
        rows.append(
            {
                "account_id": pos.account_id,
                "symbol": pos.symbol,
                "currency": pos.currency,
                "shares": float(pos.shares),
                "avg_cost": float(pos.avg_cost),
                "cost_basis": float(pos.cost_basis),
            }
        )
    return pd.DataFrame(rows)
