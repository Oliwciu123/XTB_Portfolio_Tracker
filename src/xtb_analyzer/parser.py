from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from xtb_analyzer.comment_parser import parse_trade_comment
from xtb_analyzer.models import Account, Transaction, TransactionType

HISTORY_MARKER = "CASH OPERATION HISTORY"
TOTAL_MARKER = "Total"


def parse_decimal(value: str) -> Decimal | None:
    value = (value or "").strip()
    if not value:
        return None
    value = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def parse_timestamp(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value!r}")


def _normalize_type(raw_type: str, comment: str) -> TransactionType:
    raw = raw_type.strip().lower()
    if raw == "stock purchase":
        return "buy"
    if raw == "stock sale":
        return "sell"
    if raw == "transfer":
        return "transfer_in"
    if raw in {"divident", "dividend"}:
        return "dividend"
    if raw == "withholding tax":
        return "withholding_tax"
    if raw == "free-funds interest":
        return "interest"
    if raw == "free-funds interest tax":
        return "interest_tax"
    if raw == "close trade":
        return "close_trade"
    return "other"


def _read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter=";"))


def _find_history_start(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        if row and HISTORY_MARKER in row[0]:
            return index
    raise ValueError(f"Could not find {HISTORY_MARKER!r} section in file")


def _parse_header(rows: list[list[str]], history_start: int, currency_hint: str | None = None) -> dict:
    account_id = None
    currency = currency_hint
    holder_name = None
    export_date = None
    balance = equity = margin = free_margin = None

    account_col = currency_col = None
    for row in rows[:history_start]:
        cells = [cell.strip() for cell in row]
        if "Account" in cells:
            account_col = cells.index("Account")
            if "Currency" in cells:
                currency_col = cells.index("Currency")
        if "Name and surname" in cells and not holder_name:
            try:
                name_idx = cells.index("Name and surname")
                next_row_idx = rows.index(row) + 1
                if next_row_idx < history_start:
                    data_cells = [cell.strip() for cell in rows[next_row_idx]]
                    if name_idx < len(data_cells) and data_cells[name_idx]:
                        holder_name = data_cells[name_idx]
            except (ValueError, IndexError):
                pass
        if account_col is not None:
            row_idx = rows.index(row)
            for data_row in rows[row_idx + 1 : history_start]:
                data_cells = [cell.strip() for cell in data_row]
                if account_col < len(data_cells) and data_cells[account_col].isdigit():
                    account_id = data_cells[account_col]
                    if currency_col is not None and currency_col < len(data_cells) and data_cells[currency_col]:
                        currency = data_cells[currency_col]
                    break
        if "Balance" in cells and "Equity" in cells:
            try:
                balance_idx = cells.index("Balance")
                next_row_idx = rows.index(row) + 1
                if next_row_idx < history_start:
                    values = [cell.strip() for cell in rows[next_row_idx]]
                    balance = parse_decimal(values[balance_idx])
                    equity = parse_decimal(values[balance_idx + 1])
                    margin = parse_decimal(values[balance_idx + 2])
                    free_margin = parse_decimal(values[balance_idx + 3])
            except (ValueError, IndexError):
                pass
        for cell in cells:
            if cell and "." in cell and any(part.isdigit() for part in cell.split(".")):
                try:
                    export_date = parse_timestamp(cell)
                except ValueError:
                    pass

    if not account_id:
        raise ValueError("Could not parse account metadata from XTB export")
    if not currency:
        raise ValueError("Could not determine account currency; rename file to include USD/EUR or pass currency_hint")

    return {
        "account_id": account_id,
        "currency": currency,
        "holder_name": holder_name,
        "balance": balance,
        "equity": equity,
        "margin": margin,
        "free_margin": free_margin,
        "export_date": export_date,
    }


def _parse_transactions(rows: list[list[str]], history_start: int, account_id: str, currency: str) -> list[Transaction]:
    header_idx = None
    for index in range(history_start, len(rows)):
        row = rows[index]
        if row and row[0].strip() == "ID":
            header_idx = index
            break
    if header_idx is None:
        raise ValueError("Could not find transaction header row")

    transactions: list[Transaction] = []
    for row in rows[header_idx + 1 :]:
        if not row or not row[0].strip():
            continue
        if row[0].strip().startswith(TOTAL_MARKER):
            break

        tx_id = row[0].strip()
        raw_type = row[1].strip() if len(row) > 1 else ""
        time_raw = row[2].strip() if len(row) > 2 else ""
        comment = row[3].strip() if len(row) > 3 else ""
        symbol = row[4].strip() if len(row) > 4 else ""
        amount = parse_decimal(row[5]) if len(row) > 5 else None

        if not tx_id or amount is None:
            continue

        tx_type = _normalize_type(raw_type, comment)
        timestamp = parse_timestamp(time_raw)
        symbol_value = symbol or None

        shares = price = realized_pnl = None
        if tx_type == "buy":
            trade = parse_trade_comment(comment, "buy")
            if trade:
                shares = trade.shares
                price = trade.price
        elif tx_type == "sell":
            trade = parse_trade_comment(comment, "sell")
            if trade:
                shares = trade.shares
                price = trade.price
        elif tx_type == "close_trade":
            realized_pnl = amount

        transactions.append(
            Transaction(
                id=tx_id,
                account_id=account_id,
                currency=currency,
                type=tx_type,
                timestamp=timestamp,
                symbol=symbol_value,
                amount=amount,
                shares=shares,
                price=price,
                comment=comment,
                realized_pnl=realized_pnl,
            )
        )

    return transactions


def _currency_hint_from_path(path: Path) -> str | None:
    name = path.name.upper()
    if "USD" in name:
        return "USD"
    if "EURO" in name or "_EUR" in name:
        return "EUR"
    if "PLN" in name:
        return "PLN"
    return None


def load_csv(path: str | Path) -> Account:
    path = Path(path)
    rows = _read_rows(path)
    history_start = _find_history_start(rows)
    header = _parse_header(rows, history_start, currency_hint=_currency_hint_from_path(path))
    transactions = _parse_transactions(
        rows,
        history_start,
        header["account_id"],
        header["currency"],
    )
    return Account(transactions=transactions, **header)


def load_accounts(paths: list[str | Path]) -> list[Account]:
    return [load_csv(path) for path in paths]
