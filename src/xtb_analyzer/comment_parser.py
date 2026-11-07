from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# Newer xStation comments put the ticker between the side and the size:
# "OPEN BUY APP.US 2 @ 10.50" / "CLOSE BUY UBER.US 1.5/3 @ 70.00".
# Older comments omit it: "OPEN BUY 1/1.5 @ 251.27".
_TICKER = r"(?P<ticker>[A-Za-z][A-Za-z0-9.]*)"
_SIZE_AT_PRICE = r"(?:(?P<fill>[\d.]+)/(?P<total>[\d.]+)|(?P<qty>[\d.]+))\s+@\s+(?P<price>[\d.]+)"
OPEN_BUY_RE = re.compile(
    rf"OPEN BUY\s+(?:{_TICKER}\s+)?{_SIZE_AT_PRICE}",
    re.IGNORECASE,
)
CLOSE_BUY_RE = re.compile(
    rf"CLOSE BUY\s+(?:{_TICKER}\s+)?{_SIZE_AT_PRICE}",
    re.IGNORECASE,
)
TRANSFER_RE = re.compile(
    r"Currency conversion,\s*(?P<source>PLN|USD|EUR)\s+to\s+(?P<currency>USD|EUR|PLN)",
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
    ticker: str | None = None


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

    ticker = (groups.get("ticker") or "").strip() or None
    return TradeComment(
        side=side,
        shares=shares,
        price=Decimal(groups["price"]),
        fill=fill,
        total=total,
        ticker=ticker.upper() if ticker else None,
    )


def is_transfer_in(comment: str) -> bool:
    return bool(TRANSFER_RE.search(comment))


def transfer_target_currency(comment: str) -> str | None:
    match = TRANSFER_RE.search(comment)
    return match.group("currency").upper() if match else None


def parse_exchange_rate(comment: str) -> Decimal | None:
    match = EXCHANGE_RATE_RE.search(comment)
    return Decimal(match.group(1)) if match else None
