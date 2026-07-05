from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from xtb_analyzer.cash import build_cash_ledger, cash_summary
from xtb_analyzer.flows import analyze_conversion_losses, conversion_summary
from xtb_analyzer.models import Account
from xtb_analyzer.benchmark import NASDAQ100_TR_TICKER, SP500_TR_TICKER
from xtb_analyzer.prices import fetch_benchmark


@dataclass
class PerformanceMetrics:
    total_return: float
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
    nasdaq100_beta: float | None
    nasdaq100_alpha: float | None
    nasdaq100_benchmark_total_return: float | None
    total_deposits: float
    current_nav: float
    gain: float


def _daily_returns(series: pd.Series) -> pd.Series:
    return series.pct_change().dropna()


def _return_on_capital(nav: pd.DataFrame, currency: str) -> pd.Series:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    invested = nav[dep_col].replace(0, pd.NA)
    return nav[nav_col] / invested - 1


def _first_investment_date(nav: pd.DataFrame, currency: str) -> pd.Timestamp | None:
    dep_col = f"deposits_{currency.lower()}"
    active = nav[dep_col] > 0
    if not active.any():
        return nav.index[0] if len(nav) else None
    return nav.index[active][0]


def _max_drawdown_on_capital(nav: pd.DataFrame, currency: str) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    roc = _return_on_capital(nav, currency).dropna()
    if roc.empty:
        return 0.0, None, None
    wealth = 1 + roc
    rolling_max = wealth.cummax()
    drawdown = wealth / rolling_max - 1
    end = drawdown.idxmin()
    start = wealth.loc[:end].idxmax()
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


def _benchmark_stats(
    series: pd.Series,
    returns: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    ticker: str,
    use_cache: bool,
    refresh_latest: bool,
) -> tuple[float | None, float | None, float | None]:
    benchmark = fetch_benchmark(
        start=start.date().isoformat(),
        end=(end + pd.Timedelta(days=1)).date().isoformat(),
        ticker=ticker,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
    if benchmark.empty:
        return None, None, None

    bench_aligned = benchmark.reindex(series.index, method="ffill").dropna()
    if bench_aligned.empty:
        return None, None, None

    bench_returns = _daily_returns(bench_aligned)
    beta, alpha = _beta_alpha(returns, bench_returns)
    benchmark_return = float(bench_aligned.iloc[-1] / bench_aligned.iloc[0] - 1)
    return beta, alpha, benchmark_return


def portfolio_snapshot(nav: pd.DataFrame, currency: str = "pln") -> dict[str, object]:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    return_col = f"return_{currency}"
    gain_col = f"gain_{currency}"

    as_of = nav.index[-1]
    current_nav = round(float(nav[nav_col].iloc[-1]), 2)
    total_deposits = round(float(nav[dep_col].iloc[-1]), 2)
    gain = round(float(nav[gain_col].iloc[-1]), 2) if gain_col in nav.columns else round(current_nav - total_deposits, 2)
    total_return = round(float(nav[return_col].iloc[-1]), 4) if return_col in nav.columns else 0.0

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "currency": currency.upper(),
        "current_nav": current_nav,
        "total_deposits": total_deposits,
        "gain": gain,
        "return_on_capital": total_return,
    }


def compute_metrics(
    nav: pd.DataFrame,
    currency: str = "usd",
    use_cache: bool = True,
    refresh_latest: bool = True,
) -> PerformanceMetrics:
    currency = currency.lower()
    col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    series = nav[col].dropna()

    if dep_col not in nav.columns:
        raise ValueError("NAV must include deposit columns. Run attach_deposits_to_nav() first.")

    roc = _return_on_capital(nav, currency).dropna()
    returns = _daily_returns(roc)
    mdd, mdd_start, mdd_end = _max_drawdown_on_capital(nav, currency)
    ath = float(series.max())
    benchmark_return = None
    beta = alpha = None
    nasdaq100_beta = nasdaq100_alpha = None
    nasdaq100_benchmark_return = None

    invested = float(nav[dep_col].iloc[-1])
    current_nav = float(series.iloc[-1])
    total_return = float(current_nav / invested - 1) if invested > 0 else 0.0
    gain = current_nav - invested

    if not series.empty:
        start = _first_investment_date(nav, currency) or series.index[0]
        end = series.index[-1]
        beta, alpha, benchmark_return = _benchmark_stats(
            series, returns, start, end, SP500_TR_TICKER, use_cache, refresh_latest
        )
        nasdaq100_beta, nasdaq100_alpha, nasdaq100_benchmark_return = _benchmark_stats(
            series, returns, start, end, NASDAQ100_TR_TICKER, use_cache, refresh_latest
        )

    return PerformanceMetrics(
        total_return=total_return,
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
        nasdaq100_beta=nasdaq100_beta,
        nasdaq100_alpha=nasdaq100_alpha,
        nasdaq100_benchmark_total_return=nasdaq100_benchmark_return,
        total_deposits=invested,
        current_nav=current_nav,
        gain=gain,
    )


