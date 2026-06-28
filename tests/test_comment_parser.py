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
