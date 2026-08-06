from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from xtb_analyzer.parser import (
    discover_export_files,
    load_csv,
    parse_decimal,
    parse_timestamp,
)
from xtb_analyzer.flows import extract_deposits

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_timestamp_formats():
    assert parse_timestamp("04.11.2025 21:48:19").year == 2025
    assert parse_timestamp("2025-11-04 21:48:19").day == 4
    assert parse_timestamp(datetime(2025, 11, 4, 21, 48, 19)).minute == 48


def test_parse_decimal_european_and_us():
    assert parse_decimal("1.206,28") == Decimal("1206.28")
    assert parse_decimal("-251,27") == Decimal("-251.27")
    assert parse_decimal("0,24") == Decimal("0.24")
    assert parse_decimal("1,206.28") == Decimal("1206.28")
    assert parse_decimal("1206.28") == Decimal("1206.28")


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


def test_load_v2_xlsx_with_semicolon_lines_in_one_cell():
    """XTB V2 cash ops saved as XLSX often puts each CSV line into a single cell."""
    account = load_csv(FIXTURES / "xtb_v2_euro_single_col.xlsx")
    assert account.currency == "EUR"
    assert account.account_id == "55287715"
    assert len(account.transactions) >= 5
    assert account.transactions[0].type == "transfer_in"


def test_load_xtb_v2_without_currency_in_filename(tmp_path: Path):
    """Currency inferred from conversion comment / ticker suffix when name has no USD."""
    src = (FIXTURES / "xtb_v2_usd_cash_ops.csv").read_text(encoding="utf-8")
    path = tmp_path / "xStation5_cashOperations_2026-08-06_00-00-00.csv"
    path.write_text(src, encoding="utf-8")
    account = load_csv(path)
    assert account.currency == "USD"
    assert account.account_id == "53287226"


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


def test_load_xlsx_under_user_cs_names(tmp_path: Path):
    """Canonical local names: XTB_USD_cs.xlsx / XTB_EURO_cs.xlsx."""
    import shutil

    usd = tmp_path / "XTB_USD_cs.xlsx"
    eur = tmp_path / "XTB_EURO_cs.xlsx"
    shutil.copy(FIXTURES / "legacy_usd_account.xlsx", usd)
    shutil.copy(FIXTURES / "legacy_eur_account.xlsx", eur)

    usd_acc = load_csv(usd)
    eur_acc = load_csv(eur)
    assert usd_acc.currency == "USD"
    assert eur_acc.currency == "EUR"
    assert len(usd_acc.transactions) >= 50
    assert len(eur_acc.transactions) >= 1

    found = discover_export_files(tmp_path)
    assert [p.name for p in found] == ["XTB_EURO_cs.xlsx", "XTB_USD_cs.xlsx"]