def drawdown_series(nav: pd.DataFrame, currency: str = "usd") -> pd.Series:
    return _return_on_capital(nav, currency).dropna()


def rolling_volatility(nav: pd.DataFrame, currency: str = "usd", window: int = 21) -> pd.Series:
    roc = _return_on_capital(nav, currency)
    return _daily_returns(roc).rolling(window).std() * np.sqrt(252)


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


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2%}".replace(".", ",")


def _fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def format_metrics_table(metrics: PerformanceMetrics, currency: str = "pln") -> pd.DataFrame:
    currency = currency.upper()
    rows = [
        ("Aktualna wartość portfela", f"{_fmt_num(metrics.current_nav)} {currency}"),
        ("Suma wpłat", f"{_fmt_num(metrics.total_deposits)} {currency}"),
        ("Zysk / strata", f"{_fmt_num(metrics.gain)} {currency}"),
        (
            "Zwrot na wpłaconym kapitale",
            f"{_fmt_pct(metrics.total_return)}  (wartość ÷ wpłaty − 1)",
        ),
        ("Zmienność (roczna)", _fmt_pct(metrics.volatility)),
        ("Współczynnik Sharpe'a", _fmt_num(metrics.sharpe)),
        ("Współczynnik Sortino", _fmt_num(metrics.sortino)),
        ("Maks. obsunięcie (drawdown)", _fmt_pct(metrics.max_drawdown)),
        ("Szczyt wartości portfela (ATH)", f"{_fmt_num(metrics.ath)} {currency}"),
        ("Odległość od ATH", _fmt_pct(metrics.pct_from_ath)),
        ("Beta vs S&P 500", _fmt_num(metrics.beta)),
        ("Alfa vs S&P 500", _fmt_num(metrics.alpha)),
        ("Zwrot benchmarku (S&P 500 TR)", _fmt_pct(metrics.benchmark_total_return)),
        ("Beta vs NASDAQ 100", _fmt_num(metrics.nasdaq100_beta)),
        ("Alfa vs NASDAQ 100", _fmt_num(metrics.nasdaq100_alpha)),
        ("Zwrot benchmarku (NASDAQ 100 TR)", _fmt_pct(metrics.nasdaq100_benchmark_total_return)),
    ]
    if metrics.max_drawdown_start and metrics.max_drawdown_end:
        rows.append(
            (
                "Okres maks. drawdownu",
                f"{metrics.max_drawdown_start} → {metrics.max_drawdown_end}",
            )
        )
    return pd.DataFrame(rows, columns=["Metryka", "Wartość"])


def format_positions_table(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty:
        return positions
    frame = positions.sort_values("market_value_pln", ascending=False).copy()
    numeric_cols = [
        "shares",
        "avg_cost",
        "market_price",
        "cost_basis",
        "market_value",
        "unrealized_pnl",
        "market_value_pln",
        "market_value_usd",
        "market_value_eur",
        "weight",
    ]
    for col in numeric_cols:
        if col in frame.columns:
            frame[col] = frame[col].round(2)
    frame = frame.rename(
        columns={
            "account_id": "Konto",
            "symbol": "Symbol",
            "currency": "Waluta",
            "shares": "Liczba akcji",
            "avg_cost": "Śr. cena zakupu",
            "market_price": "Aktualna cena",
            "cost_basis": "Koszt nabycia",
            "market_value": "Wartość rynkowa",
            "unrealized_pnl": "Niezrealizowany P&L",
            "market_value_pln": "Wartość PLN",
            "market_value_usd": "Wartość USD",
            "market_value_eur": "Wartość EUR",
            "weight": "Udział",
            "sector": "Sektor",
            "industry": "Branża",
        }
    )
    if "Udział" in frame.columns:
        frame["Udział"] = (frame["Udział"] * 100).round(2)
    return frame


def format_realized_pnl_table(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(columns=["Symbol", "Transakcje", "Zrealizowany P&L", "Średni P&L", "Win rate"])
    frame = summary.copy()
    frame = frame.rename(
        columns={
            "symbol": "Symbol",
            "trades": "Transakcje",
            "total_realized_pnl": "Zrealizowany P&L",
            "avg_realized_pnl": "Średni P&L",
            "win_rate": "Win rate",
        }
    )
    frame["Win rate"] = (frame["Win rate"] * 100).round(2)
    frame["Zrealizowany P&L"] = frame["Zrealizowany P&L"].round(2)
    frame["Średni P&L"] = frame["Średni P&L"].round(2)
    return frame


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
