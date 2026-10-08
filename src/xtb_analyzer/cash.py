from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from xtb_analyzer.comment_parser import is_transfer_in, parse_exchange_rate, transfer_target_currency
from xtb_analyzer.models import Account, Transaction


@dataclass
class CashLedger:
    balances: dict[str, Decimal] = field(default_factory=dict)
    deposits_pln: Decimal = Decimal("0")
    dividends: Decimal = Decimal("0")
    interest: Decimal = Decimal("0")
    taxes: Decimal = Decimal("0")


def apply_cash(tx: Transaction, ledger: CashLedger) -> None:
    account_key = f"{tx.account_id}:{tx.currency}"
    ledger.balances[account_key] = ledger.balances.get(account_key, Decimal("0")) + tx.amount

    if tx.type == "transfer_in" and is_transfer_in(tx.comment):
        rate = parse_exchange_rate(tx.comment)
        target = (transfer_target_currency(tx.comment) or tx.currency or "").upper()
        # Same rule as extract_deposits: a PLN-denominated deposit is already PLN.
        if target == "PLN":
            ledger.deposits_pln += tx.amount
        elif rate and rate > 0:
            ledger.deposits_pln += tx.amount / rate
    elif tx.type == "dividend":
        ledger.dividends += tx.amount
    elif tx.type == "interest":
        ledger.interest += tx.amount
    elif tx.type in {"withholding_tax", "interest_tax"}:
        ledger.taxes += abs(tx.amount)


def build_cash_ledger(accounts: list[Account]) -> CashLedger:
    ledger = CashLedger()
    transactions = sorted(
        (tx for account in accounts for tx in account.transactions),
        key=lambda tx: tx.timestamp,
    )
    for tx in transactions:
        apply_cash(tx, ledger)
    return ledger


def cash_summary(ledger: CashLedger) -> dict[str, float]:
    return {
        "deposits_pln": float(ledger.deposits_pln),
        "dividends": float(ledger.dividends),
        "interest": float(ledger.interest),
        "taxes": float(ledger.taxes),
        "balances": {key: float(value) for key, value in ledger.balances.items()},
    }


def income_by_currency(accounts: list[Account]):
    """Dividends, interest and taxes summed per account currency."""
    import pandas as pd

    totals: dict[str, dict[str, Decimal]] = {}
    for account in accounts:
        for tx in account.transactions:
            bucket = totals.setdefault(
                tx.currency,
                {"dividends": Decimal("0"), "interest": Decimal("0"), "taxes": Decimal("0")},
            )
            if tx.type == "dividend":
                bucket["dividends"] += tx.amount
            elif tx.type == "interest":
                bucket["interest"] += tx.amount
            elif tx.type in {"withholding_tax", "interest_tax"}:
                bucket["taxes"] += abs(tx.amount)

    rows = [
        {
            "currency": currency,
            "dividends": float(values["dividends"]),
            "interest": float(values["interest"]),
            "taxes": float(values["taxes"]),
            "net_income": float(values["dividends"] + values["interest"] - values["taxes"]),
        }
        for currency, values in sorted(totals.items())
        if any(value != 0 for value in values.values())
    ]
    return pd.DataFrame(rows)
