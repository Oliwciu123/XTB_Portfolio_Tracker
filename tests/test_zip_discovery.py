"""Zip layout discovery: nested currency-prefixed XTB exports, not the private sample."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from xtb_analyzer.parser import discover_export_files, load_csv
from xtb_analyzer.zip_import import ZipImportError, extract_xtb_zip

FIXTURES = Path(__file__).parent / "fixtures"
USD_NAME = "USD_11111111_2006-01-01_2026-10-08.csv"
EUR_NAME = "EUR_22222222_2006-01-01_2026-08-01.csv"


def _eur_export_text() -> str:
    text = (FIXTURES / "xtb_currency_prefix_cash_ops.csv").read_text(encoding="utf-8")
    return (
        text.replace("11111111", "22222222")
        .replace("PLN to USD", "PLN to EUR")
        .replace("EX.US", "EX.DE")
    )


def _write_nested_pair(root: Path, *, usd_end: str = "2026-10-08") -> None:
    usd_dir = root / "11111111"
    eur_dir = root / "22222222"
    usd_dir.mkdir(parents=True)
    eur_dir.mkdir(parents=True)
    usd_name = f"USD_11111111_2006-01-01_{usd_end}.csv"
    shutil.copy(FIXTURES / "xtb_currency_prefix_cash_ops.csv", usd_dir / usd_name)
    (eur_dir / EUR_NAME).write_text(_eur_export_text(), encoding="utf-8")


def test_prefixed_header_parses_category_and_position_columns():
    account = load_csv(FIXTURES / "xtb_currency_prefix_cash_ops.csv")
    assert account.currency == "USD"
    assert account.account_id == "11111111"
    assert any(tx.type == "buy" for tx in account.transactions)
    assert any(tx.type == "transfer_in" for tx in account.transactions)


def test_discover_nested_currency_prefixed_exports(tmp_path: Path):
    _write_nested_pair(tmp_path)
    (tmp_path / "11111111" / "notes.txt").write_text("ignore", encoding="utf-8")
    closed = tmp_path / "11111111" / "xStation5_closedPositions_USD.csv"
    closed.write_text(
        (FIXTURES / "xtb_v2_closed_positions.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    found = discover_export_files(tmp_path)
    names = {path.name for path in found}
    assert names == {USD_NAME, EUR_NAME}

    accounts = [load_csv(path) for path in found]
    assert {account.currency for account in accounts} == {"USD", "EUR"}


def test_discover_keeps_latest_range_per_account(tmp_path: Path):
    _write_nested_pair(tmp_path, usd_end="2026-10-08")
    older = tmp_path / "11111111" / "USD_11111111_2006-01-01_2026-01-01.csv"
    shutil.copy(FIXTURES / "xtb_currency_prefix_cash_ops.csv", older)

    found = {path.name for path in discover_export_files(tmp_path)}
    assert "USD_11111111_2006-01-01_2026-01-01.csv" not in found
    assert USD_NAME in found
    assert EUR_NAME in found


def test_canonical_names_win_over_nested_currency_files(tmp_path: Path):
    _write_nested_pair(tmp_path)
    shutil.copy(FIXTURES / "legacy_usd_account.xlsx", tmp_path / "XTB_USD_cs.xlsx")
    shutil.copy(FIXTURES / "legacy_eur_account.xlsx", tmp_path / "XTB_EURO_cs.xlsx")

    found = [path.name for path in discover_export_files(tmp_path)]
    assert found == ["XTB_EURO_cs.xlsx", "XTB_USD_cs.xlsx"]


def test_zip_extract_then_discover_both_currencies(tmp_path: Path):
    source = tmp_path / "src"
    _write_nested_pair(source)
    archive = tmp_path / "history.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in source.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(source).as_posix())

    extracted = tmp_path / "extracted"
    extract_xtb_zip(archive, extracted)
    found = {path.name for path in discover_export_files(extracted)}
    assert found == {USD_NAME, EUR_NAME}


def test_zip_of_canonical_filenames(tmp_path: Path):
    archive = tmp_path / "canonical.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(FIXTURES / "legacy_usd_account.xlsx", "XTB_USD_cs.xlsx")
        zf.write(FIXTURES / "legacy_eur_account.xlsx", "XTB_EURO_cs.xlsx")
    extracted = tmp_path / "extracted"
    extract_xtb_zip(archive, extracted)
    found = [path.name for path in discover_export_files(extracted)]
    assert found == ["XTB_EURO_cs.xlsx", "XTB_USD_cs.xlsx"]


def test_multisheet_xlsx_uses_cash_operations_sheet(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    closed = book.active
    closed.title = "Closed Positions"
    closed.append(["Type", "Volume", "Open price"])
    closed.append(["Stock", 1, 10])
    cash = book.create_sheet("Cash Operations")
    for line in (FIXTURES / "xtb_currency_prefix_cash_ops.csv").read_text(encoding="utf-8").splitlines():
        cash.append(line.split(";"))
    opened = book.create_sheet("Open Positions")
    opened.append(["Ticker", "Volume", "Open price"])
    opened.append(["EX.US", 1, 50])

    folder = tmp_path / "11111111"
    folder.mkdir()
    path = folder / "USD_11111111_2006-01-01_2026-10-08.xlsx"
    book.save(path)

    found = discover_export_files(tmp_path)
    assert [item.name for item in found] == [path.name]
    account = load_csv(found[0])
    assert account.currency == "USD"
    assert account.account_id == "11111111"
    assert any(tx.type == "buy" for tx in account.transactions)


def test_discover_keeps_pln_account_with_usd_and_eur(tmp_path: Path):
    _write_nested_pair(tmp_path)
    pln = (FIXTURES / "xtb_currency_prefix_cash_ops.csv").read_text(encoding="utf-8")
    pln = pln.replace("11111111", "33333333").replace("PLN to USD", "EUR to PLN").replace("EX.US", "PKO.PL")
    folder = tmp_path / "33333333"
    folder.mkdir()
    name = "PLN_33333333_2006-01-01_2026-10-08.csv"
    (folder / name).write_text(pln, encoding="utf-8")

    found = discover_export_files(tmp_path)
    assert {path.name for path in found} == {USD_NAME, EUR_NAME, name}
    assert {load_csv(path).currency for path in found} == {"USD", "EUR", "PLN"}


def test_extract_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.csv", "ID;Type;Time;Amount\n")
    dest = tmp_path / "dest"
    with pytest.raises(ZipImportError, match="Niedozwolona ścieżka"):
        extract_xtb_zip(archive, dest)
    assert not (tmp_path / "outside.csv").exists()
