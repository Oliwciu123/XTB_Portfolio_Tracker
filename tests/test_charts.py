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
