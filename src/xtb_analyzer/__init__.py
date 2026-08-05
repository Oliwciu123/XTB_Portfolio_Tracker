"""XTB portfolio analyzer."""

from xtb_analyzer.attribution import FxAttribution, compute_fx_attribution
from xtb_analyzer.benchmark import (
    build_benchmark_suite,
    build_deposit_benchmarks,
    build_nasdaq100_deposit_benchmark,
    build_sp500_deposit_benchmark,
)
from xtb_analyzer.charts import (
    PLOTLY_SHOW_CONFIG,
    ReturnComparisonData,
    build_return_comparison_figure,
    plot_allocation_donut,
    plot_benchmark_comparison,
    plot_conversion_losses,
    plot_currency_allocation,
    plot_drawdown,
    plot_fx_attribution_series,
    plot_fx_attribution_waterfall,
    plot_holdings_allocation,
    plot_monthly_returns_heatmap,
    plot_nav_with_deposits,
    plot_return_dashboard,
    plot_return_measures,
    plot_rolling_volatility,
    plot_sector_allocation,
    prepare_return_comparison_data,
    show_return_comparison_widget,
)
from xtb_analyzer.flows import (
    analyze_conversion_losses,
    attach_deposits_to_nav,
    conversion_summary,
    extract_deposits,
)
from xtb_analyzer.metrics import (
    format_metrics_table,
    format_positions_table,
    format_realized_pnl_table,
    portfolio_snapshot,
)
from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.parser import load_accounts, load_csv
from xtb_analyzer.report import collect_report_data, generate_report, render_html_report
from xtb_analyzer.returns import ReturnMeasures, compute_return_measures, twr_daily_returns, xirr
from xtb_analyzer.risk import RiskStats, compute_risk_stats

__all__ = [
    "Account",
    "FxAttribution",
    "PLOTLY_SHOW_CONFIG",
    "ReturnComparisonData",
    "ReturnMeasures",
    "RiskStats",
    "Transaction",
    "analyze_conversion_losses",
    "attach_deposits_to_nav",
    "build_benchmark_suite",
    "build_deposit_benchmarks",
    "build_nasdaq100_deposit_benchmark",
    "build_return_comparison_figure",
    "build_sp500_deposit_benchmark",
    "collect_report_data",
    "compute_fx_attribution",
    "compute_return_measures",
    "compute_risk_stats",
    "conversion_summary",
    "extract_deposits",
    "format_metrics_table",
    "format_positions_table",
    "format_realized_pnl_table",
    "generate_report",
    "load_accounts",
    "load_csv",
    "plot_allocation_donut",
    "plot_benchmark_comparison",
    "plot_conversion_losses",
    "plot_currency_allocation",
    "plot_drawdown",
    "plot_fx_attribution_series",
    "plot_fx_attribution_waterfall",
    "plot_holdings_allocation",
    "plot_monthly_returns_heatmap",
    "plot_nav_with_deposits",
    "plot_return_dashboard",
    "plot_return_measures",
    "plot_rolling_volatility",
    "plot_sector_allocation",
    "portfolio_snapshot",
    "prepare_return_comparison_data",
    "render_html_report",
    "show_return_comparison_widget",
    "twr_daily_returns",
    "xirr",
]
