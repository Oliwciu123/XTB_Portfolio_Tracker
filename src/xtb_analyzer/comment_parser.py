from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

OPEN_BUY_RE = re.compile(
    r"OPEN BUY\s+(?:(?P<fill>[\d.]+)/(?P<total>[\d.]+)\s+@\s+|(?P<qty>[\d.]+)\s+@\s+)(?P<price>[\d.]+)",
    re.IGNORECASE,
)
CLOSE_BUY_RE = re.compile(
    r"CLOSE BUY\s+(?:(?P<fill>[\d.]+)/(?P<total>[\d.]+)\s+@\s+|(?P<qty>[\d.]+)\s+@\s+)(?P<price>[\d.]+)",
    re.IGNORECASE,
)
TRANSFER_RE = re.compile(
    r"Currency conversion,\s*PLN to (?P<currency>USD|EUR)",
    re.IGNORECASE,
)
EXCHANGE_RATE_RE = re.compile(r"Exchange rate:\s*([\d.]+)", re.IGNORECASE)


@dataclass
class TradeComment:
    side: str
    shares: Decimal
    price: Decimal
    fill: Decimal | None = None
    total: Decimal | None = None


def parse_trade_comment(comment: str, side: str) -> TradeComment | None:
    pattern = OPEN_BUY_RE if side == "buy" else CLOSE_BUY_RE
    match = pattern.search(comment)
    if not match:
        return None

    groups = match.groupdict()
    if groups["qty"]:
        shares = Decimal(groups["qty"])
        fill = total = None
    else:
        shares = Decimal(groups["fill"])
        fill = Decimal(groups["fill"])
        total = Decimal(groups["total"])

    return TradeComment(
        side=side,
        shares=shares,
        price=Decimal(groups["price"]),
        fill=fill,
        total=total,
    )


def is_transfer_in(comment: str) -> bool:
    return bool(TRANSFER_RE.search(comment))


def transfer_target_currency(comment: str) -> str | None:
    match = TRANSFER_RE.search(comment)
    return match.group("currency").upper() if match else None


def parse_exchange_rate(comment: str) -> Decimal | None:
    match = EXCHANGE_RATE_RE.search(comment)
    return Decimal(match.group(1)) if match else None
