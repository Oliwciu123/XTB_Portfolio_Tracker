import pandas as pd

from xtb_analyzer.charts import build_return_comparison_figure, prepare_return_comparison_data


def _sample_nav() -> pd.DataFrame:
    dates = pd.date_range("2025-11-01", periods=6, freq="ME")
    deposits = [1000, 2000, 3000, 4000, 5000, 6000]
    nav = [1000, 2100, 3300, 4200, 5500, 6500]
    return pd.DataFrame(
        {
            "nav_pln": nav,
            "deposits_pln": deposits,
            "return_pln": [v / d - 1 for v, d in zip(nav, deposits, strict=False)],
        },
        index=dates,
    )


def _sample_benchmarks(nav: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "sp500": nav["deposits_pln"] * 1.05,
        "nasdaq100": nav["deposits_pln"] * 1.08,
        "acwi": nav["deposits_pln"] * 1.03,
    }


def test_build_return_comparison_figure_has_all_traces():
    nav = _sample_nav()
    fig = build_return_comparison_figure(nav, _sample_benchmarks(nav), "pln")
    assert len(fig.data) == 4  # portfolio + 3 benchmarks
    assert all(trace.visible is True for trace in fig.data)


def test_build_return_comparison_figure_portfolio_only():
    nav = _sample_nav()
    fig = build_return_comparison_figure(
        nav,
        _sample_benchmarks(nav),
        "pln",
        visible={"sp500": False, "nasdaq100": False, "acwi": False},
    )
    assert fig.data[0].visible is True
    assert all(trace.visible is False for trace in fig.data[1:])


def test_prepare_return_comparison_data():
    nav = _sample_nav()
    data = prepare_return_comparison_data(nav, _sample_benchmarks(nav), "pln")
    assert len(data.portfolio_monthly) >= 2
    assert "sp500" in data.benchmarks_monthly
    assert "nasdaq100" in data.benchmarks_monthly
    assert "acwi" in data.benchmarks_monthly


def test_sox_benchmark_configured():
    from xtb_analyzer.benchmark import BENCHMARK_TICKERS
    from xtb_analyzer.charts import BENCHMARK_META

    assert BENCHMARK_TICKERS.get("sox") == "^SOX"
    assert "sox" in BENCHMARK_META
    assert "SOX" in BENCHMARK_META["sox"][0]


def test_plot_company_pnl_sorted_largest_profit_to_largest_loss():
    from xtb_analyzer.charts import plot_company_pnl
    from xtb_analyzer.metrics import format_company_pnl_table

    company_pnl = pd.DataFrame(
        [
            {
                "symbol": "AMD.US",
                "status": "Closed",
                "currency": "USD",
                "invested_local": 1000.0,
                "total_pnl_local": 200.00,
                "realized_pnl": 800.00,
                "unrealized_pnl": 0.0,
                "total_pnl": 800.00,
                "return_pct": 0.20,
            },
            {
                "symbol": "NOW.US",
                "status": "Open",
                "currency": "USD",
                "invested_local": 520.0,
                "total_pnl_local": 50.00,
                "realized_pnl": 0.0,
                "unrealized_pnl": 200.00,
                "total_pnl": 200.00,
                "return_pct": 0.10,
            },
            {
                "symbol": "UBER.US",
                "status": "Open",
                "currency": "USD",
                "invested_local": 1100.0,
                "total_pnl_local": -100.00,
                "realized_pnl": 0.0,
                "unrealized_pnl": -400.00,
                "total_pnl": -400.00,
                "return_pct": -0.10,
            },
        ]
    )
    fig = plot_company_pnl(company_pnl, "pln")
    assert len(fig.data) == 1
    # Horizontal bar y-axis is ascending from bottom (largest loss) to top (largest profit)
    assert list(fig.data[0].y) == ["UBER.US", "NOW.US", "AMD.US"]

    table = format_company_pnl_table(company_pnl, "pln")
    assert list(table["Symbol"]) == ["AMD.US", "NOW.US", "UBER.US"]
    assert list(table["Rank"]) == ["#1", "#2", "#3"]


def test_chart_titles_centered_and_risk_has_alpha_beta():
    from xtb_analyzer.report import _risk_cards_html
    from xtb_analyzer.risk import BenchmarkRelation, RiskStats

    nav = _sample_nav()
    fig = build_return_comparison_figure(nav, _sample_benchmarks(nav), "pln")
    assert fig.layout.title.x == 0.5
    assert fig.layout.title.xanchor == "center"

    risk = RiskStats(
        volatility_annual=0.18,
        sharpe=1.42,
        sortino=1.95,
        max_drawdown=-0.08,
        max_drawdown_start="2026-01-05",
        max_drawdown_end="2026-02-10",
        calmar=2.1,
        var_95_daily=-0.015,
        best_day=0.04,
        worst_day=-0.03,
        best_month=0.09,
        worst_month=-0.04,
        positive_months_pct=0.75,
        skewness=0.1,
        benchmarks=[BenchmarkRelation("S&P 500 TR", 1.12, 0.064, 0.82, 0.15)],
    )
    html = _risk_cards_html(risk)
    assert "Annualized alpha" in html
    assert "Beta" in html
    assert "+6.40%" in html
    assert "1.12" in html
