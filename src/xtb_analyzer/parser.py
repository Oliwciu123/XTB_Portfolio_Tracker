"""XTB export parser — supports all known Cash Operations formats.

Detected formats
----------------
1. **Legacy CSV / XLSX** — ``CASH OPERATION HISTORY`` section,
   columns ``ID;Type;Time;Comment;Symbol;Amount``.
2. **Modern flat CSV (2024)** — header first,
   ``ID;Type;Time;Symbol;Comment;Amount`` (or Comment before Symbol).
3. **XTB V2 Cash Operations CSV (2025+)** — 4-line metadata preamble, then
   ``Type;Ticker;Instrument;Time;Amount;ID;Comment;Product``.
   Amounts use European decimals (``1.000,00``). Account id is in the preamble.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from xtb_analyzer.comment_parser import parse_trade_comment, transfer_target_currency
from xtb_analyzer.models import Account, Transaction, TransactionType

HISTORY_MARKER = "CASH OPERATION HISTORY"
CASH_OPS_MARKER = "cash operations"
CLOSED_POSITIONS_MARKER = "closed positions"
OPEN_POSITIONS_MARKER = "open positions"
TOTAL_MARKER = "Total"
ACCOUNT_ID_RE = re.compile(r"\b(\d{6,})\b")
POSITIONS_FILENAME_RE = re.compile(
    r"(closed.?positions?|open.?positions?|pozycje.?zamkni)",
    re.IGNORECASE,
)

# Header cell text (lowercased) → canonical field name.
HEADER_ALIASES = {
    "id": "id",
    "type": "type",
    "typ": "type",
    "time": "time",
    "czas": "time",
    "comment": "comment",
    "komentarz": "comment",
    "symbol": "symbol",
    "ticker": "symbol",
    "amount": "amount",
    "kwota": "amount",
    "wartość": "amount",
    "wartosc": "amount",
}


def parse_decimal(value: object) -> Decimal | None:
    """Parse amounts from US (1,234.56) or European (1.234,56 / 0,24) notation."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\xa0", "").replace(" ", "")

    if "," in text and "." in text:
        # European: dot = thousands, comma = decimal  →  1.000,00
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            # US: comma = thousands, dot = decimal  →  1,000.00
            text = text.replace(",", "")
    elif "," in text:
        # Only comma → treat as decimal separator
        text = text.replace(",", ".")

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

    if any(
        token in raw
        for token in (
            "stock purchase",
            "stocks/etf purchase",
            "ações/etf compra",
            "etf purchase",
        )
    ):
        return "buy"
    if any(
        token in raw
        for token in (
            "stock sale",
            "stock sell",
            "stocks/etf sale",
            "ações/etf vende",
            "etf sale",
        )
    ):
        return "sell"
    if (
        raw in {"transfer", "deposit"}
        or "deposit" in raw
        or "cash transfer in" in raw
        or "transfer in" in raw
    ):
        return "transfer_in"
    if "withdrawal" in raw or "cash transfer out" in raw or "transfer out" in raw:
        return "other"
    if "divident" in raw or "dividend" in raw:
        return "dividend"
    if "withholding tax" in raw or raw.endswith("wht"):
        return "withholding_tax"
    if "interest tax" in raw:
        return "interest_tax"
    if "interest" in raw and "tax" not in raw:
        return "interest"
    if "close trade" in raw:
        return "close_trade"
    if "currency conversion" in comment_l:
        return "transfer_in"
    return "other"


