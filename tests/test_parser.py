from datetime import datetime
from decimal import Decimal

import pytest

from xtb_analyzer.comment_parser import (
    is_transfer_in,
    parse_exchange_rate,
    parse_trade_comment,
    transfer_target_currency,
)
from xtb_analyzer.parser import load_csv


DATA_DIR = "data"


def test_open_buy_fractional():
    trade = parse_trade_comment("OPEN BUY 1/1.5 @ 251.27", "buy")
    assert trade is not None
    assert trade.shares == Decimal("1")
    assert trade.price == Decimal("251.27")
    assert trade.fill == Decimal("1")
    assert trade.total == Decimal("1.5")


def test_open_buy_simple():
    trade = parse_trade_comment("OPEN BUY 4 @ 94.92", "buy")
    assert trade is not None
    assert trade.shares == Decimal("4")
    assert trade.price == Decimal("94.92")


def test_close_buy():
    trade = parse_trade_comment("CLOSE BUY 0.4133/2 @ 456.97", "sell")
    assert trade is not None
    assert trade.shares == Decimal("0.4133")
    assert trade.price == Decimal("456.97")


def test_transfer_comment():
    comment = (
        "Currency conversion, PLN to USD from TA: 52970582 to: 53287226, "
        "Exchange rate:0.268063"
    )
    assert is_transfer_in(comment)
    assert transfer_target_currency(comment) == "USD"
    assert parse_exchange_rate(comment) == Decimal("0.268063")


def test_load_usd_account():
    account = load_csv(f"{DATA_DIR}/XTB_USD_account_cs.csv")
    assert account.account_id == "53287226"
    assert account.currency == "USD"
    assert account.equity == Decimal("3491.7")
    assert len(account.transactions) == 104
    assert account.transactions[0].type == "transfer_in"
    assert account.transactions[1].type == "buy"
    assert account.transactions[1].symbol == "AMD.US"
    assert account.transactions[1].shares == Decimal("1")


def test_load_eur_account():
    account = load_csv(f"{DATA_DIR}/XTB_EURO_account_cs.csv")
    assert account.account_id == "55287715"
    assert account.currency == "EUR"
    assert account.holder_name == "OLIWIER MAREK ARENT"
    assert len(account.transactions) == 3
    assert account.transactions[-1].symbol == "IFX.DE"


def test_transaction_timestamps_parseable():
    account = load_csv(f"{DATA_DIR}/XTB_USD_account_cs.csv")
    timestamps = [tx.timestamp for tx in account.transactions]
    assert len(timestamps) == len(account.transactions)
    assert isinstance(timestamps[0], datetime)
    assert sorted(timestamps)[0] == min(timestamps)
