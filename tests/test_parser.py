from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from xtb_analyzer.parser import discover_export_files, load_csv, parse_timestamp
from xtb_analyzer.flows import extract_deposits

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_timestamp_formats():
    assert parse_timestamp("04.11.2025 21:48:19").year == 2025
    assert parse_timestamp("2025-11-04 21:48:19").day == 4
    assert parse_timestamp(datetime(2025, 11, 4, 21, 48, 19)).minute == 48


def test_load_legacy_csv():
    account = load_csv(FIXTURES / "legacy_usd_cash_ops.csv")
    assert account.currency == "USD"
    assert account.account_id == "53287226"
    assert account.equity == Decimal("3491.7")
    assert len(account.transactions) >= 50
    assert account.transactions[0].type == "transfer_in"
    buys = [tx for tx in account.transactions if tx.type == "buy"]
    assert buys[0].symbol == "AMD.US"
    assert buys[0].shares == Decimal("1")


def test_load_modern_flat_csv():
    account = load_csv(FIXTURES / "modern_usd_cash_ops.csv")
    assert account.currency == "USD"
    assert account.account_id == "53287226"  # recovered from conversion comment
    assert len(account.transactions) >= 50
    assert account.transactions[0].type == "transfer_in"
    assert account.transactions[0].amount == Decimal("1206.28")
    buys = [tx for tx in account.transactions if tx.type == "buy"]
    assert buys[0].symbol == "AMD.US"
    assert buys[0].shares == Decimal("1")
    assert buys[0].price == Decimal("251.27")


def test_load_modern_accepts_stocks_etf_type_labels():
    account = load_csv(FIXTURES / "modern_usd_cash_ops.csv")
    types = {tx.type for tx in account.transactions}
    assert "buy" in types
    assert "transfer_in" in types


def test_load_xlsx_account_report():
    account = load_csv(FIXTURES / "legacy_usd_account.xlsx")
    assert account.currency == "USD"
    assert account.account_id == "53287226"
    assert len(account.transactions) >= 50


def test_modern_and_legacy_parse_same_trade_count():
    legacy = load_csv(FIXTURES / "legacy_usd_cash_ops.csv")
    modern = load_csv(FIXTURES / "modern_usd_cash_ops.csv")
    assert len(legacy.transactions) == len(modern.transactions)


def test_deposits_extracted_from_modern_export():
    account = load_csv(FIXTURES / "modern_usd_cash_ops.csv")
    deposits = extract_deposits([account])
    assert len(deposits) >= 1
    assert deposits[0].currency == "USD"
    assert float(deposits[0].pln_spent) > 0


def test_discover_export_files(tmp_path: Path):
    (tmp_path / "XTB_USD_account_cs.csv").write_text("ID;Type;Time;Symbol;Comment;Amount\n", encoding="utf-8")
    (tmp_path / "XTB_EURO_cash_ops.csv").write_text("ID;Type;Time;Symbol;Comment;Amount\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    found = discover_export_files(tmp_path)
    names = {path.name for path in found}
    assert "XTB_USD_account_cs.csv" in names
    assert "XTB_EURO_cash_ops.csv" in names
    assert "notes.txt" not in names


def test_missing_history_marker_no_longer_raises():
    """Regression: modern flat CSV has no 'CASH OPERATION HISTORY' section."""
    account = load_csv(FIXTURES / "modern_usd_cash_ops.csv")
    assert account.transactions
