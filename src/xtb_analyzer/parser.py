"""XTB export parser — supports legacy multi-section CSV, modern flat Cash
Operations CSV (2024+), and full account XLSX reports.

Detected formats
----------------
1. **Legacy CSV** — account metadata + ``CASH OPERATION HISTORY`` section,
   columns ``ID;Type;Time;Comment;Symbol;Amount``.
2. **Modern flat CSV** — header on the first data row,
   columns ``ID;Type;Time;Symbol;Comment;Amount`` (Symbol before Comment),
   type labels like ``Stocks/ETF purchase``.
3. **XLSX account report** — workbook with a ``CASH OPERATION HISTORY`` sheet
   (same content as legacy CSV). Drop the ``.xlsx`` into ``data/`` directly.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from xtb_analyzer.comment_parser import parse_trade_comment
from xtb_analyzer.models import Account, Transaction, TransactionType

HISTORY_MARKER = "CASH OPERATION HISTORY"
TOTAL_MARKER = "Total"
ACCOUNT_ID_RE = re.compile(r"\b(\d{6,})\b")

# Header aliases → canonical field names.
HEADER_ALIASES = {
    "id": "id",
    "type": "type",
    "time": "time",
    "comment": "comment",
    "symbol": "symbol",
    "amount": "amount",
}


def parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value

    text = str(value).strip()
    if not text:
        raise ValueError("Empty timestamp")

    # ISO-ish with optional fractional seconds
    iso = text.replace("Z", "")
    for candidate in (iso, iso.split(".")[0].replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass

    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {text!r}")


def _normalize_type(raw_type: str, comment: str = "") -> TransactionType:
    raw = (raw_type or "").strip().lower()
    comment_l = (comment or "").lower()

    # Buys
    if any(token in raw for token in ("stock purchase", "stocks/etf purchase", "ações/etf compra", "etf purchase")):
        return "buy"
    # Sells
    if any(token in raw for token in ("stock sale", "stocks/etf sale", "ações/etf vende", "etf sale")):
        return "sell"
    # Cash in
    if raw in {"transfer", "deposit"} or "deposit" in raw:
        return "transfer_in"
    if "withdrawal" in raw:
        return "other"
    if "divident" in raw or raw == "dividend" or raw.startswith("dividend"):
        # Negative "dividends" in some exports are corrections / fees
        return "dividend"
    if "withholding tax" in raw or raw.endswith("wht"):
        return "withholding_tax"
    if "interest tax" in raw:
        return "interest_tax"
    if "interest" in raw and "tax" not in raw:
        return "interest"
    if "close trade" in raw:
        return "close_trade"
    # Currency conversion comments sometimes sit on generic "transfer" already handled.
    if "currency conversion" in comment_l:
        return "transfer_in"
    return "other"


def _detect_delimiter(sample: str) -> str:
    semi = sample.count(";")
    comma = sample.count(",")
    return ";" if semi >= comma else ","


def _read_csv_rows(path: Path) -> list[list[str]]:
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        raise ValueError(f"Empty file: {path}")
    delimiter = _detect_delimiter(raw[:4000])
    return list(csv.reader(raw.splitlines(), delimiter=delimiter))


def _read_xlsx_rows(path: Path) -> list[list[str]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ImportError(
            "Reading .xlsx requires openpyxl. Install with: pip install openpyxl"
        ) from exc

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = None
    for name in workbook.sheetnames:
        if HISTORY_MARKER.strip().lower() in name.strip().lower():
            sheet = workbook[name]
            break
    if sheet is None:
        # Fall back to the last sheet (XTB usually puts cash ops last)
        sheet = workbook[workbook.sheetnames[-1]]

    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        cells = list(row)
        # XTB leaves column A unused — drop only that leading blank, keep alignment.
        if cells and cells[0] is None:
            cells = cells[1:]
        rows.append(["" if c is None else c for c in cells])
    workbook.close()
    return rows


def _read_rows(path: Path) -> list[list[object]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx_rows(path)
    if suffix in {".csv", ".txt"}:
        return _read_csv_rows(path)
    raise ValueError(f"Unsupported file type {suffix!r}: {path}")


def _cell(row: list[object], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


def _find_history_marker(rows: list[list[object]]) -> int | None:
    for index, row in enumerate(rows):
        if row and HISTORY_MARKER.lower() in _cell(row, 0).lower():
            return index
    return None


def _find_transaction_header(rows: list[list[object]], start: int = 0) -> tuple[int, dict[str, int]]:
    for index in range(start, len(rows)):
        cells = [_cell(rows[index], i).lower() for i in range(len(rows[index]))]
        if not cells or cells[0] != "id":
            continue
        mapping: dict[str, int] = {}
        for col_idx, name in enumerate(cells):
            canonical = HEADER_ALIASES.get(name)
            if canonical and canonical not in mapping:
                mapping[canonical] = col_idx
        if {"id", "type", "time", "amount"} <= mapping.keys():
            return index, mapping
    raise ValueError(
        "Could not find a transaction header row (expected columns like "
        "ID;Type;Time;Comment;Symbol;Amount or ID;Type;Time;Symbol;Comment;Amount)."
    )


def _currency_hint_from_path(path: Path) -> str | None:
    name = path.name.upper()
    if "USD" in name:
        return "USD"
    if "EURO" in name or "EUR" in name:
        return "EUR"
    if "PLN" in name:
        return "PLN"
    return None


def _account_id_from_rows(rows: list[list[object]], history_start: int) -> str | None:
    account_col = None
    for row in rows[: max(history_start, 0)]:
        cells = [_cell(row, i) for i in range(len(row))]
        if "Account" in cells:
            account_col = cells.index("Account")
            row_idx = rows.index(row)
            for data_row in rows[row_idx + 1 : max(history_start, row_idx + 5)]:
                value = _cell(data_row, account_col)
                if value.isdigit() and len(value) >= 6:
                    return value
    return None


def _account_id_from_comments(transactions_preview: list[str]) -> str | None:
    # Prefer "to: <id>" from currency conversion / transfer comments.
    to_re = re.compile(r"\bto[:\s]+(\d{6,})", re.IGNORECASE)
    for comment in transactions_preview:
        match = to_re.search(comment)
        if match:
            return match.group(1)
    for comment in transactions_preview:
        match = ACCOUNT_ID_RE.search(comment)
        if match:
            return match.group(1)
    return None


def _parse_metadata(
    rows: list[list[object]],
    history_start: int,
    currency_hint: str | None,
    path: Path,
) -> dict:
    account_id = _account_id_from_rows(rows, history_start) if history_start > 0 else None
    currency = currency_hint
    holder_name = None
    export_date = None
    balance = equity = margin = free_margin = None
    currency_col = None

    for row in rows[: max(history_start, 0)]:
        cells = [_cell(row, i) for i in range(len(row))]
        if "Currency" in cells and currency is None:
            currency_col = cells.index("Currency")
            row_idx = rows.index(row)
            for data_row in rows[row_idx + 1 : history_start]:
                value = _cell(data_row, currency_col)
                if value.upper() in {"USD", "EUR", "PLN"}:
                    currency = value.upper()
                    break
        if "Name and surname" in cells and not holder_name:
            name_idx = cells.index("Name and surname")
            row_idx = rows.index(row)
            if row_idx + 1 < history_start:
                holder_name = _cell(rows[row_idx + 1], name_idx) or None
        if "Balance" in cells and "Equity" in cells:
            try:
                balance_idx = cells.index("Balance")
                row_idx = rows.index(row)
                if row_idx + 1 < len(rows):
                    values = rows[row_idx + 1]
                    balance = parse_decimal(_cell(values, balance_idx))
                    equity = parse_decimal(_cell(values, balance_idx + 1))
                    margin = parse_decimal(_cell(values, balance_idx + 2))
                    free_margin = parse_decimal(_cell(values, balance_idx + 3))
            except (ValueError, IndexError):
                pass
        for cell in cells:
            if not cell:
                continue
            try:
                export_date = parse_timestamp(cell)
            except ValueError:
                pass

    if not currency:
        currency = currency_hint
    if not currency:
        raise ValueError(
            f"Could not determine account currency for {path.name}. "
            "Rename the file to include USD/EUR/PLN (e.g. XTB_USD_cash_ops.csv)."
        )

    return {
        "account_id": account_id,  # may still be None — filled later
        "currency": currency.upper(),
        "holder_name": holder_name,
        "balance": balance,
        "equity": equity,
        "margin": margin,
        "free_margin": free_margin,
        "export_date": export_date,
    }


def _parse_transactions(
    rows: list[list[object]],
    header_idx: int,
    columns: dict[str, int],
    account_id: str,
    currency: str,
) -> list[Transaction]:
    transactions: list[Transaction] = []
    for row in rows[header_idx + 1 :]:
        tx_id = _cell(row, columns["id"])
        if not tx_id:
            continue
        if tx_id.startswith(TOTAL_MARKER):
            break

        raw_type = _cell(row, columns["type"])
        time_raw = row[columns["time"]] if columns["time"] < len(row) else ""
        comment = _cell(row, columns.get("comment", -1))
        symbol = _cell(row, columns.get("symbol", -1)) or None
        amount = parse_decimal(row[columns["amount"]]) if columns["amount"] < len(row) else None
        if amount is None:
            continue

        tx_type = _normalize_type(raw_type, comment)
        try:
            timestamp = parse_timestamp(time_raw)
        except ValueError:
            continue

        shares = price = realized_pnl = None
        if tx_type == "buy":
            trade = parse_trade_comment(comment, "buy")
            if trade:
                shares, price = trade.shares, trade.price
        elif tx_type == "sell":
            trade = parse_trade_comment(comment, "sell")
            if trade:
                shares, price = trade.shares, trade.price
        elif tx_type == "close_trade":
            realized_pnl = amount

        transactions.append(
            Transaction(
                id=tx_id,
                account_id=account_id,
                currency=currency,
                type=tx_type,
                timestamp=timestamp,
                symbol=symbol,
                amount=amount,
                shares=shares,
                price=price,
                comment=comment,
                realized_pnl=realized_pnl,
            )
        )
    return transactions


def load_csv(path: str | Path) -> Account:
    """Load one XTB export (legacy CSV, modern flat CSV, or XLSX)."""
    path = Path(path)
    rows = _read_rows(path)
    if not rows:
        raise ValueError(f"No rows found in {path}")

    history_start = _find_history_marker(rows)
    header_search_from = history_start if history_start is not None else 0
    header_idx, columns = _find_transaction_header(rows, start=header_search_from)

    meta = _parse_metadata(
        rows,
        history_start if history_start is not None else 0,
        currency_hint=_currency_hint_from_path(path),
        path=path,
    )

    # Peek comments to recover account id when metadata is absent (modern flat CSV).
    if not meta["account_id"]:
        preview_comments = [
            _cell(row, columns.get("comment", -1))
            for row in rows[header_idx + 1 : header_idx + 40]
        ]
        meta["account_id"] = _account_id_from_comments(preview_comments)
    if not meta["account_id"]:
        # Last resort: stable id derived from filename + currency.
        meta["account_id"] = f"{path.stem}-{meta['currency']}"

    transactions = _parse_transactions(
        rows,
        header_idx,
        columns,
        meta["account_id"],
        meta["currency"],
    )
    if not transactions:
        raise ValueError(f"No transactions parsed from {path.name}")

    return Account(transactions=transactions, **meta)


def load_accounts(paths: list[str | Path]) -> list[Account]:
    return [load_csv(path) for path in paths]


def discover_export_files(data_dir: str | Path) -> list[Path]:
    """Find XTB exports in ``data_dir`` (CSV and XLSX), newest names first."""
    data_dir = Path(data_dir)
    patterns = (
        "XTB_*_account_cs.csv",
        "XTB_*_account*.csv",
        "XTB_*_cash*.csv",
        "XTB_*.csv",
        "XTB_*.xlsx",
        "*cash*ops*.csv",
        "*CASH*OPERATION*.csv",
    )
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in data_dir.glob(pattern):
            if path.is_file():
                found[path.name.lower()] = path
    # Prefer one file per currency hint when duplicates exist.
    return sorted(found.values(), key=lambda p: p.name.lower())
