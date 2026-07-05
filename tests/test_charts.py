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
            "return_pln": [v / d - 1 for v, d in zip(nav, deposits)],
        },
        index=dates,
    )


def _sample_benchmark(nav: pd.DataFrame, factor: float) -> pd.Series:
    return nav["deposits_pln"] * factor


def test_build_return_comparison_figure_has_three_traces():
    nav = _sample_nav()
    sp500 = _sample_benchmark(nav, 1.05)
    nasdaq = _sample_benchmark(nav, 1.08)
    fig = build_return_comparison_figure(
        nav, sp500, nasdaq, currency="pln", show_sp500=True, show_nasdaq=True
    )
    assert len(fig.data) == 3
    assert fig.data[0].visible is True
    assert fig.data[1].visible is True
    assert fig.data[2].visible is True


def test_build_return_comparison_figure_portfolio_only():
    nav = _sample_nav()
    sp500 = _sample_benchmark(nav, 1.05)
    nasdaq = _sample_benchmark(nav, 1.08)
    fig = build_return_comparison_figure(
        nav, sp500, nasdaq, currency="pln", show_sp500=False, show_nasdaq=False
    )
    assert fig.data[0].visible is True
    assert fig.data[1].visible is False
    assert fig.data[2].visible is False


def test_prepare_return_comparison_data():
    nav = _sample_nav()
    sp500 = _sample_benchmark(nav, 1.05)
    nasdaq = _sample_benchmark(nav, 1.08)
    data = prepare_return_comparison_data(nav, sp500, nasdaq, "pln")
    assert len(data.portfolio_monthly) >= 2
    assert "sp500" in data.benchmarks_monthly
    assert "nasdaq100" in data.benchmarks_monthly
