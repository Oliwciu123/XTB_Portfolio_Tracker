"""Unit and regression tests for Polish PIT-38 FIFO tax, D-1 NBP Table A rates, and dividends."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.tax import (
    compute_pit38_report,
    compute_trade_stats,
    lookup_nbp_d_minus_1_rate,
)


def _tx(
    tx_id: str,
    account_id: str,
    currency: str,
    tx_type: str,
    ts: str,
    amount: float | str,
    *,
    symbol: str | None = None,
    shares: float | str | None = None,
    price: float | str | None = None,
    comment: str = "",
    commission: float | str | None = None,
    raw_type: str = "",
) -> Transaction:
    return Transaction(
        id=tx_id,
        account_id=account_id,
        currency=currency,
        type=tx_type,  # type: ignore[arg-type]
        timestamp=datetime.fromisoformat(ts),
        symbol=symbol,
        amount=Decimal(str(amount)),
        shares=Decimal(str(shares)) if shares is not None else None,
        price=Decimal(str(price)) if price is not None else None,
        comment=comment,
        commission=Decimal(str(commission)) if commission is not None else None,
        raw_type=raw_type,
    )


def test_nbp_d_minus_1_lookback_across_weekends_and_polish_holidays():
    """Transactions on Monday after May 1 & May 3 holidays must use Apr 30 NBP Table A rate."""
    # NBP publishes Table A on Thu 2026-04-30 (3.9500) and Mon 2026-05-04 (4.0500).
    # Fri 2026-05-01 is Labour Day (no NBP table), Sat May 2 & Sun May 3 are weekend.
    nbp_dates = pd.to_datetime(["2026-04-29", "2026-04-30", "2026-05-04", "2026-05-05"])
    fx = pd.DataFrame(
        {
            "USDPLN": [3.9100, 3.9500, 4.0500, 4.0800],
            "EURPLN": [4.2500, 4.3000, 4.3600, 4.3900],
        },
        index=nbp_dates,
    )

    # Monday May 4 -> skips Sun May 3, Sat May 2, Fri May 1 -> Thu Apr 30
    mon_lookup = lookup_nbp_d_minus_1_rate("USD", "2026-05-04 15:35:00", fx)
    assert mon_lookup.rate == Decimal("3.95")
    assert mon_lookup.effective_date == "2026-04-30"

    # Saturday May 2 -> skips Fri May 1 -> Thu Apr 30
    sat_lookup = lookup_nbp_d_minus_1_rate("EUR", "2026-05-02 10:00:00", fx)
    assert sat_lookup.rate == Decimal("4.3")
    assert sat_lookup.effective_date == "2026-04-30"

    # Tuesday May 5 -> uses Monday May 4
    tue_lookup = lookup_nbp_d_minus_1_rate("USD", "2026-05-05 16:00:00", fx)
    assert tue_lookup.rate == Decimal("4.05")
    assert tue_lookup.effective_date == "2026-05-04"

    # PLN transactions always use 1:1
    pln_lookup = lookup_nbp_d_minus_1_rate("PLN", "2026-05-04", fx)
    assert pln_lookup.rate == Decimal("1")

    # Missing preceding NBP rate raises ValueError in strict mode
    with pytest.raises(ValueError, match="No NBP Table A mid rate"):
        lookup_nbp_d_minus_1_rate("USD", "2026-04-29", fx)


def test_fifo_partial_lot_splits_across_multiple_years_with_commissions():
    """Partial FIFO sales consume oldest lots first, pro-rate buy commissions, and preserve remainders."""
    fx = pd.DataFrame(
        {
            "USDPLN": [4.0000, 3.9000, 4.1000, 4.2000],
            "EURPLN": [4.3000, 4.3000, 4.4000, 4.5000],
        },
        index=pd.to_datetime(["2024-01-09", "2024-03-14", "2025-05-08", "2026-02-10"]),
    )

    usd_acc = Account(
        account_id="usd-1",
        currency="USD",
        transactions=[
            # Lot 1 on 2024-01-10 (D-1 = 2024-01-09 @ 4.00): 10 sh @ $100 + $5 buy comm = $1005
            _tx(
                "b1",
                "usd-1",
                "USD",
                "buy",
                "2024-01-10 15:30:00",
                "-1005.00",
                symbol="AAPL.US",
                shares=10,
                price=100,
            ),
            # Lot 2 on 2024-03-15 (D-1 = 2024-03-14 @ 3.90): 10 sh @ $120 + $4 buy comm = $1204
            _tx(
                "b2",
                "usd-1",
                "USD",
                "buy",
                "2024-03-15 15:30:00",
                "-1204.00",
                symbol="AAPL.US",
                shares=10,
                price=120,
            ),
            # Sale 1 on 2025-05-09 (D-1 = 2025-05-08 @ 4.10): 14 sh @ $150 ($2100 gross), $7 sell comm -> $2093 net
            _tx(
                "s1",
                "usd-1",
                "USD",
                "sell",
                "2025-05-09 16:00:00",
                "2093.00",
                symbol="AAPL.US",
                shares=14,
                price=150,
            ),
            # Sale 2 on 2026-02-11 (D-1 = 2026-02-10 @ 4.20): remaining 6 sh @ $140 ($840 gross), $3 explicit comm
            _tx(
                "s2",
                "usd-1",
                "USD",
                "sell",
                "2026-02-11 16:00:00",
                "840.00",
                symbol="AAPL.US",
                shares=6,
                price=140,
                commission="3.00",
            ),
        ],
    )

    report = compute_pit38_report([usd_acc], fx=fx)
    assert report.open_lots_count == 0
    assert len(report.fifo_matches) == 3

    # Match 1 (2025): all 10 shares of Lot 1
    # Revenue: 10 * 150 * 4.10 = 6150.00 PLN
    # Acq cost: 1000 * 4.00 = 4000.00 PLN
    # Buy comm: 5 * 4.00 = 20.00 PLN; Sell comm (10/14 of $7 * 4.10 = 28.70): 20.50 PLN -> total comm 40.50 PLN
    m1, m2, m3 = report.fifo_matches
    assert m1.tax_year == 2025
    assert m1.shares == pytest.approx(10.0)
    assert m1.buy_nbp_date == "2024-01-09"
    assert m1.sell_nbp_date == "2025-05-08"
    assert m1.revenue_pln == pytest.approx(6150.00)
    assert m1.acquisition_cost_pln == pytest.approx(4000.00)
    assert m1.commission_pln == pytest.approx(40.50)
    assert m1.deductible_cost_pln == pytest.approx(4040.50)

    # Match 2 (2025): 4 shares sliced from Lot 2 (4/10 of $1200 * 3.90 = 1872.00 PLN; 4/10 of $4 * 3.90 = 6.24 PLN)
    # Sell comm remainder: 28.70 - 20.50 = 8.20 PLN -> total comm = 6.24 + 8.20 = 14.44 PLN
    assert m2.tax_year == 2025
    assert m2.shares == pytest.approx(4.0)
    assert m2.revenue_pln == pytest.approx(2460.00)
    assert m2.acquisition_cost_pln == pytest.approx(1872.00)
    assert m2.commission_pln == pytest.approx(14.44)

    y2025 = report.by_year[2025]
    assert y2025.section_c_revenue_pln == pytest.approx(8610.00)
    assert y2025.section_c_costs_pln == pytest.approx(5926.94)
    assert y2025.section_c_income_pln == pytest.approx(2683.06)
    assert y2025.section_c_tax_pln == pytest.approx(round(2683.06 * 0.19, 2))
    assert y2025.section_c_tax_base_rounded_pln == 2683
    assert y2025.section_c_tax_rounded_pln == round(2683 * 0.19)

    # Match 3 (2026): remaining 6 shares of Lot 2 -> exact remaining acq cost = 4680 - 1872 = 2808.00 PLN
    # Remaining buy comm = 15.60 - 6.24 = 9.36 PLN + sell comm ($3 * 4.20 = 12.60 PLN) = 21.96 PLN
    assert m3.tax_year == 2026
    assert m3.shares == pytest.approx(6.0)
    assert m3.acquisition_cost_pln == pytest.approx(2808.00)
    assert m3.commission_pln == pytest.approx(21.96)
    assert m3.revenue_pln == pytest.approx(840.0 * 4.20)


def test_separate_commission_rows_and_legacy_close_trade_rows():
    """Standalone XTB Commission rows and split Stock sell + Close trade rows settle accurately."""
    fx = pd.DataFrame(
        {"USDPLN": [4.0000, 4.1000], "EURPLN": [4.3000, 4.4000]},
        index=pd.to_datetime(["2025-01-02", "2025-02-03"]),
    )
    acc = Account(
        account_id="legacy-usd",
        currency="USD",
        transactions=[
            _tx(
                "1",
                "legacy-usd",
                "USD",
                "buy",
                "2025-01-03 10:00:00",
                "-100.00",
                symbol="MSFT.US",
                shares=1,
                price=100,
            ),
            _tx(
                "2",
                "legacy-usd",
                "USD",
                "other",
                "2025-01-03 10:00:01",
                "-2.00",
                symbol="MSFT.US",
                raw_type="Commission",
                comment="Brokerage commission",
            ),
            # Legacy XTB split: Stock sell records returned cost (50.00), Close trade records profit (+10.00)
            _tx(
                "3",
                "legacy-usd",
                "USD",
                "sell",
                "2025-02-04 14:00:00",
                "50.00",
                symbol="MSFT.US",
                shares=0.5,
                price=120,
            ),
            _tx(
                "4",
                "legacy-usd",
                "USD",
                "close_trade",
                "2025-02-04 14:00:00",
                "10.00",
                symbol="MSFT.US",
            ),
            _tx(
                "5",
                "legacy-usd",
                "USD",
                "other",
                "2025-02-04 14:00:01",
                "-1.50",
                symbol="MSFT.US",
                raw_type="Sec fee",
                comment="SEC fee",
            ),
        ],
    )
    pit = compute_pit38_report([acc], fx=fx)
    assert len(pit.fifo_matches) == 1
    m = pit.fifo_matches[0]
    # Proceeds: 0.5 * $120 = $60 * 4.10 = 246.00 PLN (not $50!)
    assert m.proceeds_orig == pytest.approx(60.00)
    assert m.revenue_pln == pytest.approx(246.00)
    # Acq cost: 0.5 * $100 * 4.00 = 200.00 PLN
    # Commissions: 0.5 * ($2 * 4.00) + ($1.50 * 4.10) = 4.00 + 6.15 = 10.15 PLN
    assert m.acquisition_cost_pln == pytest.approx(200.00)
    assert m.commission_pln == pytest.approx(10.15)
    assert m.gain_loss_pln == pytest.approx(35.85)


def test_loss_year_and_dividend_wht_credit_cap_across_currencies():
    """Section C losses yield 0 PLN Section C tax without offsetting dividends; >19% WHT caps at 19%."""
    fx = pd.DataFrame(
        {
            "USDPLN": [4.0000, 3.8000],
            "EURPLN": [4.4000, 4.3000],
        },
        index=pd.to_datetime(["2025-03-10", "2025-06-10"]),
    )

    usd_acc = Account(
        account_id="u1",
        currency="USD",
        transactions=[
            # Buy 10 @ $100 (D-1 = 4.00 -> 4000 PLN), sell 10 @ $90 (D-1 = 3.80 -> 3420 PLN) => -580 PLN loss
            _tx(
                "u-b",
                "u1",
                "USD",
                "buy",
                "2025-03-11 15:00:00",
                "-1000.00",
                symbol="AMD.US",
                shares=10,
                price=100,
            ),
            _tx(
                "u-s",
                "u1",
                "USD",
                "sell",
                "2025-06-11 15:00:00",
                "900.00",
                symbol="AMD.US",
                shares=10,
                price=90,
            ),
            # US Dividend $100 on 2025-06-11 (D-1 = 3.80 -> 380.00 PLN gross; 19% = 72.20 PLN)
            # 15% WHT = -$15 (57.00 PLN) -> Polish tax due = 72.20 - 57.00 = 15.20 PLN (4%)
            _tx("u-d", "u1", "USD", "dividend", "2025-06-11 12:00:00", "100.00", symbol="KO.US"),
            _tx(
                "u-w",
                "u1",
                "USD",
                "withholding_tax",
                "2025-06-11 12:01:00",
                "-15.00",
                symbol="KO.US",
            ),
        ],
    )
    eur_acc = Account(
        account_id="e1",
        currency="EUR",
        transactions=[
            # German Dividend €100 on 2025-06-11 (D-1 = 4.30 -> 430.00 PLN gross; 19% = 81.70 PLN)
            # German 26.38% WHT = -€26.38 (113.43 PLN) -> credit MUST cap at 81.70 PLN, 0 PLN due,
            # and excess 31.73 PLN German tax MUST NOT reduce the 15.20 PLN owed on the US dividend!
            _tx("e-d", "e1", "EUR", "dividend", "2025-06-11 13:00:00", "100.00", symbol="SAP.DE"),
            _tx(
                "e-w",
                "e1",
                "EUR",
                "withholding_tax",
                "2025-06-11 13:01:00",
                "-26.38",
                symbol="SAP.DE",
            ),
            # Zero-WHT ETF Dividend €50 on 2025-06-11 (D-1 = 4.30 -> 215.00 PLN gross; 19% = 40.85 PLN due)
            _tx("e-d2", "e1", "EUR", "dividend", "2025-06-11 14:00:00", "50.00", symbol="VUSA.DE"),
        ],
    )

    pit = compute_pit38_report([usd_acc, eur_acc], fx=fx)
    y2025 = pit.by_year[2025]

    assert y2025.section_c_revenue_pln == pytest.approx(3420.00)
    assert y2025.section_c_costs_pln == pytest.approx(4000.00)
    assert y2025.section_c_income_pln == 0.0
    assert y2025.section_c_loss_pln == pytest.approx(580.00)
    assert y2025.section_c_tax_pln == 0.0

    assert y2025.dividends_count == 3
    assert y2025.dividends_gross_pln == pytest.approx(380.00 + 430.00 + 215.00)
    assert y2025.dividends_wht_paid_pln == pytest.approx(57.00 + 113.43)
    # Credited WHT = 57.00 (US) + 81.70 (DE capped at 19%!) + 0.00 (ETF) = 138.70 PLN
    assert y2025.dividends_wht_credit_pln == pytest.approx(138.70)
    # Net dividend tax to pay = 15.20 (US 4%) + 0.00 (DE) + 40.85 (ETF 19%) = 56.05 PLN
    assert y2025.dividends_tax_due_pln == pytest.approx(56.05)
    # Section C loss (-580 PLN) does not offset Section G dividend tax (56.05 PLN)
    assert y2025.total_tax_due_pln == pytest.approx(56.05)


def test_fifo_preserves_cost_basis_across_stock_splits():
    """A 2-for-1 stock split doubles FIFO lot shares while preserving original D-1 PLN cost basis."""
    fx = pd.DataFrame(
        {"USDPLN": [4.0000, 4.2000], "EURPLN": [4.3000, 4.4000]},
        index=pd.to_datetime(["2025-01-09", "2025-06-09"]),
    )
    acc = Account(
        account_id="u1",
        currency="USD",
        transactions=[
            # Buy 5 shares @ $200 = $1000 (4000 PLN at 4.00)
            _tx(
                "b1",
                "u1",
                "USD",
                "buy",
                "2025-01-10 15:00:00",
                "-1000.00",
                symbol="NVDA.US",
                shares=5,
                price=200,
            ),
            # After 2:1 split on 2025-03-01, lot holds 10 shares @ $100 cost basis; sell 6 shares @ $130
            _tx(
                "s1",
                "u1",
                "USD",
                "sell",
                "2025-06-10 15:00:00",
                "780.00",
                symbol="NVDA.US",
                shares=6,
                price=130,
            ),
        ],
    )
    pit = compute_pit38_report([acc], fx=fx, splits={"NVDA.US": {"2025-03-01": 2.0}})
    assert len(pit.fifo_matches) == 1
    m = pit.fifo_matches[0]
    assert m.shares == pytest.approx(6.0)
    # 6 out of 10 post-split shares = 60% of 4000 PLN = 2400.00 PLN cost basis
    assert m.acquisition_cost_pln == pytest.approx(2400.00)
    assert m.revenue_pln == pytest.approx(780.0 * 4.20)
    stats = compute_trade_stats(pit)
    assert stats["win_rate"] == 1.0
    assert stats["profit_factor"] is None  # zero losing trades


def test_split_on_first_purchase_day_does_not_double_split_post_split_lot():
    """Regression: a lot purchased ON the split effective date is already post-split."""
    fx = pd.DataFrame(
        {"USDPLN": [4.0000, 4.1000], "EURPLN": [4.3000, 4.4000]},
        index=pd.to_datetime(["2025-02-28", "2025-06-09"]),
    )
    acc = Account(
        account_id="u1",
        currency="USD",
        transactions=[
            _tx(
                "b-on-split",
                "u1",
                "USD",
                "buy",
                "2025-03-03 15:00:00",
                "-1000.00",
                symbol="NVDA.US",
                shares=10,
                price=100,
            ),
            _tx(
                "s-later",
                "u1",
                "USD",
                "sell",
                "2025-06-10 15:00:00",
                "1200.00",
                symbol="NVDA.US",
                shares=10,
                price=120,
            ),
        ],
    )
    pit = compute_pit38_report([acc], fx=fx, splits={"NVDA.US": {"2025-03-03": 2.0}})
    assert pit.open_lots_count == 0
    assert len(pit.fifo_matches) == 1
    assert pit.fifo_matches[0].acquisition_cost_pln == pytest.approx(4000.00)
    # 2025 is a completed prior calendar year relative to 2026
    assert pit.by_year[2025].is_ytd is False


def test_early_january_fx_cache_requires_prior_year_d_minus_1_lookback(tmp_path, monkeypatch):
    """Regression: cache starting on Jan 2 must refresh to fetch Dec 29 D-1 NBP rate."""
    from xtb_analyzer import fx as fx_mod

    monkeypatch.setattr(fx_mod, "CACHE_DIR", tmp_path)
    stale_cache = pd.DataFrame(
        {"USDPLN": [3.99], "EURPLN": [4.34], "EURUSD": [4.34 / 3.99], "USDEUR": [3.99 / 4.34]},
        index=pd.to_datetime(["2024-01-02"]),
    )
    stale_cache.to_parquet(tmp_path / "fx_rates_v3.parquet")

    full_dates = pd.to_datetime(["2023-12-22", "2023-12-29", "2024-01-02", "2024-01-03"])
    monkeypatch.setattr(
        fx_mod,
        "_nbp_series",
        lambda code, start, end=None: pd.Series(
            [3.92, 3.9350, 3.98, 3.99] if code.lower() == "usd" else [4.31, 4.3480, 4.35, 4.36],
            index=full_dates,
            name=f"{code.upper()}PLN",
        ),
    )

    loaded = fx_mod.fetch_fx_rates(start="2024-01-02", end="2024-01-04", use_cache=True)
    jan2_nbp = lookup_nbp_d_minus_1_rate("USD", "2024-01-02 10:00:00", loaded)
    assert jan2_nbp.effective_date == "2023-12-29"
    assert jan2_nbp.rate == Decimal("3.935")


def test_eurozone_xtb_suffixes_and_direct_pln_cash_ledger():
    """Verify Eurozone XTB ticker mappings and direct PLN bank deposits in CashLedger."""
    from xtb_analyzer.cash import build_cash_ledger
    from xtb_analyzer.prices import xtb_to_yahoo

    assert xtb_to_yahoo("ASML.NL") == "ASML.AS"
    assert xtb_to_yahoo("MC.FR") == "MC.PA"
    assert xtb_to_yahoo("SAN.ES") == "SAN.MC"
    assert xtb_to_yahoo("ENI.IT") == "ENI.MI"

    pln_acc = Account(
        account_id="pln-direct",
        currency="PLN",
        transactions=[
            _tx("d1", "pln-direct", "PLN", "transfer_in", "2025-04-10 09:00:00", "2500.00"),
        ],
    )
    ledger = build_cash_ledger([pln_acc])
    assert ledger.deposits_pln == Decimal("2500.00")
