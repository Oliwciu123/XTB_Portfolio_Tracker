from decimal import Decimal

from xtb_analyzer.comment_parser import parse_trade_comment


def test_german_decimal_price_in_comment():
    trade = parse_trade_comment("OPEN BUY 0.2546/2.2546 @ 78.050", "buy")
    assert trade is not None
    assert trade.shares == Decimal("0.2546")
    assert trade.price == Decimal("78.050")


def test_close_partial_position():
    trade = parse_trade_comment("CLOSE BUY 1.552/2.2167 @ 247.03", "sell")
    assert trade is not None
    assert trade.shares == Decimal("1.552")
    assert trade.price == Decimal("247.03")


def test_comment_with_ticker_before_size():
    """xStation sometimes writes the ticker inside the trade comment."""
    buy = parse_trade_comment("OPEN BUY APP.US 2 @ 10.50", "buy")
    assert buy is not None
    assert buy.ticker == "APP.US"
    assert buy.shares == Decimal("2")
    assert buy.price == Decimal("10.50")

    sell = parse_trade_comment("CLOSE BUY UBER.US 1.5/3 @ 70.00", "sell")
    assert sell is not None
    assert sell.ticker == "UBER.US"
    assert sell.shares == Decimal("1.5")
    assert sell.price == Decimal("70.00")


def test_ticker_in_comment_opens_and_closes_position(tmp_path):
    from pathlib import Path

    from xtb_analyzer.parser import load_csv
    from xtb_analyzer.positions import build_positions

    body = """Account number;11111111
Cash Operations
Date from (UTC);2006-01-01 00:00:00
Date to (UTC);2026-10-08 00:00:00
Type;Instrument;Ticker;Category;Time;Amount;ID;Comment;Product;Position ID
Stock purchase;Uber;;STOCK;2025-11-04 21:52:58;-70,00;1;OPEN BUY UBER.US 1 @ 70.00;My Trades;1
Stock sell;Uber;;STOCK;2025-12-01 10:00:00;80,00;2;CLOSE BUY UBER.US 1 @ 80.00;My Trades;1
Stock purchase;Example;;STOCK;2025-12-02 10:00:00;-21,00;3;OPEN BUY APP.US 2 @ 10.50;My Trades;2
"""
    path = Path(tmp_path) / "USD_11111111_2006-01-01_2026-10-08.csv"
    path.write_text(body, encoding="utf-8")
    account = load_csv(path)
    buys = [tx for tx in account.transactions if tx.type == "buy"]
    sells = [tx for tx in account.transactions if tx.type == "sell"]
    assert all(tx.shares for tx in buys + sells)
    positions = build_positions([account])
    symbols = {symbol: float(pos.shares) for (_, symbol), pos in positions.items()}
    assert "UBER.US" not in symbols
    assert symbols["APP.US"] == 2.0


def test_pln_conversion_counts_amount_as_pln_deposit():
    from xtb_analyzer.flows import extract_deposits
    from xtb_analyzer.models import Account, Transaction
    from datetime import datetime

    account = Account(
        account_id="33333333",
        currency="PLN",
        transactions=[
            Transaction(
                id="1",
                account_id="33333333",
                currency="PLN",
                type="transfer_in",
                timestamp=datetime(2025, 11, 4, 12, 0, 0),
                symbol=None,
                amount=Decimal("1000.00"),
                comment="Currency conversion, EUR to PLN from TA: 1 to: 33333333, Exchange rate:4.25",
            )
        ],
    )
    deposits = extract_deposits([account])
    assert len(deposits) == 1
    assert deposits[0].currency == "PLN"
    assert deposits[0].pln_spent == Decimal("1000.00")

    from xtb_analyzer.cash import build_cash_ledger

    ledger = build_cash_ledger([account])
    assert ledger.deposits_pln == Decimal("1000.00")
