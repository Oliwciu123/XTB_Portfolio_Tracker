from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

TransactionType = Literal[
    "buy",
    "sell",
    "transfer_in",
    "transfer_out",
    "dividend",
    "withholding_tax",
    "interest",
    "interest_tax",
    "close_trade",
    "other",
]


@dataclass
class Transaction:
    id: str
    account_id: str
    currency: str
    type: TransactionType
    timestamp: datetime
    symbol: str | None
    amount: Decimal
    shares: Decimal | None = None
    price: Decimal | None = None
    comment: str = ""
    realized_pnl: Decimal | None = None
    commission: Decimal | None = None
    raw_type: str = ""


@dataclass
class Account:
    account_id: str
    currency: str
    holder_name: str | None = None
    balance: Decimal | None = None
    equity: Decimal | None = None
    margin: Decimal | None = None
    free_margin: Decimal | None = None
    export_date: datetime | None = None
    transactions: list[Transaction] = field(default_factory=list)


@dataclass
class Position:
    symbol: str
    account_id: str
    currency: str
    shares: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal = Decimal("0")

    @property
    def cost_basis(self) -> Decimal:
        return self.shares * self.avg_cost


@dataclass
class HoldingSnapshot:
    symbol: str
    shares: Decimal
    avg_cost: Decimal
    market_price: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    weight: Decimal
    sector: str | None = None
    industry: str | None = None
