from datetime import datetime

import pandas as pd
import pytest

from xtb_analyzer.returns import CashFlow, twr_daily_returns, xirr


def test_xirr_single_year_gain():
    flows = [
        CashFlow(date=pd.Timestamp("2024-01-01"), amount=-1000.0),
        CashFlow(date=pd.Timestamp("2025-01-01"), amount=1100.0),
    ]
    result = xirr(flows)
    assert result is not None
    # 366 days => slightly more than one 365.25-day year, so a bit below 10%
    assert result == pytest.approx(0.0998, abs=2e-3)


def test_xirr_zero_return():
    flows = [
        CashFlow(date=pd.Timestamp("2024-01-01"), amount=-1000.0),
        CashFlow(date=pd.Timestamp("2024-07-01"), amount=1000.0),
    ]
    assert xirr(flows) == pytest.approx(0.0, abs=1e-6)


def test_xirr_solution_zeroes_npv():
    flows = [
        CashFlow(date=pd.Timestamp("2024-01-01"), amount=-1000.0),
        CashFlow(date=pd.Timestamp("2024-06-01"), amount=-500.0),
        CashFlow(date=pd.Timestamp("2025-01-01"), amount=1700.0),
    ]
    rate = xirr(flows)
    assert rate is not None
    t0 = flows[0].date
    npv = sum(f.amount / (1 + rate) ** ((f.date - t0).days / 365.25) for f in flows)
    assert npv == pytest.approx(0.0, abs=1e-4)


def test_xirr_requires_both_signs():
    flows = [
        CashFlow(date=pd.Timestamp("2024-01-01"), amount=-1000.0),
        CashFlow(date=pd.Timestamp("2025-01-01"), amount=-100.0),
    ]
    assert xirr(flows) is None


def test_twr_neutralizes_deposits():
    index = pd.DatetimeIndex([datetime(2024, 1, 1), datetime(2024, 1, 2), datetime(2024, 1, 3)])
    nav = pd.DataFrame(
        {
            "nav_pln": [1000.0, 1100.0, 2310.0],
            "deposits_pln": [1000.0, 1000.0, 2000.0],
        },
        index=index,
    )
    daily = twr_daily_returns(nav, "pln")
    assert daily.iloc[0] == pytest.approx(0.0)
    assert daily.iloc[1] == pytest.approx(0.10)
    # Day 3: 1000 deposited at start of day, then +10% on 2100
    assert daily.iloc[2] == pytest.approx(0.10)

    twr_total = float((1 + daily).prod() - 1)
    assert twr_total == pytest.approx(0.21)

    roi = nav["nav_pln"].iloc[-1] / nav["deposits_pln"].iloc[-1] - 1
    assert roi == pytest.approx(0.155)
    assert twr_total > roi  # late deposit dilutes ROI but not TWR


def test_twr_starts_at_first_deposit():
    index = pd.date_range("2024-01-01", periods=4, freq="D")
    nav = pd.DataFrame(
        {
            "nav_pln": [0.0, 0.0, 1000.0, 1050.0],
            "deposits_pln": [0.0, 0.0, 1000.0, 1000.0],
        },
        index=index,
    )
    daily = twr_daily_returns(nav, "pln")
    assert len(daily) == 2
    assert daily.iloc[-1] == pytest.approx(0.05)


def test_legacy_metrics_roi_preserves_profit_after_full_withdrawal(monkeypatch):
    from xtb_analyzer.metrics import compute_metrics

    monkeypatch.setattr("xtb_analyzer.metrics._benchmark_stats", lambda *a: (None, None, None))
    nav = pd.DataFrame(
        {
            "nav_pln": [1000, 1100, 0],
            "deposits_pln": [1000, 1000, -100],
            "gross_deposits_pln": [1000, 1000, 1000],
        },
        index=pd.date_range("2024-01-01", periods=3),
    )
    result = compute_metrics(nav, "pln", refresh_latest=False)
    assert result.total_return == pytest.approx(0.1)
    assert result.gain == pytest.approx(100)
