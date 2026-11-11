"""Polish PIT-38 tax engine: FIFO capital gains, NBP Table A D-1 FX, and dividend WHT credits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from xtb_analyzer.fx import fetch_fx_rates, fetch_nbp_currency_series
from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.prices import warsaw_today

PIT38_TAX_RATE = Decimal("0.19")
CENT = Decimal("0.01")
SHARES_EPS = Decimal("0.00000001")

_COMMISSION_TOKENS = (
    "commission",
    "prowizja",
    "sec fee",
    "stamp",
    "brokerage",
    "ftt",
    "transaction tax",
    "opłata transakcyjna",
    "oplata transakcyjna",
)


def _q2(val: Decimal) -> Decimal:
    return val.quantize(CENT, rounding=ROUND_HALF_UP)


def _round_full_pln(val: Decimal) -> int:
    if val <= 0:
        return 0
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class NbpRateLookup:
    currency: str
    rate: Decimal
    effective_date: str


@dataclass
class _FifoLot:
    tx_id: str
    buy_date: str
    remaining_shares: Decimal
    unit_price_orig: Decimal
    remaining_principal_orig: Decimal
    remaining_principal_pln: Decimal
    remaining_buy_comm_orig: Decimal
    remaining_buy_comm_pln: Decimal
    nbp_rate: Decimal
    nbp_date: str


@dataclass(frozen=True)
class FifoLotMatch:
    tax_year: int
    account_id: str
    symbol: str
    currency: str
    buy_tx_id: str
    sell_tx_id: str
    buy_date: str
    sell_date: str
    shares: float
    buy_price_orig: float
    sell_price_orig: float
    cost_orig: float
    proceeds_orig: float
    buy_commission_orig: float
    sell_commission_orig: float
    buy_nbp_rate: float
    buy_nbp_date: str
    sell_nbp_rate: float
    sell_nbp_date: str
    acquisition_cost_pln: float
    commission_pln: float
    deductible_cost_pln: float
    revenue_pln: float
    gain_loss_pln: float


@dataclass(frozen=True)
class DividendTaxEntry:
    tax_year: int
    account_id: str
    symbol: str
    currency: str
    tx_id: str
    date: str
    gross_orig: float
    wht_orig: float
    wht_rate_pct: float
    nbp_rate: float
    nbp_date: str
    wht_nbp_rate: float
    wht_nbp_date: str
    gross_pln: float
    wht_paid_pln: float
    polish_tax_19_pln: float
    wht_credit_pln: float
    tax_due_pln: float


@dataclass(frozen=True)
class Pit38YearSummary:
    year: int
    is_ytd: bool
    sold_lots_count: int
    section_c_revenue_pln: float
    section_c_costs_pln: float
    section_c_commissions_pln: float
    section_c_income_pln: float
    section_c_loss_pln: float
    section_c_net_pln: float
    section_c_tax_base_rounded_pln: int
    section_c_tax_pln: float
    section_c_tax_rounded_pln: int
    dividends_count: int
    dividends_gross_pln: float
    dividends_polish_tax_19_pln: float
    dividends_wht_paid_pln: float
    dividends_wht_credit_pln: float
    dividends_tax_due_pln: float
    dividends_tax_due_rounded_pln: int
    total_tax_due_pln: float
    total_tax_due_rounded_pln: int


@dataclass(frozen=True)
class Pit38Report:
    available_years: list[int]
    latest_year: int | None
    by_year: dict[int, Pit38YearSummary]
    all_years_summary: Pit38YearSummary
    fifo_matches: list[FifoLotMatch]
    dividends: list[DividendTaxEntry]
    open_lots_count: int

    def to_payload(self) -> dict[str, object]:
        return {
            "available_years": self.available_years,
            "latest_year": self.latest_year,
            "by_year": {str(yr): asdict(summary) for yr, summary in self.by_year.items()},
            "all_years_summary": asdict(self.all_years_summary),
            "fifo_matches": [asdict(m) for m in self.fifo_matches],
            "dividends": [asdict(d) for d in self.dividends],
            "open_lots_count": self.open_lots_count,
        }


def lookup_nbp_d_minus_1_rate(
    currency: str,
    tx_date: date | datetime | pd.Timestamp | str,
    fx: pd.DataFrame,
    *,
    allow_boundary_fallback: bool = False,
) -> NbpRateLookup:
    """Return official NBP Table A mid rate from the last business day preceding ``tx_date``."""
    code = currency.strip().upper()
    day = pd.Timestamp(tx_date).normalize()
    if code == "PLN":
        return NbpRateLookup(
            currency="PLN", rate=Decimal("1"), effective_date=day.strftime("%Y-%m-%d")
        )

    nbp_df = fx.attrs.get("nbp_table_a", fx) if fx is not None else pd.DataFrame()
    col = f"{code}PLN"
    if nbp_df is None or nbp_df.empty or col not in nbp_df.columns:
        raise ValueError(f"Missing NBP Table A exchange-rate column {col} for PIT-38 valuation.")

    series = nbp_df[col].dropna().sort_index()
    if series.empty:
        raise ValueError(f"Empty NBP Table A exchange-rate series {col} for PIT-38 valuation.")

    prior = series.loc[series.index < day]
    if not prior.empty:
        eff_day = pd.Timestamp(prior.index[-1]).strftime("%Y-%m-%d")
        return NbpRateLookup(
            currency=code,
            rate=Decimal(str(float(prior.iloc[-1]))),
            effective_date=eff_day,
        )

    if allow_boundary_fallback and day == pd.Timestamp(series.index[0]).normalize():
        eff_day = pd.Timestamp(series.index[0]).strftime("%Y-%m-%d")
        return NbpRateLookup(
            currency=code,
            rate=Decimal(str(float(series.iloc[0]))),
            effective_date=eff_day,
        )

    raise ValueError(
        f"No NBP Table A mid rate available before {day.strftime('%Y-%m-%d')} for {code}."
    )


def _is_commission_tx(tx: Transaction) -> bool:
    if tx.type != "other" or not tx.symbol or tx.amount >= 0:
        return False
    haystack = f"{tx.raw_type} {tx.comment}".lower()
    return any(tok in haystack for tok in _COMMISSION_TOKENS)


def _ensure_fx_for_tax(
    accounts: list[Account],
    fx: pd.DataFrame | None,
    use_cache: bool,
) -> pd.DataFrame:
    all_txs = [tx for acc in accounts for tx in acc.transactions]
    if not all_txs:
        return pd.DataFrame()

    min_date = min(tx.timestamp for tx in all_txs).date().isoformat()
    max_date = (
        (pd.Timestamp(max(tx.timestamp for tx in all_txs).date()) + pd.Timedelta(days=2))
        .date()
        .isoformat()
    )

    if fx is None:
        fx = fetch_fx_rates(start=min_date, end=max_date, use_cache=use_cache, refresh_latest=False)

    needed_currencies = {
        tx.currency.upper() for tx in all_txs if tx.currency and tx.currency.upper() != "PLN"
    }
    is_yahoo_fallback = fx.attrs.get("fx_source") == "yahoo" and "nbp_table_a" not in fx.attrs
    nbp_base = (
        pd.DataFrame()
        if is_yahoo_fallback
        else (fx.attrs.get("nbp_table_a", fx).copy() if not fx.empty else pd.DataFrame())
    )
    missing_cols = [c for c in sorted(needed_currencies) if f"{c}PLN" not in nbp_base.columns]
    if missing_cols:
        extra_series = {
            f"{code}PLN": fetch_nbp_currency_series(
                code, start=min_date, end=max_date, use_cache=use_cache
            )
            for code in missing_cols
        }
        extra_df = pd.DataFrame(extra_series)
        nbp_base = (
            nbp_base.join(extra_df, how="outer").sort_index() if not nbp_base.empty else extra_df
        )
        fx = fx.copy()
        for col_name, ser in extra_series.items():
            fx[col_name] = ser.reindex(fx.index, method="ffill")
        fx.attrs["nbp_table_a"] = nbp_base
    return fx


def _build_summary(
    year: int,
    is_ytd: bool,
    matches: list[FifoLotMatch],
    standalone_commissions_pln: Decimal,
    dividends: list[DividendTaxEntry],
) -> Pit38YearSummary:
    rev_dec = sum((Decimal(str(m.revenue_pln)) for m in matches), Decimal("0.00"))
    cost_dec = (
        sum((Decimal(str(m.deductible_cost_pln)) for m in matches), Decimal("0.00"))
        + standalone_commissions_pln
    )
    comm_dec = (
        sum((Decimal(str(m.commission_pln)) for m in matches), Decimal("0.00"))
        + standalone_commissions_pln
    )
    rev_q = _q2(rev_dec)
    cost_q = _q2(cost_dec)
    comm_q = _q2(comm_dec)
    net_q = _q2(rev_q - cost_q)
    inc_q = net_q if net_q > 0 else Decimal("0.00")
    loss_q = abs(net_q) if net_q < 0 else Decimal("0.00")

    sec_c_tax_exact = _q2(inc_q * PIT38_TAX_RATE) if inc_q > 0 else Decimal("0.00")
    sec_c_base_rounded = _round_full_pln(inc_q)
    sec_c_tax_rounded = (
        _round_full_pln(Decimal(sec_c_base_rounded) * PIT38_TAX_RATE)
        if sec_c_base_rounded > 0
        else 0
    )

    div_gross = _q2(sum((Decimal(str(d.gross_pln)) for d in dividends), Decimal("0.00")))
    div_pl_19 = _q2(sum((Decimal(str(d.polish_tax_19_pln)) for d in dividends), Decimal("0.00")))
    div_wht_paid = _q2(sum((Decimal(str(d.wht_paid_pln)) for d in dividends), Decimal("0.00")))
    div_wht_cred = _q2(sum((Decimal(str(d.wht_credit_pln)) for d in dividends), Decimal("0.00")))
    div_due = _q2(sum((Decimal(str(d.tax_due_pln)) for d in dividends), Decimal("0.00")))
    div_due_rounded = _round_full_pln(div_due)

    total_exact = _q2(sec_c_tax_exact + div_due)
    total_rounded = sec_c_tax_rounded + div_due_rounded

    return Pit38YearSummary(
        year=year,
        is_ytd=is_ytd,
        sold_lots_count=len(matches),
        section_c_revenue_pln=float(rev_q),
        section_c_costs_pln=float(cost_q),
        section_c_commissions_pln=float(comm_q),
        section_c_income_pln=float(inc_q),
        section_c_loss_pln=float(loss_q),
        section_c_net_pln=float(net_q),
        section_c_tax_base_rounded_pln=sec_c_base_rounded,
        section_c_tax_pln=float(sec_c_tax_exact),
        section_c_tax_rounded_pln=sec_c_tax_rounded,
        dividends_count=len(dividends),
        dividends_gross_pln=float(div_gross),
        dividends_polish_tax_19_pln=float(div_pl_19),
        dividends_wht_paid_pln=float(div_wht_paid),
        dividends_wht_credit_pln=float(div_wht_cred),
        dividends_tax_due_pln=float(div_due),
        dividends_tax_due_rounded_pln=div_due_rounded,
        total_tax_due_pln=float(total_exact),
        total_tax_due_rounded_pln=total_rounded,
    )


def compute_pit38_report(
    accounts: list[Account],
    fx: pd.DataFrame | None = None,
    *,
    splits: dict[str, dict[str, float]] | None = None,
    use_cache: bool = True,
    allow_boundary_fallback: bool = False,
    last_date: date | pd.Timestamp | None = None,
) -> Pit38Report:
    """Compute Polish PIT-38 capital-gains (FIFO) and dividend tax settlements across all years."""
    all_txs = [tx for acc in accounts for tx in acc.transactions]
    if not all_txs:
        empty_sum = _build_summary(0, False, [], Decimal("0.00"), [])
        return Pit38Report(
            available_years=[],
            latest_year=None,
            by_year={},
            all_years_summary=empty_sum,
            fifo_matches=[],
            dividends=[],
            open_lots_count=0,
        )

    fx_df = _ensure_fx_for_tax(accounts, fx, use_cache=use_cache)

    # Index paired close_trade rows per (account_id, symbol, date)
    close_trades_by_key: dict[tuple[str, str, date], list[Transaction]] = {}
    commission_txs: list[Transaction] = []
    trade_txs: list[Transaction] = []
    dividend_txs: list[Transaction] = []
    wht_txs: list[Transaction] = []

    for acc in accounts:
        for tx in acc.transactions:
            if tx.type == "close_trade" and tx.symbol:
                key = (tx.account_id, tx.symbol, tx.timestamp.date())
                close_trades_by_key.setdefault(key, []).append(tx)
            elif _is_commission_tx(tx):
                commission_txs.append(tx)
            elif tx.type in ("buy", "sell") and tx.symbol and tx.shares:
                trade_txs.append(tx)
            elif tx.type == "dividend" and tx.amount > 0:
                dividend_txs.append(tx)
            elif tx.type == "withholding_tax":
                wht_txs.append(tx)

    for bucket in close_trades_by_key.values():
        bucket.sort(key=lambda t: t.timestamp)

    # Pair standalone commission rows with same-day buy or sell of (account_id, symbol)
    buy_extra_comm: dict[int, list[tuple[Decimal, Decimal]]] = {}
    sell_extra_comm: dict[int, list[tuple[Decimal, Decimal]]] = {}
    standalone_comm_by_year: dict[int, Decimal] = {}

    trades_by_key_day: dict[tuple[str, str, date], list[Transaction]] = {}
    for tx in trade_txs:
        trades_by_key_day.setdefault(
            (tx.account_id, tx.symbol or "", tx.timestamp.date()), []
        ).append(tx)

    for comm_tx in sorted(commission_txs, key=lambda t: t.timestamp):
        comm_orig = abs(comm_tx.amount)
        nbp = lookup_nbp_d_minus_1_rate(
            comm_tx.currency,
            comm_tx.timestamp,
            fx_df,
            allow_boundary_fallback=allow_boundary_fallback,
        )
        comm_pln = comm_orig * nbp.rate
        candidates = trades_by_key_day.get(
            (comm_tx.account_id, comm_tx.symbol or "", comm_tx.timestamp.date()), []
        )
        if candidates:
            target_tx = min(
                candidates,
                key=lambda t: (
                    abs((t.timestamp - comm_tx.timestamp).total_seconds()),
                    0 if t.type == "sell" else 1,
                ),
            )
            target_map = sell_extra_comm if target_tx.type == "sell" else buy_extra_comm
            target_map.setdefault(id(target_tx), []).append((comm_orig, comm_pln))
        else:
            yr = comm_tx.timestamp.year
            standalone_comm_by_year[yr] = standalone_comm_by_year.get(yr, Decimal("0.00")) + _q2(
                comm_pln
            )

    # Sort buy/sell chronologically; on identical timestamps process buys before sells.
    trade_txs.sort(key=lambda t: (t.timestamp, 0 if t.type == "buy" else 1))

    # Pre-organize split dates per symbol
    split_events: dict[str, list[tuple[date, Decimal]]] = {}
    for sym, sym_splits in (splits or {}).items():
        parsed_splits = sorted(
            (pd.Timestamp(day_str).date(), Decimal(str(ratio)))
            for day_str, ratio in sym_splits.items()
            if ratio and float(ratio) > 0 and float(ratio) != 1.0
        )
        if parsed_splits:
            split_events[sym] = parsed_splits
    applied_splits: dict[tuple[str, str], set[date]] = {}

    open_lots: dict[tuple[str, str], list[_FifoLot]] = {}
    fifo_matches: list[FifoLotMatch] = []

    for tx in trade_txs:
        symbol = tx.symbol or ""
        lot_key = (tx.account_id, symbol)
        tx_day = tx.timestamp.date()

        # Apply stock splits effective on or before tx_day strictly to lots opened before sp_date.
        if symbol in split_events:
            done = applied_splits.setdefault(lot_key, set())
            for sp_date, sp_ratio in split_events[symbol]:
                if sp_date <= tx_day and sp_date not in done:
                    sp_iso = sp_date.isoformat()
                    for lot in open_lots.get(lot_key, []):
                        if lot.buy_date < sp_iso:
                            lot.remaining_shares *= sp_ratio
                            lot.unit_price_orig /= sp_ratio
                    done.add(sp_date)

        shares = Decimal(str(tx.shares))
        nbp = lookup_nbp_d_minus_1_rate(
            tx.currency,
            tx.timestamp,
            fx_df,
            allow_boundary_fallback=allow_boundary_fallback,
        )

        if tx.type == "buy":
            cash_outflow = abs(tx.amount)
            explicit_comm = abs(Decimal(str(tx.commission))) if tx.commission is not None else None
            gross_est = (
                (shares * Decimal(str(tx.price))).quantize(CENT, rounding=ROUND_HALF_UP)
                if tx.price is not None
                else None
            )

            if explicit_comm is not None:
                if gross_est is not None and abs(
                    cash_outflow - (gross_est + explicit_comm)
                ) <= Decimal("0.02"):
                    principal_orig = cash_outflow - explicit_comm
                else:
                    principal_orig = cash_outflow
                buy_comm_orig = explicit_comm
            elif gross_est is not None and cash_outflow > gross_est + CENT:
                principal_orig = gross_est
                buy_comm_orig = cash_outflow - gross_est
            else:
                principal_orig = cash_outflow
                buy_comm_orig = Decimal("0")

            principal_pln = principal_orig * nbp.rate
            buy_comm_pln = buy_comm_orig * nbp.rate

            for ex_orig, ex_pln in buy_extra_comm.get(id(tx), []):
                buy_comm_orig += ex_orig
                buy_comm_pln += ex_pln

            unit_price = (
                Decimal(str(tx.price)) if tx.price is not None else (principal_orig / shares)
            )
            open_lots.setdefault(lot_key, []).append(
                _FifoLot(
                    tx_id=tx.id,
                    buy_date=tx_day.isoformat(),
                    remaining_shares=shares,
                    unit_price_orig=unit_price,
                    remaining_principal_orig=principal_orig,
                    remaining_principal_pln=principal_pln,
                    remaining_buy_comm_orig=buy_comm_orig,
                    remaining_buy_comm_pln=buy_comm_pln,
                    nbp_rate=nbp.rate,
                    nbp_date=nbp.effective_date,
                )
            )

        elif tx.type == "sell":
            lots = open_lots.get(lot_key, [])
            if not lots:
                raise ValueError(
                    f"PIT-38 FIFO error: sale of {symbol} on {tx_day} has no preceding purchase lots."
                )

            close_queue = close_trades_by_key.get((tx.account_id, symbol, tx_day), [])
            paired_close = close_queue.pop(0) if close_queue else None
            close_pnl = paired_close.amount if paired_close is not None else Decimal("0")

            explicit_comm = abs(Decimal(str(tx.commission))) if tx.commission is not None else None
            if tx.price is not None:
                gross_proceeds_orig = (shares * Decimal(str(tx.price))).quantize(
                    CENT, rounding=ROUND_HALF_UP
                )
                net_cash = tx.amount + close_pnl
                embedded_comm = (
                    gross_proceeds_orig - net_cash
                    if (gross_proceeds_orig - net_cash) > CENT
                    else Decimal("0")
                )
            else:
                gross_proceeds_orig = abs(tx.amount) + close_pnl
                embedded_comm = Decimal("0")

            if explicit_comm is not None:
                if embedded_comm > 0 and abs(embedded_comm - explicit_comm) <= Decimal("0.02"):
                    sell_comm_orig = explicit_comm
                else:
                    sell_comm_orig = embedded_comm + explicit_comm
            else:
                sell_comm_orig = embedded_comm

            sell_comm_pln_total = sell_comm_orig * nbp.rate
            for ex_orig, ex_pln in sell_extra_comm.get(id(tx), []):
                sell_comm_orig += ex_orig
                sell_comm_pln_total += ex_pln

            total_revenue_pln_q = _q2(gross_proceeds_orig * nbp.rate)
            total_sell_comm_pln_q = _q2(sell_comm_pln_total)
            sell_unit_price = (
                Decimal(str(tx.price)) if tx.price is not None else (gross_proceeds_orig / shares)
            )

            to_sell = shares
            pending_slices: list[tuple[_FifoLot, Decimal, bool]] = []
            while to_sell > SHARES_EPS:
                if not lots:
                    raise ValueError(
                        f"PIT-38 FIFO error: sale of {symbol} ({shares} sh) on {tx_day} exceeds open FIFO lots."
                    )
                head = lots[0]
                if head.remaining_shares <= to_sell + SHARES_EPS:
                    take = head.remaining_shares
                    to_sell = max(Decimal("0"), to_sell - take)
                    lots.pop(0)
                    pending_slices.append((head, take, True))
                else:
                    take = to_sell
                    to_sell = Decimal("0")
                    pending_slices.append((head, take, False))

            rem_rev_pln = total_revenue_pln_q
            rem_proceeds_orig = gross_proceeds_orig
            rem_sell_comm_orig = sell_comm_orig
            rem_sell_comm_pln = total_sell_comm_pln_q

            for idx, (lot, take, exhausted) in enumerate(pending_slices):
                is_last_slice = idx == len(pending_slices) - 1
                sale_fraction = take / shares

                if exhausted:
                    acq_orig = lot.remaining_principal_orig
                    acq_pln_q = _q2(lot.remaining_principal_pln)
                    b_comm_orig = lot.remaining_buy_comm_orig
                    b_comm_pln_q = _q2(lot.remaining_buy_comm_pln)
                else:
                    lot_fraction = take / lot.remaining_shares
                    acq_orig = (lot.remaining_principal_orig * lot_fraction).quantize(
                        CENT, rounding=ROUND_HALF_UP
                    )
                    acq_pln_q = _q2(lot.remaining_principal_pln * lot_fraction)
                    b_comm_orig = (lot.remaining_buy_comm_orig * lot_fraction).quantize(
                        CENT, rounding=ROUND_HALF_UP
                    )
                    b_comm_pln_q = _q2(lot.remaining_buy_comm_pln * lot_fraction)
                    lot.remaining_shares -= take
                    lot.remaining_principal_orig -= acq_orig
                    lot.remaining_principal_pln -= Decimal(str(acq_pln_q))
                    lot.remaining_buy_comm_orig -= b_comm_orig
                    lot.remaining_buy_comm_pln -= Decimal(str(b_comm_pln_q))

                if is_last_slice:
                    slice_proceeds_orig = rem_proceeds_orig
                    slice_rev_pln = rem_rev_pln
                    slice_s_comm_orig = rem_sell_comm_orig
                    slice_s_comm_pln = rem_sell_comm_pln
                else:
                    slice_proceeds_orig = _q2(gross_proceeds_orig * sale_fraction)
                    slice_rev_pln = _q2(total_revenue_pln_q * sale_fraction)
                    slice_s_comm_orig = _q2(sell_comm_orig * sale_fraction)
                    slice_s_comm_pln = _q2(total_sell_comm_pln_q * sale_fraction)
                    rem_proceeds_orig -= slice_proceeds_orig
                    rem_rev_pln -= slice_rev_pln
                    rem_sell_comm_orig -= slice_s_comm_orig
                    rem_sell_comm_pln -= slice_s_comm_pln

                comm_pln = _q2(b_comm_pln_q + slice_s_comm_pln)
                ded_cost_pln = _q2(acq_pln_q + comm_pln)
                gain_pln = _q2(slice_rev_pln - ded_cost_pln)

                fifo_matches.append(
                    FifoLotMatch(
                        tax_year=tx.timestamp.year,
                        account_id=tx.account_id,
                        symbol=symbol,
                        currency=tx.currency.upper(),
                        buy_tx_id=lot.tx_id,
                        sell_tx_id=tx.id,
                        buy_date=lot.buy_date,
                        sell_date=tx_day.isoformat(),
                        shares=float(take),
                        buy_price_orig=float(lot.unit_price_orig),
                        sell_price_orig=float(sell_unit_price),
                        cost_orig=float(_q2(acq_orig)),
                        proceeds_orig=float(_q2(slice_proceeds_orig)),
                        buy_commission_orig=float(_q2(b_comm_orig)),
                        sell_commission_orig=float(_q2(slice_s_comm_orig)),
                        buy_nbp_rate=float(lot.nbp_rate),
                        buy_nbp_date=lot.nbp_date,
                        sell_nbp_rate=float(nbp.rate),
                        sell_nbp_date=nbp.effective_date,
                        acquisition_cost_pln=float(acq_pln_q),
                        commission_pln=float(comm_pln),
                        deductible_cost_pln=float(ded_cost_pln),
                        revenue_pln=float(slice_rev_pln),
                        gain_loss_pln=float(gain_pln),
                    )
                )

    # Pair withholding_tax rows with dividend rows on (account_id, symbol) within [-2, +7] days
    dividend_txs.sort(key=lambda t: t.timestamp)
    wht_txs.sort(key=lambda t: t.timestamp)
    paired_whts: dict[int, list[Transaction]] = {i: [] for i in range(len(dividend_txs))}

    for wtx in wht_txs:
        best_idx: int | None = None
        best_delta: float | None = None
        for idx, dtx in enumerate(dividend_txs):
            if dtx.account_id != wtx.account_id or (dtx.symbol or "") != (wtx.symbol or ""):
                continue
            day_diff = (wtx.timestamp.date() - dtx.timestamp.date()).days
            if -2 <= day_diff <= 7:
                sec_diff = abs((wtx.timestamp - dtx.timestamp).total_seconds())
                # Prefer a dividend that doesn't already have a negative WHT attached unless this is a refund/adjustment
                already_has_wht = len(paired_whts[idx]) > 0 and wtx.amount < 0
                score = sec_diff + (86400 * 10 if already_has_wht else 0)
                if best_delta is None or score < best_delta:
                    best_delta = score
                    best_idx = idx
        if best_idx is not None:
            paired_whts[best_idx].append(wtx)

    dividend_entries: list[DividendTaxEntry] = []
    for idx, dtx in enumerate(dividend_txs):
        div_nbp = lookup_nbp_d_minus_1_rate(
            dtx.currency,
            dtx.timestamp,
            fx_df,
            allow_boundary_fallback=allow_boundary_fallback,
        )
        gross_orig = dtx.amount
        gross_pln = _q2(gross_orig * div_nbp.rate)
        pl_tax_19 = _q2(gross_pln * PIT38_TAX_RATE)

        attached = paired_whts[idx]
        wht_orig_net = Decimal("0.00")
        wht_pln_net = Decimal("0.00")
        wht_nbp_rate = div_nbp.rate
        wht_nbp_date = div_nbp.effective_date

        for wtx in attached:
            w_nbp = lookup_nbp_d_minus_1_rate(
                wtx.currency,
                wtx.timestamp,
                fx_df,
                allow_boundary_fallback=allow_boundary_fallback,
            )
            # Negative wtx.amount means tax withheld; positive wtx.amount means WHT refund/reversal
            signed_tax_orig = -wtx.amount
            wht_orig_net += signed_tax_orig
            wht_pln_net += signed_tax_orig * w_nbp.rate
            wht_nbp_rate = w_nbp.rate
            wht_nbp_date = w_nbp.effective_date

        wht_orig_q = max(Decimal("0.00"), _q2(wht_orig_net))
        wht_paid_pln = max(Decimal("0.00"), _q2(wht_pln_net))
        # Foreign WHT credit capped at 19% Polish flat tax per dividend payment (Art. 30a ust. 9 PIT)
        wht_credit_pln = min(wht_paid_pln, pl_tax_19)
        tax_due_pln = max(Decimal("0.00"), _q2(pl_tax_19 - wht_credit_pln))
        eff_wht_pct = float(wht_orig_q / gross_orig * 100) if gross_orig > 0 else 0.0

        dividend_entries.append(
            DividendTaxEntry(
                tax_year=dtx.timestamp.year,
                account_id=dtx.account_id,
                symbol=dtx.symbol or "—",
                currency=dtx.currency.upper(),
                tx_id=dtx.id,
                date=dtx.timestamp.date().isoformat(),
                gross_orig=float(_q2(gross_orig)),
                wht_orig=float(wht_orig_q),
                wht_rate_pct=round(eff_wht_pct, 2),
                nbp_rate=float(div_nbp.rate),
                nbp_date=div_nbp.effective_date,
                wht_nbp_rate=float(wht_nbp_rate),
                wht_nbp_date=wht_nbp_date,
                gross_pln=float(gross_pln),
                wht_paid_pln=float(wht_paid_pln),
                polish_tax_19_pln=float(pl_tax_19),
                wht_credit_pln=float(wht_credit_pln),
                tax_due_pln=float(tax_due_pln),
            )
        )

    min_yr = min(tx.timestamp.year for tx in all_txs)
    max_tx_date = max(tx.timestamp.date() for tx in all_txs)
    ref_end_date = pd.Timestamp(last_date).date() if last_date is not None else max_tx_date
    max_yr = max(max_tx_date.year, ref_end_date.year)
    available_years = list(range(max_yr, min_yr - 1, -1))
    current_cal_year = int(warsaw_today().year)

    by_year: dict[int, Pit38YearSummary] = {}
    for yr in available_years:
        yr_matches = [m for m in fifo_matches if m.tax_year == yr]
        yr_divs = [d for d in dividend_entries if d.tax_year == yr]
        yr_comm = standalone_comm_by_year.get(yr, Decimal("0.00"))
        is_ytd = (
            yr == max_yr
            and ref_end_date < date(yr, 12, 31)
            and (last_date is not None or yr >= current_cal_year)
        )
        by_year[yr] = _build_summary(yr, is_ytd, yr_matches, yr_comm, yr_divs)

    total_standalone_comm = sum(standalone_comm_by_year.values(), Decimal("0.00"))
    all_years_summary = _build_summary(
        0, False, fifo_matches, total_standalone_comm, dividend_entries
    )
    remaining_open_lots = sum(len(v) for v in open_lots.values())

    return Pit38Report(
        available_years=available_years,
        latest_year=available_years[0] if available_years else None,
        by_year=by_year,
        all_years_summary=all_years_summary,
        fifo_matches=fifo_matches,
        dividends=dividend_entries,
        open_lots_count=remaining_open_lots,
    )


def compute_trade_stats(pit38: Pit38Report) -> dict[str, object]:
    """Compute closed-lot win rate and profit factor from FIFO lot matches."""
    matches = pit38.fifo_matches
    total = len(matches)
    if total == 0:
        return {
            "closed_lots": 0,
            "winning_lots": 0,
            "losing_lots": 0,
            "win_rate": None,
            "profit_factor": None,
        }
    wins = [m.gain_loss_pln for m in matches if m.gain_loss_pln > 0]
    losses = [m.gain_loss_pln for m in matches if m.gain_loss_pln < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = len(wins) / total
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    return {
        "closed_lots": total,
        "winning_lots": len(wins),
        "losing_lots": len(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
    }
