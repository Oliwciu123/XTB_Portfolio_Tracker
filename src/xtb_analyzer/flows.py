from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from xtb_analyzer.comment_parser import (
    TRANSFER_RE,
    parse_exchange_rate,
)
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account

CONVERSION_FEE_RATE = Decimal("0.005")


@dataclass
class Deposit:
    timestamp: pd.Timestamp
    account_id: str
    currency: str
    amount_foreign: Decimal
    pln_spent: Decimal
    xtb_rate: Decimal
    is_conversion: bool = True


def first_deposit_date(accounts: list[Account]) -> pd.Timestamp | None:
    deposits = extract_deposits(accounts)
    if not deposits:
        return None
    return pd.Timestamp(deposits[0].timestamp.date())


def extract_deposits(accounts: list[Account], fx: pd.DataFrame | None = None) -> list[Deposit]:
    deposits: list[Deposit] = []
    currencies = {a.currency for a in accounts}
    for account in accounts:
        for tx in account.transactions:
            if tx.type not in ("transfer_in", "transfer_out"):
                continue
            conversion = TRANSFER_RE.search(tx.comment)
            if conversion:
                source = conversion.group("source").upper()
                target_currency = conversion.group("currency").upper()
                if source in currencies and target_currency in currencies:
                    continue  # Both legs belong to the portfolio, not external capital.
                if account.currency != target_currency:
                    continue  # Outgoing conversion to an absent account is ambiguous.
            rate = parse_exchange_rate(tx.comment)
            target = account.currency
            # "PLN to USD, Exchange rate:0.27" means foreign units per 1 PLN.
            # A deposit already denominated in PLN (future PLN account) is the PLN amount itself.
            if target == "PLN":
                if tx.amount is None:
                    continue
                pln_spent = tx.amount
                used_rate = rate or Decimal("1")
            else:
                if conversion and conversion.group("source").upper() == "PLN" and rate and rate > 0:
                    pln_spent = tx.amount / rate
                    used_rate = rate
                else:
                    if fx is None:
                        dates = [t.timestamp for a in accounts for t in a.transactions]
                        fx = fetch_fx_rates(
                            start=(pd.Timestamp(min(dates)) - pd.Timedelta(days=7))
                            .date()
                            .isoformat()
                        )
                    available = fx.loc[: pd.Timestamp(tx.timestamp.date())]
                    row = available.iloc[-1] if not available.empty else pd.Series(dtype=float)
                    pln_spent = Decimal(str(convert_value(float(tx.amount), target, "PLN", row)))
                    used_rate = tx.amount / pln_spent if pln_spent else Decimal("1")
            deposits.append(
                Deposit(
                    timestamp=pd.Timestamp(tx.timestamp),
                    account_id=account.account_id,
                    currency=target,
                    amount_foreign=tx.amount,
                    pln_spent=pln_spent,
                    xtb_rate=used_rate,
                    is_conversion=bool(conversion),
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
    gross = dict.fromkeys(cumulative, 0.0)
    withdrawn = dict.fromkeys(cumulative, 0.0)
    deposits_by_day: dict[pd.Timestamp, list[Deposit]] = {}
    for deposit in deposits:
        day = pd.Timestamp(deposit.timestamp.date())
        deposits_by_day.setdefault(day, []).append(deposit)

    for day in calendar:
        fx_row = fx.loc[:day].iloc[-1] if not fx.empty else pd.Series(dtype=float)
        for deposit in deposits_by_day.get(day, []):
            previous = cumulative.copy()
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
            for code in cumulative:
                delta = cumulative[code] - previous[code]
                gross[code] += max(delta, 0.0)
                withdrawn[code] += max(-delta, 0.0)
        rows.append(
            {
                "date": day,
                "deposits_pln": cumulative["PLN"],
                "deposits_usd": cumulative["USD"],
                "deposits_eur": cumulative["EUR"],
                **{f"gross_deposits_{c.lower()}": gross[c] for c in gross},
                **{f"withdrawals_{c.lower()}": withdrawn[c] for c in withdrawn},
            }
        )
    return pd.DataFrame(rows).set_index("date")


def attach_deposits_to_nav(
    nav: pd.DataFrame,
    accounts: list[Account],
    use_cache: bool = True,
    fx: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if nav.empty:
        return nav
    end = (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).date().isoformat()
    if fx is None:
        fx = fetch_fx_rates(start=nav.index[0].date().isoformat(), end=end, use_cache=use_cache)
    deposits = extract_deposits(accounts, fx=fx)
    cumulative = build_cumulative_deposits(deposits, nav.index, fx)
    enriched = nav.join(cumulative, how="left")
    for currency in ("pln", "usd", "eur"):
        dep_col = f"deposits_{currency}"
        nav_col = f"nav_{currency}"
        enriched[f"gain_{currency}"] = enriched[nav_col] - enriched[dep_col]
        enriched[f"return_{currency}"] = enriched[f"gain_{currency}"] / enriched[
            f"gross_deposits_{currency}"
        ].replace(0, float("nan"))
    return enriched


def analyze_conversion_losses(
    accounts: list[Account], use_cache: bool = True, fx: pd.DataFrame | None = None
) -> pd.DataFrame:
    del use_cache  # FX rates not needed for commission-only calculation
    deposits = extract_deposits(accounts, fx=fx)
    if not deposits:
        return pd.DataFrame()

    rows = []
    for deposit in deposits:
        if not deposit.is_conversion or deposit.currency == "PLN" or deposit.amount_foreign <= 0:
            continue
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
