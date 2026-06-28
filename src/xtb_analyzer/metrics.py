from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from xtb_analyzer.cash import build_cash_ledger, cash_summary
from xtb_analyzer.flows import analyze_conversion_losses, conversion_summary
from xtb_analyzer.models import Account
from xtb_analyzer.prices import fetch_benchmark


@dataclass
class PerformanceMetrics:
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_start: str | None
    max_drawdown_end: str | None
    ath: float
    pct_from_ath: float
    beta: float | None
    alpha: float | None
    benchmark_total_return: float | None


def _daily_returns(nav: pd.Series) -> pd.Series:
    return nav.pct_change().dropna()


def _cagr(nav: pd.Series) -> float:
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return 0.0
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1)


def _max_drawdown(nav: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    rolling_max = nav.cummax()
    drawdown = nav / rolling_max - 1
    if drawdown.empty:
        return 0.0, None, None
    end = drawdown.idxmin()
    start = nav.loc[:end].idxmax()
    return float(drawdown.min()), start, end


def _sharpe(returns: pd.Series, risk_free: float = 0.0) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    excess = returns - risk_free / 252
    return float(np.sqrt(252) * excess.mean() / excess.std())


def _sortino(returns: pd.Series, risk_free: float = 0.0) -> float:
    if returns.empty:
        return 0.0
    excess = returns - risk_free / 252
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0:
        return 0.0
    return float(np.sqrt(252) * excess.mean() / downside.std())


def _beta_alpha(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> tuple[float | None, float | None]:
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 5:
        return None, None
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
    if cov[1, 1] == 0:
        return None, None
    beta = cov[0, 1] / cov[1, 1]
    alpha = (aligned.iloc[:, 0].mean() - beta * aligned.iloc[:, 1].mean()) * 252
    return float(beta), float(alpha)


def compute_metrics(nav: pd.DataFrame, currency: str = "usd", use_cache: bool = True) -> PerformanceMetrics:
    col = f"nav_{currency.lower()}"
    series = nav[col].dropna()
    returns = _daily_returns(series)
    mdd, mdd_start, mdd_end = _max_drawdown(series)
    ath = float(series.max())
    benchmark_return = None
    beta = alpha = None

    if not series.empty:
        benchmark = fetch_benchmark(
            start=series.index[0].date().isoformat(),
            end=(series.index[-1] + pd.Timedelta(days=1)).date().isoformat(),
            use_cache=use_cache,
        )
        if not benchmark.empty:
            bench_aligned = benchmark.reindex(series.index, method="ffill").dropna()
            bench_returns = _daily_returns(bench_aligned)
            beta, alpha = _beta_alpha(returns, bench_returns)
            benchmark_return = float(bench_aligned.iloc[-1] / bench_aligned.iloc[0] - 1)

    return PerformanceMetrics(
        total_return=float(series.iloc[-1] / series.iloc[0] - 1) if len(series) > 1 else 0.0,
        cagr=_cagr(series),
        volatility=float(returns.std() * np.sqrt(252)) if not returns.empty else 0.0,
        sharpe=_sharpe(returns),
        sortino=_sortino(returns),
        max_drawdown=mdd,
        max_drawdown_start=mdd_start.date().isoformat() if mdd_start is not None else None,
        max_drawdown_end=mdd_end.date().isoformat() if mdd_end is not None else None,
        ath=ath,
        pct_from_ath=float(series.iloc[-1] / ath - 1) if ath else 0.0,
        beta=beta,
        alpha=alpha,
        benchmark_total_return=benchmark_return,
    )


def drawdown_series(nav: pd.DataFrame, currency: str = "usd") -> pd.Series:
    col = f"nav_{currency.lower()}"
    series = nav[col].dropna()
    return series / series.cummax() - 1


def rolling_volatility(nav: pd.DataFrame, currency: str = "usd", window: int = 21) -> pd.Series:
    col = f"nav_{currency.lower()}"
    return _daily_returns(nav[col]).rolling(window).std() * np.sqrt(252)


def realized_pnl_summary(accounts: list[Account]) -> pd.DataFrame:
    rows = []
    for account in accounts:
        for tx in account.transactions:
            if tx.type == "close_trade" and tx.symbol:
                rows.append(
                    {
                        "account_id": account.account_id,
                        "symbol": tx.symbol,
                        "timestamp": tx.timestamp,
                        "realized_pnl": float(tx.realized_pnl or tx.amount),
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    summary = (
        frame.groupby("symbol", as_index=False)
        .agg(
            trades=("realized_pnl", "count"),
            total_realized_pnl=("realized_pnl", "sum"),
            avg_realized_pnl=("realized_pnl", "mean"),
            win_rate=("realized_pnl", lambda s: float((s > 0).mean())),
        )
        .sort_values("total_realized_pnl", ascending=False)
    )
    return summary


def build_report(
    accounts: list[Account],
    nav: pd.DataFrame,
    positions: pd.DataFrame,
    output_dir: str | Path = "output",
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ledger = build_cash_ledger(accounts)
    conversion_losses = analyze_conversion_losses(accounts)
    metrics = {
        currency: asdict(compute_metrics(nav, currency=currency))
        for currency in ("pln", "usd", "eur")
    }
    report = {
        "cash": cash_summary(ledger),
        "conversion": conversion_summary(conversion_losses),
        "conversion_details": conversion_losses.to_dict(orient="records"),
        "metrics": metrics,
        "positions": positions.to_dict(orient="records"),
        "accounts": [
            {
                "account_id": account.account_id,
                "currency": account.currency,
                "equity_snapshot": float(account.equity) if account.equity else None,
            }
            for account in accounts
        ],
    }
    with (output_dir / "report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    return report
