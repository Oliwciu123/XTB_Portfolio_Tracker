"""Independent arithmetic cases, with no market API or private account dependency."""

from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from xtb_analyzer.benchmark import benchmark_in_currency, build_deposit_benchmark
from xtb_analyzer.flows import build_cumulative_deposits, extract_deposits
from xtb_analyzer.fx import convert_value
from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.returns import CashFlow, compute_return_measures, xirr
from xtb_analyzer.risk import _sortino, drawdown_from_returns


def tx(code, currency, amount, kind, day="2026-10-20", comment="", symbol=None, shares=None):
    return Transaction(
        code,
        code,
        currency,
        kind,
        datetime.fromisoformat(day),
        symbol,
        Decimal(str(amount)),
        Decimal(str(shares)) if shares else None,
        comment=comment,
    )


@pytest.fixture
def fx():
    return pd.DataFrame(
        {
            "USDPLN": [4, 4.1, 4.2],
            "EURPLN": [4.4, 4.51, 4.62],
            "EURUSD": [1.1] * 3,
            "USDEUR": [1 / 1.1] * 3,
        },
        index=pd.date_range("2026-10-20", periods=3),
    )


def test_deposits_withdrawals_and_internal_conversions(fx):
    pln = Account(
        "pln",
        "PLN",
        transactions=[
            tx("pln", "PLN", 4000, "transfer_in"),
            tx(
                "pln",
                "PLN",
                -4000,
                "transfer_in",
                comment="Currency conversion, PLN to USD, Exchange rate:0.25",
            ),
        ],
    )
    usd = Account(
        "usd",
        "USD",
        transactions=[
            tx(
                "usd",
                "USD",
                1000,
                "transfer_in",
                comment="Currency conversion, PLN to USD, Exchange rate:0.25",
            ),
            tx("usd", "USD", -100, "transfer_out", "2026-10-22"),
        ],
    )
    deposits = extract_deposits([pln, usd], fx=fx)
    assert [float(d.pln_spent) for d in deposits] == [4000, -420]
    capital = build_cumulative_deposits(deposits, fx.index, fx)
    assert capital.deposits_pln.iloc[-1] == 3580
    assert capital.gross_deposits_pln.iloc[-1] == 4000
    assert capital.withdrawals_pln.iloc[-1] == 420


def test_roi_after_full_withdrawal_uses_gross_capital(fx):
    account = Account(
        "a",
        "PLN",
        transactions=[
            tx("a", "PLN", 1000, "transfer_in"),
            tx("a", "PLN", -1100, "transfer_out", "2026-10-22"),
        ],
    )
    nav = build_cumulative_deposits(extract_deposits([account]), fx.index, fx)
    nav["nav_pln"] = [1000, 1100, 0]
    result = compute_return_measures([account], nav, fx=fx)
    assert result.gain == pytest.approx(100)
    assert result.roi == pytest.approx(0.10)
    assert result.invested == 1000
    assert result.withdrawn == 1100


def test_benchmark_preserves_currency_exposure_and_cost(fx):
    account = Account(
        "a",
        "USD",
        transactions=[
            tx(
                "a",
                "USD",
                1000,
                "transfer_in",
                comment="Currency conversion, PLN to USD, Exchange rate:0.25",
            )
        ],
    )
    index = pd.Series([100, 100, 100], index=fx.index)
    result = build_deposit_benchmark([account], fx.index, currency="pln", index_series=index, fx=fx)
    assert result.tolist() == pytest.approx([4000, 4100, 4200])
    assert benchmark_in_currency(index, "EUR", "usd", fx).tolist() == pytest.approx([110] * 3)


def test_benchmark_rejects_history_starting_after_deposit(fx):
    account = Account("a", "PLN", transactions=[tx("a", "PLN", 1000, "transfer_in")])
    result = build_deposit_benchmark(
        [account], fx.index, index_series=pd.Series([10, 11], index=fx.index[1:]), fx=fx
    )
    assert result.empty


