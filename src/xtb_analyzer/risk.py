"""Risk statistics computed on time-weighted (TWR) daily returns.

TWR returns neutralize deposits, so these statistics describe the behaviour of
the investments themselves and are directly comparable with benchmark indices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class BenchmarkRelation:
    name: str
    beta: float | None
    alpha_annual: float | None
    correlation: float | None
    benchmark_return: float | None


@dataclass
class RiskStats:
    volatility_annual: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_start: str | None
    max_drawdown_end: str | None
    calmar: float | None
    var_95_daily: float
    best_day: float
    worst_day: float
    best_month: float | None
    worst_month: float | None
    positive_months_pct: float | None
    skewness: float | None
    benchmarks: list[BenchmarkRelation]


def monthly_returns(daily_returns: pd.Series) -> pd.Series:
    if daily_returns.empty:
        return pd.Series(dtype=float)
    return (1 + daily_returns).resample("ME").prod() - 1


def drawdown_from_returns(daily_returns: pd.Series) -> pd.Series:
    """Drawdown of the TWR wealth index (0 at peaks, negative below)."""
    if daily_returns.empty:
        return pd.Series(dtype=float)
    wealth = (1 + daily_returns).cumprod()
    return wealth / wealth.cummax().clip(lower=1.0) - 1


def _max_drawdown(
    daily_returns: pd.Series,
) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    drawdown = drawdown_from_returns(daily_returns)
    if drawdown.empty or drawdown.min() >= 0:
        return 0.0, None, None
    end = drawdown.idxmin()
    wealth = (1 + daily_returns).cumprod()
    start = wealth.loc[:end].idxmax()
    return float(drawdown.min()), start, end


def _annualized_return(daily_returns: pd.Series) -> float | None:
    if daily_returns.empty:
        return None
    total = float((1 + daily_returns).prod())
    days = (daily_returns.index[-1] - daily_returns.index[0]).days
    if days < 30 or total <= 0:
        return None
    return total ** (365.25 / days) - 1


def _sharpe(returns: pd.Series, risk_free_annual: float = 0.0) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return float("nan")
    excess = returns - risk_free_annual / TRADING_DAYS
    return float(np.sqrt(TRADING_DAYS) * excess.mean() / excess.std())


def _sortino(returns: pd.Series, risk_free_annual: float = 0.0) -> float:
    if returns.empty:
        return float("nan")
    excess = returns - risk_free_annual / TRADING_DAYS
    downside_deviation = float(np.sqrt(np.minimum(excess, 0).pow(2).mean()))
    if downside_deviation == 0:
        return float("nan")
    return float(np.sqrt(TRADING_DAYS) * excess.mean() / downside_deviation)


def _benchmark_relation(
    name: str,
    portfolio_returns: pd.Series,
    benchmark_series: pd.Series,
) -> BenchmarkRelation:
    if benchmark_series.empty:
        return BenchmarkRelation(name, None, None, None, None)

    aligned_bench = benchmark_series.reindex(portfolio_returns.index, method="ffill").dropna()
    bench_returns = aligned_bench.pct_change().dropna()
    joined = pd.concat([portfolio_returns, bench_returns], axis=1, join="inner").dropna()
    benchmark_return = (
        float(aligned_bench.iloc[-1] / aligned_bench.iloc[0] - 1)
        if len(aligned_bench) > 1
        else None
    )

    if len(joined) < 5:
        return BenchmarkRelation(name, None, None, None, benchmark_return)

    cov = np.cov(joined.iloc[:, 0], joined.iloc[:, 1])
    if cov[1, 1] == 0:
        return BenchmarkRelation(name, None, None, None, benchmark_return)
    beta = float(cov[0, 1] / cov[1, 1])
    alpha = float((joined.iloc[:, 0].mean() - beta * joined.iloc[:, 1].mean()) * TRADING_DAYS)
    correlation = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
    return BenchmarkRelation(name, beta, alpha, correlation, benchmark_return)


def compute_risk_stats(
    daily_returns: pd.Series,
    benchmarks: dict[str, pd.Series] | None = None,
    risk_free_annual: float = 0.0,
) -> RiskStats:
    """Compute risk statistics from TWR daily returns.

    ``benchmarks`` maps display names to benchmark *price level* series.
    """
    daily_returns = daily_returns.replace([np.inf, -np.inf], np.nan).dropna()
    mdd, mdd_start, mdd_end = _max_drawdown(daily_returns)
    annual_return = _annualized_return(daily_returns)
    monthly = monthly_returns(daily_returns)

    relations = [
        _benchmark_relation(name, daily_returns, series)
        for name, series in (benchmarks or {}).items()
    ]

    return RiskStats(
        volatility_annual=float(daily_returns.std() * np.sqrt(TRADING_DAYS))
        if len(daily_returns) > 1
        else 0.0,
        sharpe=_sharpe(daily_returns, risk_free_annual),
        sortino=_sortino(daily_returns, risk_free_annual),
        max_drawdown=mdd,
        max_drawdown_start=mdd_start.date().isoformat() if mdd_start is not None else None,
        max_drawdown_end=mdd_end.date().isoformat() if mdd_end is not None else None,
        calmar=annual_return / abs(mdd) if annual_return is not None and mdd < 0 else None,
        var_95_daily=float(np.percentile(daily_returns, 5)) if not daily_returns.empty else 0.0,
        best_day=float(daily_returns.max()) if not daily_returns.empty else 0.0,
        worst_day=float(daily_returns.min()) if not daily_returns.empty else 0.0,
        best_month=float(monthly.max()) if not monthly.empty else None,
        worst_month=float(monthly.min()) if not monthly.empty else None,
        positive_months_pct=float((monthly > 0).mean()) if not monthly.empty else None,
        skewness=float(daily_returns.skew()) if len(daily_returns) > 2 else None,
        benchmarks=relations,
    )
