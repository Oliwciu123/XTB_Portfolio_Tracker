"""XTB portfolio analyzer."""

from xtb_analyzer.benchmark import build_sp500_deposit_benchmark
from xtb_analyzer.charts import (
    plot_benchmark_comparison,
    plot_conversion_losses,
    plot_nav_with_deposits,
    plot_return_dashboard,
)
from xtb_analyzer.flows import (
    analyze_conversion_losses,
    attach_deposits_to_nav,
    conversion_summary,
    extract_deposits,
)
from xtb_analyzer.models import Account, Transaction
from xtb_analyzer.parser import load_accounts, load_csv

__all__ = [
    "Account",
    "Transaction",
    "analyze_conversion_losses",
    "attach_deposits_to_nav",
    "build_sp500_deposit_benchmark",
    "conversion_summary",
    "extract_deposits",
    "load_accounts",
    "load_csv",
    "plot_benchmark_comparison",
    "plot_conversion_losses",
    "plot_nav_with_deposits",
    "plot_return_dashboard",
]
