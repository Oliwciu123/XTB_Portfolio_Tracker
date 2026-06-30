from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from xtb_analyzer.comment_parser import (
    is_transfer_in,
    parse_exchange_rate,
    transfer_target_currency,
)
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account, Transaction

CONVERSION_FEE_RATE = Decimal("0.005")


@dataclass
class Deposit:
    timestamp: pd.Timestamp
    account_id: str
    currency: str
    amount_foreign: Decimal
    pln_spent: Decimal
    xtb_rate: Decimal


def first_deposit_date(accounts: list[Account]) -> pd.Timestamp | None:
    deposits = extract_deposits(accounts)
    if not deposits:
        return None
    return pd.Timestamp(deposits[0].timestamp.date())


def extract_deposits(accounts: list[Account]) -> list[Deposit]:
    deposits: list[Deposit] = []
    for account in accounts:
        for tx in account.transactions:
            if tx.type != "transfer_in" or not is_transfer_in(tx.comment):
                continue
            rate = parse_exchange_rate(tx.comment)
            if not rate or rate <= 0:
                continue
            deposits.append(
                Deposit(
                    timestamp=pd.Timestamp(tx.timestamp),
                    account_id=account.account_id,
                    currency=transfer_target_currency(tx.comment) or account.currency,
                    amount_foreign=tx.amount,
                    pln_spent=tx.amount / rate,
                    xtb_rate=rate,
                )
            )
    return sorted(deposits, key=lambda item: item.timestamp)


def build_cumulative_deposits(
    deposits: list[Deposit],
    calendar: pd.DatetimeIndex,
    fx: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    cumulative = {"PLN": 0.0, "USD": 0.0, "EUR": 0.0}
    deposits_by_day: dict[pd.Timestamp, list[Deposit]] = {}
    for deposit in deposits:
        day = pd.Timestamp(deposit.timestamp.date())
        deposits_by_day.setdefault(day, []).append(deposit)

    for day in calendar:
        fx_row = fx.loc[:day].iloc[-1] if not fx.empty else pd.Series(dtype=float)
        for deposit in deposits_by_day.get(day, []):
            cumulative["PLN"] += float(deposit.pln_spent)
            cumulative["USD"] += convert_value(
                float(deposit.amount_foreign),
                deposit.currency,
                "USD",
                fx_row,
            )
            cumulative["EUR"] += convert_value(
                float(deposit.amount_foreign),
                deposit.currency,
                "EUR",
                fx_row,
            )
        rows.append(
            {
                "date": day,
                "deposits_pln": cumulative["PLN"],
                "deposits_usd": cumulative["USD"],
                "deposits_eur": cumulative["EUR"],
            }
        )
    return pd.DataFrame(rows).set_index("date")


def attach_deposits_to_nav(nav: pd.DataFrame, accounts: list[Account], use_cache: bool = True) -> pd.DataFrame:
    if nav.empty:
        return nav
    deposits = extract_deposits(accounts)
    end = (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).date().isoformat()
    fx = fetch_fx_rates(
        start=nav.index[0].date().isoformat(),
        end=end,
        use_cache=use_cache,
    )
    cumulative = build_cumulative_deposits(deposits, nav.index, fx)
    enriched = nav.join(cumulative, how="left")
    for currency in ("pln", "usd", "eur"):
        dep_col = f"deposits_{currency}"
        nav_col = f"nav_{currency}"
        enriched[f"gain_{currency}"] = enriched[nav_col] - enriched[dep_col]
        enriched[f"return_{currency}"] = (
            enriched[nav_col] / enriched[dep_col].replace(0, pd.NA) - 1
        )
    return enriched


def analyze_conversion_losses(accounts: list[Account], use_cache: bool = True) -> pd.DataFrame:
    del use_cache  # FX rates not needed for commission-only calculation
    deposits = extract_deposits(accounts)
    if not deposits:
        return pd.DataFrame()

    rows = []
    for deposit in deposits:
        pln_spent = float(deposit.pln_spent)
        commission_loss_pln = pln_spent * float(CONVERSION_FEE_RATE)

        rows.append(
            {
                "timestamp": deposit.timestamp,
                "account_id": deposit.account_id,
                "to_currency": deposit.currency,
                "pln_spent": pln_spent,
                "foreign_received": float(deposit.amount_foreign),
                "xtb_rate": float(deposit.xtb_rate),
                "commission_loss_pln": commission_loss_pln,
                "total_loss_pln": commission_loss_pln,
            }
        )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["cumulative_loss_pln"] = frame["total_loss_pln"].cumsum()
    return frame


def conversion_summary(losses: pd.DataFrame) -> dict[str, float]:
    if losses.empty:
        return {
            "total_pln_converted": 0.0,
            "total_commission_pln": 0.0,
            "total_loss_pln": 0.0,
            "avg_loss_pct": 0.0,
        }
    total_pln = float(losses["pln_spent"].sum())
    total_loss = float(losses["total_loss_pln"].sum())
    return {
        "total_pln_converted": total_pln,
        "total_commission_pln": float(losses["commission_loss_pln"].sum()),
        "total_loss_pln": total_loss,
        "avg_loss_pct": total_loss / total_pln if total_pln else 0.0,
    }