def _detect_delimiter(sample: str) -> str:
    semi = sample.count(";")
    comma = sample.count(",")
    # V2 files are semicolon-delimited even though amounts contain commas.
    return ";" if semi >= max(comma // 3, 1) or semi > 0 else ","


def _read_csv_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "cp1250", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    if not text.strip():
        raise ValueError(f"Empty file: {path}")
    delimiter = _detect_delimiter(text[:4000])
    return list(csv.reader(text.splitlines(), delimiter=delimiter))


def _read_xlsx_rows(path: Path) -> list[list[object]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ImportError(
            "Reading .xlsx requires openpyxl. Install with: pip install openpyxl"
        ) from exc

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = None
    for name in workbook.sheetnames:
        lowered = name.strip().lower()
        if HISTORY_MARKER.lower() in lowered or "cash operation" in lowered:
            sheet = workbook[name]
            break
    if sheet is None:
        sheet = workbook[workbook.sheetnames[-1]]

    rows: list[list[object]] = []
    for row in sheet.iter_rows(values_only=True):
        cells = list(row)
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


def _normalize_header_cell(value: str) -> str:
    return value.strip().lower().replace("\ufeff", "")


def _row_column_map(row: list[object]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col_idx in range(len(row)):
        name = _normalize_header_cell(_cell(row, col_idx))
        canonical = HEADER_ALIASES.get(name)
        if canonical and canonical not in mapping:
            mapping[canonical] = col_idx
    return mapping


def _find_history_marker(rows: list[list[object]]) -> int | None:
    for index, row in enumerate(rows):
        first = _normalize_header_cell(_cell(row, 0))
        if HISTORY_MARKER.lower() in first or first == CASH_OPS_MARKER:
            return index
    return None


def _find_section_marker(rows: list[list[object]], *markers: str) -> int | None:
    wanted = {m.lower() for m in markers}
    for index, row in enumerate(rows):
        first = _normalize_header_cell(_cell(row, 0))
        if first in wanted or any(marker in first for marker in wanted):
            return index
    return None


def _looks_like_positions_header(mapping: dict[str, int], row: list[object]) -> bool:
    """Closed/Open Positions headers have Volume/Open Price, not cash Amount+Time."""
    cells = {_normalize_header_cell(_cell(row, i)) for i in range(len(row))}
    position_hints = {
        "volume",
        "open price",
        "close price",
        "open time",
        "close time",
        "profit/loss",
        "purchase value",
        "sale value",
    }
    if cells & position_hints:
        # Cash-ops V2 has Amount+Time; positions use Volume / Open|Close Time.
        if "amount" not in mapping or "time" not in mapping:
            return True
    return False


def _positions_export_error(path: Path, rows: list[list[object]]) -> ValueError:
    preview = []
    for i, row in enumerate(rows[:6]):
        preview.append(" | ".join(_cell(row, j) for j in range(min(6, len(row)))))
    preview_text = "\n".join(f"  row {i}: {line}" for i, line in enumerate(preview)) or "  (empty)"
    return ValueError(
        f"{path.name} looks like an XTB Closed/Open Positions export, "
        "not Cash Operations.\n"
        "This analyzer needs Cash Operations (wpłaty, zakupy, dywidendy, podatki).\n"
        "In xStation: Historia → Cash Operations / Operacje gotówkowe → Export CSV.\n"
        "Put those files in data/ (optionally with USD/EUR in the filename).\n"
        f"First rows of the file were:\n{preview_text}"
    )


def _find_transaction_header(rows: list[list[object]], start: int = 0) -> tuple[int, dict[str, int]]:
    """Find the Cash Operations header row by required columns — ID need not be first."""
    required = {"type", "time", "amount"}
    for index in range(start, len(rows)):
        first = _normalize_header_cell(_cell(rows[index], 0))
        # Stop at a later non-cash section so we don't mis-read positions tables.
        if first in {CLOSED_POSITIONS_MARKER, OPEN_POSITIONS_MARKER}:
            continue
        mapping = _row_column_map(rows[index])
        if _looks_like_positions_header(mapping, rows[index]):
            continue
        if required <= mapping.keys() and ("id" in mapping or "symbol" in mapping or "comment" in mapping):
            if "id" not in mapping:
                mapping["id"] = -1
            return index, mapping

    preview = []
    for row in rows[:8]:
        preview.append(" | ".join(_cell(row, i) for i in range(min(6, len(row)))))
    preview_text = "\n".join(f"  row {i}: {line}" for i, line in enumerate(preview)) or "  (empty)"
    raise ValueError(
        "Could not find a transaction header row.\n"
        "Supported headers include:\n"
        "  • ID;Type;Time;Comment;Symbol;Amount\n"
        "  • ID;Type;Time;Symbol;Comment;Amount\n"
        "  • Type;Ticker;Instrument;Time;Amount;ID;Comment;Product  (XTB 2025+)\n"
        "If you exported Closed Positions, use Cash Operations instead "
        "(xStation → Historia → Cash Operations → Export).\n"
        f"First rows of the file were:\n{preview_text}"
    )


def _currency_hint_from_path(path: Path) -> str | None:
    name = path.name.upper()
    # Prefer explicit currency tokens; IKE/IKZE cash is PLN.
    if re.search(r"(^|[_-])USD([_-]|$)", name) or "USD" in name:
        return "USD"
    if re.search(r"(^|[_-])EUR([_-]|$)", name) or "EURO" in name or "EUR" in name:
        return "EUR"
    if "IKE" in name or "IKZE" in name or "PLN" in name:
        return "PLN"
    return None


def _currency_from_comments(rows: list[list[object]], header_idx: int, columns: dict[str, int]) -> str | None:
    """Infer account currency from conversion comments or ticker suffixes."""
    comment_col = columns.get("comment", -1)
    symbol_col = columns.get("symbol", -1)
    for row in rows[header_idx + 1 : header_idx + 80]:
        comment = _cell(row, comment_col)
        if comment:
            currency = transfer_target_currency(comment)
            if currency:
                return currency
        symbol = _cell(row, symbol_col)
        if symbol and "." in symbol:
            suffix = symbol.rsplit(".", 1)[-1].upper()
            if suffix in {"US", "USD"}:
                return "USD"
            if suffix in {"DE", "FR", "NL", "ES", "IT", "PT", "BE", "AT", "IE", "EUR"}:
                return "EUR"
            if suffix in {"UK", "GB", "LSE"}:
                return "GBP"
            if suffix in {"PL", "WSE"}:
                return "PLN"
    return None


def _account_id_from_preamble(rows: list[list[object]], header_idx: int) -> str | None:
    for row in rows[:header_idx]:
        first = _normalize_header_cell(_cell(row, 0))
        if "account" in first and len(row) > 1:
            value = _cell(row, 1)
            if value.isdigit() and len(value) >= 5:
                return value
        # Sometimes "Account number;12345678" is a single joined feel — scan cells.
        for col_idx in range(len(row)):
            value = _cell(row, col_idx)
            if value.isdigit() and len(value) >= 6:
                return value
    return None


def _account_id_from_rows(rows: list[list[object]], history_start: int) -> str | None:
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


def _account_id_from_comments(comments: list[str]) -> str | None:
    to_re = re.compile(r"\bto[:\s]+(\d{6,})", re.IGNORECASE)
    for comment in comments:
        match = to_re.search(comment)
        if match:
            return match.group(1)
    for comment in comments:
        match = ACCOUNT_ID_RE.search(comment)
        if match:
            return match.group(1)
    return None


def _parse_metadata(
    rows: list[list[object]],
    history_start: int,
    header_idx: int,
    currency_hint: str | None,
    path: Path,
    columns: dict[str, int] | None = None,
) -> dict:
    account_id = _account_id_from_preamble(rows, header_idx)
    if not account_id and history_start:
        account_id = _account_id_from_rows(rows, history_start)

    currency = currency_hint
    holder_name = None
    export_date = None
    balance = equity = margin = free_margin = None

    scan_until = max(history_start or 0, header_idx)
    for row in rows[:scan_until]:
        cells = [_cell(row, i) for i in range(len(row))]
        if "Currency" in cells and currency is None:
            currency_col = cells.index("Currency")
            row_idx = rows.index(row)
            for data_row in rows[row_idx + 1 : scan_until]:
                value = _cell(data_row, currency_col)
                if value.upper() in {"USD", "EUR", "PLN", "GBP"}:
                    currency = value.upper()
                    break
        if "Name and surname" in cells and not holder_name:
            name_idx = cells.index("Name and surname")
            row_idx = rows.index(row)
            if row_idx + 1 < scan_until:
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

    if not currency and columns is not None:
        currency = _currency_from_comments(rows, header_idx, columns)

    if not currency:
        raise ValueError(
            f"Could not determine account currency for {path.name}. "
            "Rename the file to include USD/EUR/PLN (e.g. XTB_USD_cash_ops.csv)."
        )

    return {
        "account_id": account_id,
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
    synthetic_id = 0
    for row in rows[header_idx + 1 :]:
        if not any(_cell(row, i) for i in range(len(row))):
            continue

        # Stop at Total row (first cell or type cell).
        first = _cell(row, 0)
        type_cell = _cell(row, columns["type"])
        if first.startswith(TOTAL_MARKER) or type_cell.startswith(TOTAL_MARKER):
            break

        if columns["id"] >= 0:
            tx_id = _cell(row, columns["id"])
        else:
            tx_id = ""
        if not tx_id:
            synthetic_id += 1
            tx_id = f"auto-{synthetic_id}"

        raw_type = type_cell
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
    """Load one XTB export (legacy / modern 2024 / V2 2025+ / XLSX)."""
    path = Path(path)
    rows = _read_rows(path)
    if not rows:
        raise ValueError(f"No rows found in {path}")

    history_start = _find_history_marker(rows)
    positions_start = _find_section_marker(
        rows, CLOSED_POSITIONS_MARKER, OPEN_POSITIONS_MARKER
    )

    # Prefer the Cash Operations section when a multi-section export has both.
    header_search_from = history_start if history_start is not None else 0
    try:
        header_idx, columns = _find_transaction_header(rows, start=header_search_from)
    except ValueError:
        if positions_start is not None and history_start is None:
            raise _positions_export_error(path, rows) from None
        raise

    meta = _parse_metadata(
        rows,
        history_start if history_start is not None else 0,
        header_idx,
        currency_hint=_currency_hint_from_path(path),
        path=path,
        columns=columns,
    )

    if not meta["account_id"]:
        preview_comments = [
            _cell(row, columns.get("comment", -1))
            for row in rows[header_idx + 1 : header_idx + 40]
        ]
        meta["account_id"] = _account_id_from_comments(preview_comments)
    if not meta["account_id"]:
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


def _is_positions_only_file(path: Path) -> bool:
    """True when the file is Closed/Open Positions without a Cash Operations section."""
    if POSITIONS_FILENAME_RE.search(path.name):
        return True
    try:
        rows = _read_rows(path)
    except Exception:
        return False
    has_positions = _find_section_marker(
        rows, CLOSED_POSITIONS_MARKER, OPEN_POSITIONS_MARKER
    ) is not None
    has_cash = _find_history_marker(rows) is not None
    if has_positions and not has_cash:
        # Flat cash-ops files have no section marker; only skip clear positions exports.
        try:
            _find_transaction_header(rows, start=0)
            return False
        except ValueError:
            return True
    return False


def discover_export_files(data_dir: str | Path) -> list[Path]:
    """Find XTB Cash Operations exports in ``data_dir`` (CSV and XLSX).

    Skips Closed/Open Positions files — those are a different report and cannot
    replace Cash Operations for deposits, dividends and cash flows.
    """
    data_dir = Path(data_dir)
    patterns = (
        "XTB_*_account_cs.csv",
        "XTB_*_account*.csv",
        "XTB_*_cash*.csv",
        "XTB_*.csv",
        "XTB_*.xlsx",
        "*cash*ops*.csv",
        "*cashOperations*.csv",
        "*Cash*Operation*.csv",
        "*CASH*OPERATION*.csv",
        "xStation*_cashOperations*.csv",
        "xStation*_CashOperations*.csv",
        "account_*.xlsx",
        "account_*.csv",
    )
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in data_dir.glob(pattern):
            if not path.is_file() or path.name.startswith("~"):
                continue
            if _is_positions_only_file(path):
                continue
            found[path.name.lower()] = path
    return sorted(found.values(), key=lambda p: p.name.lower())