def test_no_fake_or_recursive_fx():
    with pytest.raises(ValueError, match="exchange rate"):
        convert_value(100, "USD", "PLN", pd.Series(dtype=float))


def test_sortino_uses_all_observations_and_zero_target():
    returns = pd.Series([0.02, -0.01, 0.03, -0.02])
    expected = np.sqrt(252) * 0.005 / np.sqrt((0.01**2 + 0.02**2) / 4)
    assert _sortino(returns) == pytest.approx(expected)


def test_initial_loss_is_drawdown():
    returns = pd.Series([-0.1, 0.01], index=pd.date_range("2026-01-01", periods=2))
    assert drawdown_from_returns(returns).iloc[0] == pytest.approx(-0.1)


def test_same_day_xirr_is_undefined():
    day = pd.Timestamp("2026-01-01")
    assert xirr([CashFlow(day, -100), CashFlow(day, 110)]) is None


def test_actual_prices_and_split_reconstruction(monkeypatch, fx):
    from xtb_analyzer.portfolio import build_nav_series

    account = Account(
        "a",
        "USD",
        transactions=[
            tx(
                "a",
                "USD",
                1000,
                "transfer_in",
                comment="Currency conversion, PLN to USD, Exchange rate:0.25",
            ),
            tx("a", "USD", -1000, "buy", symbol="EX.US", shares=10),
            tx("a", "USD", 20, "dividend", "2026-10-21", symbol="EX.US"),
            tx("a", "USD", 275, "sell", "2026-10-22", symbol="EX.US", shares=5),
        ],
    )
    prices = pd.DataFrame({"EX.US": [100, 50, 55]}, index=fx.index)
    prices.attrs["splits"] = {"EX.US": {"2026-10-21": 2}}
    monkeypatch.setattr("xtb_analyzer.portfolio.fetch_prices", lambda *a, **kw: prices)
    nav, _, positions = build_nav_series([account], fx=fx)
    assert nav.nav_usd.tolist() == pytest.approx([1000, 1020, 1120])
    assert positions.shares.iloc[0] == 15
    assert positions.cost_basis.iloc[0] == 750
    assert positions.unrealized_pnl.iloc[0] == 75


def test_spot_history_undoes_yahoo_split_adjustment():
    from xtb_analyzer.prices import _extract_close

    frame = pd.DataFrame(
        {"Close": [50, 50, 55], "Stock Splits": [0, 2, 0]},
        index=pd.date_range("2026-10-20", periods=3),
    )
    spot = _extract_close(frame, "EX", adjusted=False)
    assert spot.tolist() == [100, 50, 55]
    assert spot.attrs["splits"] == {"2026-10-21": 2}


def test_comparison_uses_real_dates_and_same_endpoint():
    from xtb_analyzer.charts import prepare_return_comparison_data

    dates = pd.date_range("2026-10-20", periods=3)
    nav = pd.DataFrame({"nav_pln": [990, 1010, 1100], "deposits_pln": [1000] * 3}, index=dates)
    data = prepare_return_comparison_data(nav, {}, "pln")
    assert data.portfolio_monthly.index[-1] == dates[-1]
    assert data.portfolio_monthly.iloc[0] == pytest.approx(-1)
    assert data.portfolio_monthly.iloc[-1] == pytest.approx(data.final_portfolio)


