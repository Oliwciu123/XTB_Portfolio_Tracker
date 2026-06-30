"""XTB portfolio analyzer."""

from xtb_analyzer.benchmark import build_sp500_deposit_benchmark
from xtb_analyzer.charts import (
    PLOTLY_SHOW_CONFIG,
    plot_benchmark_comparison,
    plot_conversion_losses,
    plot_nav_with_deposits,
    plot_return_dashboard,
    plot_sector_allocation,
)
from xtb_analyzer.flows import (
    analyze_conversion_losses,
    attach_deposits_to_nav,
    conversion_summary,
    extract_deposits,
)
from xtb_analyzer.metrics import format_metrics_table, format_positions_table, format_realized_pnl_table, portfolio_snapshot
from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.parser import load_accounts, load_csv

__all__ = [
    "Account",
    "PLOTLY_SHOW_CONFIG",
    "Transaction",
    "analyze_conversion_losses",
    "attach_deposits_to_nav",
    "build_sp500_deposit_benchmark",
    "conversion_summary",
    "extract_deposits",
    "format_metrics_table",
    "format_positions_table",
    "format_realized_pnl_table",
    "portfolio_snapshot",
    "load_accounts",
    "load_csv",
    "plot_benchmark_comparison",
    "plot_conversion_losses",
    "plot_nav_with_deposits",
    "plot_return_dashboard",
    "plot_sector_allocation",
]
