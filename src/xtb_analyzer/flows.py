from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from xtb_analyzer.comment_parser import (
    TRANSFER_RE,
    parse_exchange_rate,
)
from xtb_analyzer.fx import convert_value, fetch_fx_rates
from xtb_analyzer.models import Account
from xtb_analyzer.prices import warsaw_today

CONVERSION_FEE_RATE = Decimal("0.005")
MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class Deposit:
    timestamp: pd.Timestamp
    account_id: str
    currency: str
    amount_foreign: Decimal
    pln_spent: Decimal
    xtb_rate: Decimal
    is_conversion: bool = True
    tx_id: str = ""
    comment: str = ""


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
                    tx_id=tx.id,
                    comment=tx.comment,
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
    end = (warsaw_today() + pd.Timedelta(days=1)).date().isoformat()
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


_DEPOSIT_OPS_COLUMNS = [
    "tx_id",
    "timestamp",
    "date",
    "year",
    "month",
    "month_name",
    "year_month",
    "account_id",
    "currency",
    "amount_foreign",
    "pln_spent",
    "amount",
    "report_currency",
    "xtb_rate",
    "is_conversion",
    "comment",
]


def extract_deposit_operations(
    accounts: list[Account],
    currency: str = "pln",
    fx: pd.DataFrame | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Extract inbound external deposit operations converted into ``currency``."""
    target_curr = currency.upper()
    deposits = [d for d in extract_deposits(accounts, fx=fx) if d.amount_foreign > 0]
    if not deposits:
        return pd.DataFrame(columns=_DEPOSIT_OPS_COLUMNS)

    if target_curr != "PLN" and fx is None and any(d.currency != target_curr for d in deposits):
        start = (
            (pd.Timestamp(deposits[0].timestamp.date()) - pd.Timedelta(days=7)).date().isoformat()
        )
        end = (
            (pd.Timestamp(deposits[-1].timestamp.date()) + pd.Timedelta(days=1)).date().isoformat()
        )
        fx = fetch_fx_rates(start=start, end=end, use_cache=use_cache)

    rows: list[dict[str, object]] = []
    for dep in deposits:
        ts = pd.Timestamp(dep.timestamp)
        day = pd.Timestamp(ts.date())
        if target_curr == "PLN":
            amount_report = float(dep.pln_spent)
        elif dep.currency.upper() == target_curr:
            amount_report = float(dep.amount_foreign)
        else:
            available = fx.loc[:day] if fx is not None and not fx.empty else pd.DataFrame()
            fx_row = available.iloc[-1] if not available.empty else pd.Series(dtype=float)
            amount_report = convert_value(
                float(dep.amount_foreign), dep.currency.upper(), target_curr, fx_row
            )
        month_num = int(ts.month)
        rows.append(
            {
                "tx_id": dep.tx_id,
                "timestamp": ts,
                "date": ts.strftime("%Y-%m-%d"),
                "year": int(ts.year),
                "month": month_num,
                "month_name": MONTH_ABBR[month_num - 1],
                "year_month": ts.strftime("%Y-%m"),
                "account_id": dep.account_id,
                "currency": dep.currency.upper(),
                "amount_foreign": float(dep.amount_foreign),
                "pln_spent": float(dep.pln_spent),
                "amount": float(amount_report),
                "report_currency": target_curr,
                "xtb_rate": float(dep.xtb_rate),
                "is_conversion": bool(dep.is_conversion),
                "comment": dep.comment,
            }
        )
    return pd.DataFrame(rows, columns=_DEPOSIT_OPS_COLUMNS)


def filter_deposit_operations(
    deposit_ops: pd.DataFrame,
    *,
    years: Iterable[int] | None = None,
    month: int | None = None,
    year_month: str | None = None,
) -> pd.DataFrame:
    """Filter deposit operations by selected year(s), calendar month (1..12), or YYYY-MM."""
    if deposit_ops.empty:
        return deposit_ops.copy()
    view = deposit_ops
    if years is not None:
        year_set = {int(y) for y in years}
        view = view[view["year"].isin(year_set)]
    if year_month:
        view = view[view["year_month"] == str(year_month)]
    elif month is not None:
        view = view[view["month"] == int(month)]
    return view.reset_index(drop=True)


def aggregate_deposits_monthly(
    deposit_ops: pd.DataFrame,
    *,
    years: Iterable[int] | None = None,
    by_calendar_month: bool = False,
) -> pd.DataFrame:
    """Aggregate deposited capital either chronologically (YYYY-MM) or across calendar months (Jan-Dec)."""
    filtered = filter_deposit_operations(deposit_ops, years=years)
    if by_calendar_month:
        rows = []
        for m in range(1, 13):
            sub = filtered[filtered["month"] == m] if not filtered.empty else filtered
            rows.append(
                {
                    "month": m,
                    "month_label": MONTH_ABBR[m - 1],
                    "total_amount": float(sub["amount"].sum()) if not sub.empty else 0.0,
                    "deposit_count": int(len(sub)),
                    "years_active": int(sub["year"].nunique()) if not sub.empty else 0,
                }
            )
        return pd.DataFrame(rows)

    if filtered.empty:
        return pd.DataFrame(
            columns=[
                "year",
                "month",
                "month_label",
                "year_month",
                "label",
                "total_amount",
                "deposit_count",
            ]
        )

    selected_years = sorted({int(y) for y in years}) if years is not None else None
    grouped = (
        filtered.groupby(["year", "month", "year_month"], as_index=False)
        .agg(total_amount=("amount", "sum"), deposit_count=("amount", "count"))
        .sort_values(["year", "month"])
    )
    by_ym = {
        str(row["year_month"]): (float(row["total_amount"]), int(row["deposit_count"]))
        for _, row in grouped.iterrows()
    }

    # Build a clean continuous monthly axis for selected years (or min..max period when unfiltered).
    if selected_years:
        max_ym_in_data = str(deposit_ops["year_month"].max())
        timeline_months = [
            (yr, m)
            for yr in selected_years
            for m in range(1, 13)
            if f"{yr:04d}-{m:02d}" <= max_ym_in_data or f"{yr:04d}-{m:02d}" in by_ym
        ]
    else:
        start_ym = pd.Period(str(filtered["year_month"].min()), freq="M")
        end_ym = pd.Period(str(filtered["year_month"].max()), freq="M")
        periods = pd.period_range(start_ym, end_ym, freq="M")
        timeline_months = [(int(p.year), int(p.month)) for p in periods]

    out_rows = []
    for yr, m in timeline_months:
        ym = f"{yr:04d}-{m:02d}"
        amt, cnt = by_ym.get(ym, (0.0, 0))
        out_rows.append(
            {
                "year": yr,
                "month": m,
                "month_label": MONTH_ABBR[m - 1],
                "year_month": ym,
                "label": f"{MONTH_ABBR[m - 1]} {yr}",
                "total_amount": amt,
                "deposit_count": cnt,
            }
        )
    return pd.DataFrame(out_rows)


def top_deposit_months(
    deposit_ops: pd.DataFrame,
    *,
    years: Iterable[int] | None = None,
    limit: int = 10,
) -> pd.DataFrame:
    """Return the Top N highest-deposit months (YYYY-MM) within the selected year(s)."""
    filtered = filter_deposit_operations(deposit_ops, years=years)
    cols = [
        "rank",
        "year_month",
        "label",
        "year",
        "month",
        "deposit_count",
        "total_amount",
        "share_pct",
    ]
    if filtered.empty or limit <= 0:
        return pd.DataFrame(columns=cols)

    scope_total = float(filtered["amount"].sum())
    grouped = (
        filtered.groupby(["year_month", "year", "month"], as_index=False)
        .agg(total_amount=("amount", "sum"), deposit_count=("amount", "count"))
        .sort_values(
            by=["total_amount", "deposit_count", "year_month"],
            ascending=[False, False, False],
        )
        .head(limit)
        .reset_index(drop=True)
    )
    grouped["rank"] = range(1, len(grouped) + 1)
    grouped["label"] = grouped.apply(
        lambda r: f"{MONTH_ABBR[int(r['month']) - 1]} {int(r['year'])}", axis=1
    )
    grouped["share_pct"] = grouped["total_amount"] / scope_total if scope_total > 0 else 0.0
    return grouped[cols]