def test_full_report_and_live_charts_share_financial_snapshot(monkeypatch, fx, tmp_path):
    from xtb_analyzer.report import build_live_payload, collect_report_data, render_html_report

    account = Account(
        "a",
        "USD",
        transactions=[
            tx(
                "a",
                "USD",
                1000,
                "transfer_in",
                comment="Currency conversion, PLN to USD, Exchange rate:0.25",
            ),
            tx("a", "USD", -1000, "buy", symbol="EX.US", shares=10),
        ],
    )
    prices = pd.DataFrame({"EX.US": [100, 100, 110]}, index=fx.index)
    monkeypatch.setattr("xtb_analyzer.report.fetch_fx_rates", lambda **kw: fx)
    monkeypatch.setattr("xtb_analyzer.benchmark.fetch_fx_rates", lambda **kw: fx)
    monkeypatch.setattr("xtb_analyzer.portfolio.fetch_prices", lambda *a, **kw: prices)
    monkeypatch.setattr("xtb_analyzer.report.instrument_currency", lambda ticker: "USD")
    monkeypatch.setattr(
        "xtb_analyzer.report.enrich_positions_with_sectors", lambda p: p.assign(sector="Technology")
    )
    monkeypatch.setattr(
        "xtb_analyzer.report.fetch_benchmarks",
        lambda tickers, **kw: {t: pd.Series([100] * 3, index=fx.index) for t in tickers},
    )
    data = collect_report_data([account], refresh_latest=False)
    assert data.measures.final_value == pytest.approx(4620)
    assert data.measures.gain == pytest.approx(620)
    assert data.measures.roi == pytest.approx(0.155)
    assert data.attribution.total_gain_pln == pytest.approx(620)
    assert data.benchmarks["sp500"].iloc[-1] == pytest.approx(4200)
    report = render_html_report(data)
    live = build_live_payload(data)
    assert len(live["charts"]) == 9
    assert all(f'id="{key}"' in report for key in live["charts"])
    assert '<script src="https://cdn.plot.ly' not in report
    assert "export-bench-csv" in report
    (tmp_path / "report.html").write_text(report, encoding="utf-8")


def test_split_metadata_survives_cache_round_trip(tmp_path):
    from xtb_analyzer.prices import _load_cached_series

    price = pd.Series([100, 50], index=pd.date_range("2026-01-01", periods=2))
    price.attrs["splits"] = {"2026-01-02": 2}
    file = tmp_path / "price.parquet"
    price.to_frame("close").to_parquet(file)
    assert _load_cached_series(file).attrs["splits"] == {"2026-01-02": 2}


def test_internal_fx_transfers_move_capital_basis(fx):
    from xtb_analyzer.attribution import compute_fx_attribution

    comment = "Currency conversion, PLN to USD, Exchange rate:0.25"
    pln = Account(
        "pln",
        "PLN",
        transactions=[
            tx("pln", "PLN", 4000, "transfer_in"),
            tx("pln", "PLN", -4000, "transfer_in", comment=comment),
        ],
    )
    usd = Account(
        "usd", "USD", transactions=[tx("usd", "USD", 1000, "transfer_in", comment=comment)]
    )
    nav = pd.DataFrame(
        {
            "local_pln": [0] * 3,
            "local_usd": [1000] * 3,
            "local_eur": [0] * 3,
            "deposits_pln": [4000] * 3,
        },
        index=fx.index,
    )
    result = compute_fx_attribution([pln, usd], nav, fx=fx)
    assert result.total_gain_pln == pytest.approx(200)
    assert result.fx_gain_pln == pytest.approx(200)
    assert result.investment_gain_pln == pytest.approx(0)


def test_cash_only_portfolio_can_be_valued(monkeypatch, fx):
    from xtb_analyzer.portfolio import build_nav_series

    account = Account("a", "PLN", transactions=[tx("a", "PLN", 1000, "transfer_in")])
    monkeypatch.setattr("xtb_analyzer.portfolio.fetch_prices", lambda *a, **kw: pd.DataFrame())
    nav, _, positions = build_nav_series([account], fx=fx)
    assert nav.nav_pln.tolist() == [1000] * 3
    assert positions.empty


def test_missing_batched_ticker_is_not_replaced_by_another_stock():
    from xtb_analyzer.prices import _extract_close

    data = pd.DataFrame({("Close", "AAPL"): [100]}, index=[pd.Timestamp("2026-01-01")])
    assert _extract_close(data, "MSFT").empty
