from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from xtb_analyzer.comment_parser import is_transfer_in, parse_exchange_rate
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
        if rate and rate > 0:
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
