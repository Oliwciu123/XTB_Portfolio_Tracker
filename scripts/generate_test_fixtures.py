"""Rebuild the small, fictional parser fixtures without reading private data.

Only the export layouts are based on XTB reports. Names, identifiers, dates,
transactions, quantities, prices, and account balances are invented here.
"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
ACCOUNTS = {"USD": "90000001", "EUR": "90000002"}
LEGACY_HEADER = ["ID", "Type", "Time", "Comment", "Symbol", "Amount"]
MODERN_HEADER = ["ID", "Type", "Time", "Symbol", "Comment", "Amount"]
V2_HEADER = ["Type", "Ticker", "Instrument", "Time", "Amount", "ID", "Comment", "Product"]


def transactions(currency: str) -> list[dict[str, str]]:
    """A fictional eight-month history including partial fills and sales."""
    account = ACCOUNTS[currency]
    symbols = ("MSFT.US", "AAPL.US") if currency == "USD" else ("SAP.DE", "SIE.DE")
    rate = "0.25" if currency == "USD" else "0.20"
    rows: list[dict[str, str]] = []
    for month in range(1, 9):
        events = [
            (
                "Transfer",
                "",
                "1000.00",
                f"Currency conversion, PLN to {currency} from TA: 90000000 to: {account}, Exchange rate:{rate}",
            ),
            ("Stock purchase", symbols[0], "-100.00", "OPEN BUY 1 @ 100.00"),
            ("Stock purchase", symbols[1], "-100.00", "OPEN BUY 2 @ 50.00"),
            ("Stock purchase", symbols[0], "-50.00", "OPEN BUY 0.5/1.5 @ 100.00"),
            ("Stock sell", symbols[0], "50.00", "CLOSE BUY 0.5/1.5 @ 120.00"),
            ("Close trade", symbols[0], "10.00", f"Profit of position #{70000000 + month}"),
            ("Dividend", symbols[1], "3.00", "Synthetic cash dividend"),
            ("Withholding tax", symbols[1], "-0.45", "Synthetic dividend withholding tax"),
            ("Free funds interest", "", "1.00", "Synthetic free-funds interest"),
            ("Interest tax", "", "-0.19", "Synthetic interest withholding tax"),
        ]
        for hour, (kind, symbol, amount, comment) in enumerate(events, 9):
            rows.append(
                {
                    "ID": str(80000000 + len(rows)),
                    "Type": kind,
                    "Time": datetime(2024, month, 2, hour).isoformat(sep=" "),
                    "Comment": comment,
                    "Symbol": symbol,
                    "Amount": amount,
                }
            )
    return rows


def metadata(currency: str) -> list[list[str]]:
    rows = transactions(currency)
    balance = sum(Decimal(row["Amount"]) for row in rows)
    # Eight shares at 120 and sixteen shares at 55: fictional end-of-export prices.
    equity = balance + Decimal("1840")
    return [
        ["Account", "Currency", "Name and surname", "Balance", "Equity", "Margin", "Free margin"],
        [
            ACCOUNTS[currency],
            currency,
            "Synthetic Investor",
            str(balance),
            str(equity),
            "0",
            str(equity),
        ],
        ["CASH OPERATION HISTORY"],
    ]


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, delimiter=";").writerows(rows)


def preamble(currency: str) -> list[list[str]]:
    return [
        ["Account number", ACCOUNTS[currency]],
        ["Cash Operations"],
        ["Date from (UTC)", "2024-01-01 00:00:00"],
        ["Date to (UTC)", "2024-09-01 00:00:00"],
    ]


def v2_rows(currency: str) -> list[list[str]]:
    rows = transactions(currency)[:10]
    rows += [
        transactions(currency)[10],
        {
            "ID": "81000001",
            "Type": "Stock purchase",
            "Time": "2024-02-03 10:00:00",
            "Symbol": "MSFT.US" if currency == "USD" else "SAP.DE",
            "Amount": "-75.00",
            "Comment": "OPEN BUY 0.75 @ 100.00",
        },
        {
            "ID": "81000002",
            "Type": "Dividend",
            "Time": "2024-02-05 10:00:00",
            "Symbol": "AAPL.US" if currency == "USD" else "SIE.DE",
            "Amount": "1.00",
            "Comment": "Synthetic cash dividend",
        },
    ]
    return (
        preamble(currency)
        + [V2_HEADER]
        + [
            [
                r["Type"],
                r["Symbol"],
                "Synthetic instrument" if r["Symbol"] else "",
                r["Time"],
                r["Amount"].replace(".", ","),
                r["ID"],
                r["Comment"],
                "My Trades",
            ]
            for r in rows
        ]
    )


def save_book(path: Path, sheets: dict[str, list[list[str]]], single_column: bool = False) -> None:
    book = Workbook()
    book.remove(book.active)
    book.properties.creator = "XTB Analyzer synthetic data generator"
    book.properties.lastModifiedBy = "Synthetic data generator"
    book.properties.created = datetime(2024, 1, 1)
    book.properties.modified = datetime(2024, 1, 1)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append([";".join(row)] if single_column else row)
    book.save(path)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for currency in ACCOUNTS:
        rows = transactions(currency)
        legacy = (
            metadata(currency) + [LEGACY_HEADER] + [[r[c] for c in LEGACY_HEADER] for r in rows]
        )
        save_book(
            FIXTURES / f"legacy_{currency.lower()}_account.xlsx", {"CASH OPERATION HISTORY": legacy}
        )
    usd = transactions("USD")
    write_csv(
        FIXTURES / "legacy_usd_cash_ops.csv",
        metadata("USD") + [LEGACY_HEADER] + [[r[c] for c in LEGACY_HEADER] for r in usd],
    )
    modern = [MODERN_HEADER] + [[r[c] for c in MODERN_HEADER] for r in usd]
    write_csv(FIXTURES / "modern_usd_cash_ops.csv", modern)
    deposit = ["82000000", "Deposit", "2024-01-01 09:00:00", "", "Synthetic bank deposit", "500.00"]
    write_csv(FIXTURES / "modern_with_deposit.csv", [MODERN_HEADER, deposit] + modern[1:])
    write_csv(FIXTURES / "xtb_v2_usd_cash_ops.csv", v2_rows("USD"))
    save_book(
        FIXTURES / "xtb_v2_euro_single_col.xlsx",
        {"Cash Operations": v2_rows("EUR")},
        single_column=True,
    )
    closed = [
        ["Account number", ACCOUNTS["EUR"]],
        ["Closed Positions"],
        [
            "Instrument",
            "Ticker",
            "Type",
            "Volume",
            "Open Price",
            "Close Price",
            "Profit/Loss",
            "ID",
        ],
        ["Synthetic company", "SAP.DE", "Stock", "1", "100.00", "120.00", "20.00", "83000000"],
    ]
    write_csv(FIXTURES / "xtb_v2_closed_positions.csv", closed)
    multi_closed = [list(row) for row in closed]
    multi_closed[0][1] = ACCOUNTS["USD"]
    write_csv(FIXTURES / "xtb_v2_multi_section.csv", multi_closed + [[]] + v2_rows("USD"))
    print("Generated small synthetic parser fixtures; demo data is generated separately.")


if __name__ == "__main__":
    main()