def test_discover_prefers_cs_xlsx_over_junk_csv(tmp_path: Path):
    import shutil

    shutil.copy(FIXTURES / "legacy_usd_account.xlsx", tmp_path / "XTB_USD_cs.xlsx")
    shutil.copy(FIXTURES / "legacy_eur_account.xlsx", tmp_path / "XTB_EURO_cs.xlsx")
    # Leftover Closed Positions / broken V2 CSV must not break discovery.
    (tmp_path / "XTB_USD_broken.csv").write_text("Account number;123\n", encoding="utf-8")
    (tmp_path / "xStation5_closedPositions.csv").write_text(
        (FIXTURES / "xtb_v2_closed_positions.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    found = {p.name for p in discover_export_files(tmp_path)}
    assert found == {"XTB_USD_cs.xlsx", "XTB_EURO_cs.xlsx"}


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
    # Header-only files are discoverable; full transaction data is not required to list them.
    (tmp_path / "XTB_USD_account_cs.csv").write_text(
        "ID;Type;Time;Symbol;Comment;Amount\n", encoding="utf-8"
    )
    (tmp_path / "XTB_EURO_cash_ops.csv").write_text(
        "ID;Type;Time;Symbol;Comment;Amount\n", encoding="utf-8"
    )
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    found = discover_export_files(tmp_path)
    names = {path.name for path in found}
    # Canonical *_account_cs / *_cs wins — non-canonical cash_ops alone is fine when no xlsx.
    assert "XTB_USD_account_cs.csv" in names
    assert "notes.txt" not in names


def test_missing_history_marker_no_longer_raises():
    """Regression: modern flat CSV has no 'CASH OPERATION HISTORY' section."""
    account = load_csv(FIXTURES / "modern_usd_cash_ops.csv")
    assert account.transactions


def test_closed_positions_export_raises_clear_error():
    with pytest.raises(ValueError, match="Closed/Open Positions"):
        load_csv(FIXTURES / "xtb_v2_closed_positions.csv")


def test_multi_section_export_uses_cash_operations():
    account = load_csv(FIXTURES / "xtb_v2_multi_section.csv")
    assert account.currency == "USD"
    assert account.account_id == "53287226"
    assert any(tx.type == "buy" for tx in account.transactions)
    assert account.transactions[0].amount == Decimal("1206.28")


def test_discover_skips_closed_positions(tmp_path: Path):
    cash = tmp_path / "xStation5_cashOperations_USD.csv"
    closed = tmp_path / "xStation5_closedPositions_USD.csv"
    cash.write_text((FIXTURES / "xtb_v2_usd_cash_ops.csv").read_text(encoding="utf-8"), encoding="utf-8")
    closed.write_text((FIXTURES / "xtb_v2_closed_positions.csv").read_text(encoding="utf-8"), encoding="utf-8")
    # Also a misleading name that matches XTB_*.csv but is positions-only.
    wrongly_named = tmp_path / "XTB_USD_account.csv"
    wrongly_named.write_text(
        (FIXTURES / "xtb_v2_closed_positions.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    found = {p.name for p in discover_export_files(tmp_path)}
    assert "xStation5_cashOperations_USD.csv" in found
    assert "xStation5_closedPositions_USD.csv" not in found
    assert "XTB_USD_account.csv" not in found


def test_find_project_root_from_notebooks_cwd(tmp_path: Path, monkeypatch):
    from xtb_analyzer.parser import default_data_dir, find_project_root

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    notebooks = tmp_path / "notebooks"
    notebooks.mkdir()
    monkeypatch.chdir(notebooks)
    assert find_project_root() == tmp_path.resolve()
    assert default_data_dir() == (tmp_path / "data").resolve()


def test_find_project_root_from_repo_cwd(tmp_path: Path, monkeypatch):
    from xtb_analyzer.parser import default_data_dir, find_project_root

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    assert find_project_root() == tmp_path.resolve()
    assert default_data_dir() == (tmp_path / "data").resolve()


def test_describe_export_discovery_lists_directory(tmp_path: Path):
    from xtb_analyzer.parser import describe_export_discovery

    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    text = describe_export_discovery(tmp_path)
    assert str(tmp_path.resolve()) in text
    assert "notes.txt" in text


def test_discover_raises_with_reason_for_unreadable_cs_xlsx(tmp_path: Path):
    """Canonical XTB_*_cs.xlsx that cannot be opened must not fail silently."""
    bad = tmp_path / "XTB_USD_cs.xlsx"
    bad.write_bytes(b"not-an-xlsx")
    with pytest.raises(ValueError, match="Nie wszystkie pliki|nie udało się"):
        discover_export_files(tmp_path)


def test_discover_does_not_silently_drop_failed_euro(tmp_path: Path):
    """If USD parses but EURO does not, raise — never return only USD."""
    import shutil

    shutil.copy(FIXTURES / "legacy_usd_account.xlsx", tmp_path / "XTB_USD_cs.xlsx")
    (tmp_path / "XTB_EURO_cs.xlsx").write_bytes(b"not-a-real-xlsx-but-long-enough!!!!")
    with pytest.raises(ValueError, match="XTB_EURO_cs.xlsx"):
        discover_export_files(tmp_path)


def test_discover_returns_both_usd_and_euro(tmp_path: Path):
    import shutil

    shutil.copy(FIXTURES / "legacy_usd_account.xlsx", tmp_path / "XTB_USD_cs.xlsx")
    shutil.copy(FIXTURES / "legacy_eur_account.xlsx", tmp_path / "XTB_EURO_cs.xlsx")
    found = [p.name for p in discover_export_files(tmp_path)]
    assert found == ["XTB_EURO_cs.xlsx", "XTB_USD_cs.xlsx"]


def test_cash_operations_status_reports_openpyxl_hint(tmp_path: Path, monkeypatch):
    from xtb_analyzer import parser as parser_mod

    path = tmp_path / "XTB_USD_cs.xlsx"
    path.write_bytes(b"PK\x03\x04fake")

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ImportError("No module named openpyxl")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    ok, reason = parser_mod._cash_operations_status(path)
    assert ok is False
    assert "openpyxl" in reason.lower()
