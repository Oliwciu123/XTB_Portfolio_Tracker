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


def _sheet_rows(sheet) -> list[list[object]]:
    rows: list[list[object]] = []
    for row in sheet.iter_rows(values_only=True):
        cells = ["" if c is None else c for c in row]
        # XTB account XLSX pads a blank leading column — strip all leading empties.
        while cells and cells[0] == "":
            cells = cells[1:]
        rows.append(cells)
    return _explode_delimited_rows(rows)


def _explode_delimited_rows(rows: list[list[object]]) -> list[list[object]]:
    """Split rows that store an entire CSV line in one cell (common XTB V2→XLSX export)."""
    nonempty = [row for row in rows if any(str(c).strip() for c in row)]
    if not nonempty:
        return rows

    single_delim = 0
    for row in nonempty[:40]:
        if len(row) == 1 and isinstance(row[0], str) and row[0].count(";") >= 2:
            single_delim += 1
        elif (
            len(row) >= 1
            and isinstance(row[0], str)
            and row[0].count(";") >= 2
            and sum(1 for c in row[1:] if str(c).strip()) == 0
        ):
            single_delim += 1

    if single_delim < max(3, len(nonempty[:40]) // 2):
        return rows

    exploded: list[list[object]] = []
    for row in rows:
        if not row:
            exploded.append(row)
            continue
        first = row[0]
        if isinstance(first, str) and first.count(";") >= 2:
            # Keep only the delimited first cell (rest are empty padding).
            exploded.append([part.strip() for part in first.split(";")])
        else:
            exploded.append(row)
    return exploded


def _sheet_has_cash_ops(rows: list[list[object]]) -> bool:
    if _find_history_marker(rows) is not None:
        return True
    try:
        _find_transaction_header(rows, start=0)
        return True
    except ValueError:
        return False


def _is_cash_ops_sheet_name(name: str) -> bool:
    lowered = name.strip().lower()
    return any(
        token in lowered
        for token in (
            "cash operation",
            "cash operations",
            "operacji gotówk",
            "operacje gotówk",
            "historia operacji",
        )
    )


def _read_xlsx_rows(path: Path) -> list[list[object]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ImportError(
            "Brak pakietu openpyxl w tym interpreterze Pythona.\n"
            "W terminalu (ten sam Python co kernel notebooka) uruchom:\n"
            "  python -m pip install openpyxl\n"
            "Potem Restart Kernel i odpal komórki od nowa."
        ) from exc

    size = path.stat().st_size if path.exists() else 0
    if size < 64:
        raise ValueError(
            f"{path.name} ma tylko {size} bajtów — plik jest pusty albo jeszcze "
            "niezsynchronizowany z OneDrive. W Eksploratorze: PPM → Zawsze zachowuj na tym urządzeniu, "
            "poczekaj aż ikona chmury zniknie, potem spróbuj ponownie."
        )

    last_error: Exception | None = None
    workbook = None
    for read_only in (True, False):
        try:
            workbook = openpyxl.load_workbook(path, data_only=True, read_only=read_only)
            break
        except Exception as exc:  # noqa: BLE001 — surface later with context
            last_error = exc
            workbook = None

    if workbook is None:
        hint = ""
        err_text = str(last_error or "")
        if "zip" in err_text.lower() or "not a zip" in err_text.lower():
            hint = (
                " Plik nie jest prawidłowym XLSX (częsty efekt OneDrive „tylko online” "
                "albo uszkodzonego pobrania). Pobierz lokalnie / wyeksportuj ponownie z xStation."
            )
        raise ValueError(
            f"Nie można otworzyć {path.name} przez openpyxl "
            f"({type(last_error).__name__}: {last_error}).{hint}"
        ) from last_error

    try:
        # 1) Prefer sheet by name.
        preferred = None
        for name in workbook.sheetnames:
            if _is_cash_ops_sheet_name(name):
                preferred = workbook[name]
                break

        candidates: list = []
        if preferred is not None:
            candidates.append(preferred)
        # 2) Then every sheet (cash ops is usually last in XTB exports).
        for name in workbook.sheetnames:
            sheet = workbook[name]
            if sheet is not preferred:
                candidates.append(sheet)

        best_rows: list[list[object]] | None = None
        for sheet in candidates:
            rows = _sheet_rows(sheet)
            if _sheet_has_cash_ops(rows):
                return rows
            if best_rows is None:
                best_rows = rows

        if best_rows is None:
            raise ValueError(f"{path.name}: workbook has no sheets")
        return best_rows
    finally:
        workbook.close()


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


def find_project_root(start: Path | None = None) -> Path:
    """Locate the repo root whether the process cwd is project root or ``notebooks/``."""
    start = (start or Path.cwd()).resolve()
    for base in (start, *start.parents):
        if (base / "pyproject.toml").is_file():
            return base
        if (base / "src" / "xtb_analyzer").is_dir():
            return base
    if start.name.lower() == "notebooks":
        return start.parent
    return start


def default_data_dir(start: Path | None = None) -> Path:
    """``<project>/data`` — stable across notebook and CLI working directories."""
    return find_project_root(start) / "data"


def describe_export_discovery(data_dir: str | Path) -> str:
    """Human-readable diagnostics when no exports are found."""
    data_dir = Path(data_dir)
    resolved = data_dir.resolve()
    lines = [
        f"Szukano w: {resolved}",
        f"Katalog istnieje: {data_dir.is_dir()}",
    ]
    try:
        import openpyxl  # noqa: F401

        openpyxl_status = "OK"
    except ImportError:
        openpyxl_status = (
            "BRAK — uruchom w tym samym Pythonie co kernel: python -m pip install openpyxl"
        )
    lines.append(f"openpyxl: {openpyxl_status}")

    if data_dir.is_dir():
        entries = sorted(
            (p for p in data_dir.iterdir() if not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
        if entries:
            lines.append("Zawartość katalogu:")
            for path in entries[:40]:
                if path.is_file():
                    lines.append(f"  • {path.name} ({path.stat().st_size} bajtów)")
                else:
                    lines.append(f"  • {path.name}/")
            if len(entries) > 40:
                lines.append(f"  … i {len(entries) - 40} więcej")
        else:
            lines.append("Katalog data/ jest pusty.")

        xtb_files = sorted(data_dir.glob("XTB_*"), key=lambda p: p.name.lower())
        if xtb_files:
            lines.append("Diagnostyka plików XTB_*:")
            for path in xtb_files:
                if not path.is_file():
                    continue
                ok, reason = _cash_operations_status(path)
                lines.append(f"  • {path.name}: {'OK' if ok else reason}")
    else:
        lines.append(
            "Upewnij się, że pliki leżą w katalogu projektu: "
            f"{find_project_root() / 'data'}"
        )
    lines.append(
        "Oczekiwane nazwy: XTB_USD_cs.xlsx, XTB_EURO_cs.xlsx "
        "(xStation → Historia → Eksportuj jako XLSX)."
    )
    return "\n".join(lines)


def load_accounts(paths: list[str | Path]) -> list[Account]:
    accounts: list[Account] = []
    for path in paths:
        path = Path(path)
        try:
            accounts.append(load_csv(path))
        except Exception as exc:
            raise ValueError(f"Failed to load {path.name}: {exc}") from exc
    return accounts


def _cash_operations_status(path: Path) -> tuple[bool, str]:
    """Return ``(ok, detail)`` — detail is empty on success, else the failure reason."""
    try:
        if _is_positions_only_file(path):
            return False, "Closed/Open Positions (pominięty)"
        rows = _read_rows(path)
        if not rows:
            return False, "plik bez wierszy"
        history_start = _find_history_marker(rows)
        start = history_start if history_start is not None else 0
        _find_transaction_header(rows, start=start)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _has_cash_operations_content(path: Path) -> bool:
    """True when the file contains a parseable Cash Operations table."""
    ok, _ = _cash_operations_status(path)
    return ok


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
        try:
            _find_transaction_header(rows, start=0)
            return False
        except ValueError:
            return True
    return False


def _looks_like_currency_cs_export(path: Path) -> bool:
    """True for names like XTB_USD_cs.xlsx / XTB_EURO_cs.xlsx / xtb-eur-cs.XLSX."""
    stem = path.stem.lower().replace("-", "_")
    if not stem.startswith("xtb"):
        return False
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xls", ".csv"}:
        return False
    has_cs = stem.endswith("_cs") or "_cs_" in stem or stem.endswith("cs")
    has_currency = any(token in stem for token in ("usd", "euro", "eur", "pln"))
    return has_cs and has_currency


def _is_canonical_account_report(path: Path) -> bool:
    """Match preferred names: XTB_USD_cs.xlsx, XTB_EURO_cs.xlsx, XTB_*_account*.xlsx."""
    name = path.name
    if re.match(r"(?i)XTB_.+_cs\.(xlsx|xlsm|xls|csv)$", name):
        return True
    if re.match(r"(?i)XTB_.+cs\.(xlsx|xlsm|xls|csv)$", name) and re.search(
        r"(?i)(usd|euro|eur|pln)", name
    ):
        return True
    if re.match(r"(?i)XTB_.+_account.*\.(xlsx|xlsm|xls|csv)$", name):
        return True
    return _looks_like_currency_cs_export(path)


def discover_export_files(data_dir: str | Path) -> list[Path]:
    """Find XTB Cash Operations exports in ``data_dir`` (CSV and XLSX).

    Preferred (canonical) names — used exclusively when present and parseable:
      ``XTB_USD_cs.xlsx``, ``XTB_EURO_cs.xlsx`` / ``XTB_EUR_cs.xlsx``.

    If any of those canonical files is present but unreadable, raise ``ValueError``
    listing every failure. Never silently keep only the subset that parsed.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return []

    patterns = (
        "XTB_*_cs.xlsx",
        "XTB_*_cs.xlsm",
        "XTB_*_cs.xls",
        "XTB_*_cs.csv",
        "XTB_*cs.xlsx",
        "XTB_*_account*.xlsx",
        "XTB_*_account*.csv",
        "XTB_*_cash*.csv",
        "XTB_*.xlsx",
        "XTB_*.csv",
        "*cash*ops*.csv",
        "*cashOperations*.csv",
        "*Cash*Operation*.csv",
        "*CASH*OPERATION*.csv",
        "xStation*_cashOperations*.csv",
        "xStation*_CashOperations*.csv",
        "account_*.xlsx",
        "account_*.csv",
    )

    candidates: dict[str, Path] = {}
    for pattern in patterns:
        for path in data_dir.glob(pattern):
            if not path.is_file() or path.name.startswith("~"):
                continue
            if POSITIONS_FILENAME_RE.search(path.name):
                continue
            candidates[path.name.lower()] = path

    # Directory scan catches odd casing / unicode underscores missed by glob.
    for path in data_dir.iterdir():
        if not path.is_file() or path.name.startswith("~"):
            continue
        if POSITIONS_FILENAME_RE.search(path.name):
            continue
        if _is_canonical_account_report(path) or _looks_like_currency_cs_export(path):
            candidates[path.name.lower()] = path

    statuses = {path: _cash_operations_status(path) for path in candidates.values()}
    named_canonical = sorted(
        (
            p
            for p in candidates.values()
            if (_is_canonical_account_report(p) or _looks_like_currency_cs_export(p))
            # Positions leftovers named like XTB_*_account*.csv must not block USD/EURO.
            and "Closed/Open Positions" not in statuses[p][1]
        ),
        key=lambda p: p.name.lower(),
    )

    if named_canonical:
        ok = [p for p in named_canonical if statuses[p][0]]
        failed = [(p, statuses[p][1]) for p in named_canonical if not statuses[p][0]]
        if failed:
            details = [
                f"  • {p.name} ({p.stat().st_size} B): {reason}" for p, reason in failed
            ]
            ok_names = ", ".join(p.name for p in ok) or "(żaden)"
            raise ValueError(
                "Nie wszystkie pliki XTB_*_cs.xlsx dały się odczytać.\n"
                f"OK: {ok_names}\n"
                "Błędy:\n"
                + "\n".join(details)
                + "\n\nPotrzebne są oba konta (USD i EURO). "
                "Napraw pliki z błędem (openpyxl / OneDrive → „Zawsze zachowuj na tym urządzeniu” "
                "/ ponowny eksport z xStation) i uruchom ponownie."
            )
        return ok

    return sorted(
        (p for p, (success, _) in statuses.items() if success),
        key=lambda p: p.name.lower(),
    )
