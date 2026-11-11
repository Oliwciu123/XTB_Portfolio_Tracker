"""Worked indicator calculations that end at the values shown on the dashboard."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from xtb_analyzer.definitions import FORMULA_TEX, INDICATOR_SUMMARY, METRIC_DEFINITIONS
from xtb_analyzer.risk import TRADING_DAYS, _annualized_return, _max_drawdown, monthly_returns
from xtb_analyzer.tax import Pit38YearSummary, _q2

PIT_KEYS = (
    "pit38_revenue",
    "pit38_costs",
    "pit38_income",
    "pit38_wht_credit",
    "pit38_total_tax",
)


def _fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}"


def _fmt_pct(value: float | None, decimals: int = 2, sign: bool = True) -> str:
    if value is None or pd.isna(value):
        return "—"
    pattern = f"{{:+.{decimals}f}}%" if sign else f"{{:.{decimals}f}}%"
    return pattern.format(value * 100)


def _money(value: float | None, currency: str, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{_fmt_num(value, decimals)} {currency.upper()}"


def _step(label: str, detail: str, value: str, *, result: bool = False) -> dict[str, Any]:
    return {"label": label, "detail": detail, "value": value, "result": result}


def _finite(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _ranges(key: str, active: int | None) -> list[dict[str, Any]]:
    definition = METRIC_DEFINITIONS[key]
    return [
        {
            "band": item.band,
            "meaning": item.meaning,
            "tone": item.tone,
            "active": index == active,
        }
        for index, item in enumerate(definition.ranges)
    ]


def _pack(
    key: str,
    display: str,
    steps: list[dict[str, Any]],
    *,
    active: int | None,
    note: str = "",
    range_value: str | None = None,
    check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = METRIC_DEFINITIONS[key]
    if steps and steps[-1].get("result"):
        steps[-1]["value"] = display
    return {
        "key": key,
        "title": definition.title,
        "summary": INDICATOR_SUMMARY[key],
        "explanation": definition.explanation,
        "example": definition.example,
        "formula_tex": FORMULA_TEX[key],
        "display_value": display,
        "range_value": range_value or display,
        "steps": steps,
        "ranges": _ranges(key, active),
        "range_note": note,
        "check": check or {},
    }


def _primary_benchmark(data: Any):
    risk = data.risk
    return next(
        (
            item
            for item in risk.benchmarks
            if item.beta is not None or item.alpha_annual is not None
        ),
        risk.benchmarks[0] if risk.benchmarks else None,
    )


def _band_for(key: str, value: float | None, ctx: dict[str, Any]) -> tuple[int | None, str]:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None, "This report has no numeric value for the reference bands."
    if key == "nav":
        net = ctx["net_deposits"]
        if value > net:
            return 0, ""
        if value < net:
            return 1, ""
        return None, "NAV equals net deposits, so neither comparison band applies."
    if key == "contributions":
        return (0 if ctx["steady_deposits"] else 1), ""
    if key == "profit_loss":
        if value > 0:
            return 0, ""
        if value == 0:
            return 1, ""
        return 2, ""
    if key == "roi":
        if value > 0.20:
            return 0, ""
        if value >= 0:
            return 1, ""
        return 2, ""
    if key == "mwr_xirr":
        xirr = ctx.get("xirr")
        if xirr is None:
            return None, "Annualized XIRR is unavailable, so the bands are not marked."
        note = "Bands use the annualized XIRR shown under the dashboard card."
        if xirr > 0.10:
            return 0, note
        if xirr >= 0.04:
            return 1, note
        if xirr < 0:
            return 2, note
        return None, "Annualized XIRR is between 0% and 4%, outside the listed bands."
    if key == "twr":
        bench = ctx.get("benchmark_return")
        name = ctx.get("benchmark_name") or "the benchmark"
        compared = f"Compared with {name} ({_fmt_pct(bench)})." if bench is not None else ""
        if value < 0:
            return 2, compared
        if bench is None or not math.isfinite(float(bench)):
            return None, f"No {name} return was available, so the comparison bands are not marked."
        if value > bench:
            return 0, compared
        if 0 < value < bench:
            return 1, compared
        return None, f"{compared} TWR is not strictly inside one listed band."
    if key == "volatility":
        if value < 0.12:
            return 0, ""
        if value <= 0.22:
            return 1, ""
        if value > 0.25:
            return 2, ""
        return None, "The value sits between the 12–22% and >25% bands."
    if key in {"sharpe", "sortino"}:
        if value < 0:
            return 0, ""
        if value < 1:
            return 1, ""
        if value <= 2:
            return 2, ""
        return 3, ""
    if key == "alpha":
        if value > 0.02:
            return 0, ""
        if value >= -0.02:
            return 1, ""
        return 2, ""
    if key == "beta":
        if value < 0.85:
            return 0, ""
        if value <= 1.15:
            return 1, ""
        return 2, ""
    if key == "max_drawdown":
        if value >= -0.15:
            return 0, ""
        if value >= -0.30:
            return 1, ""
        return 2, ""
    if key == "calmar":
        if value < 0:
            return 0, ""
        if value < 0.5:
            return 1, ""
        if value <= 1:
            return 2, ""
        return 3, ""
    if key == "var_95":
        if value >= -0.012:
            return 0, ""
        if value >= -0.025:
            return 1, ""
        return 2, ""
    if key == "win_rate":
        if value > 0.60:
            return 0, ""
        if value >= 0.45:
            return 1, ""
        return 2, ""
    if key == "profit_factor":
        if value < 1:
            return 0, ""
        if value < 1.5:
            return 1, ""
        if value <= 2.5:
            return 2, ""
        return 3, ""
    if key == "best_month":
        if value > 0.08:
            return 0, ""
        if value >= 0:
            return 1, ""
        return None, "Every month was negative, below the listed bands."
    if key == "worst_month":
        if value > 0:
            return None, "The worst month was positive, above the listed bands."
        if value >= -0.05:
            return 0, ""
        if value >= -0.10:
            return 1, ""
        return 2, ""
    if key == "pit38_income":
        if value > 0:
            return 0, ""
        if value < 0:
            return 1, ""
        return None, "Section C is exactly zero."
    return None, ""


def _core_guides(data: Any) -> dict[str, dict[str, Any]]:
    measures = data.measures
    currency = data.currency
    daily = data.twr_returns.replace([np.inf, -np.inf], np.nan).dropna()
    risk = data.risk
    nav_value = float(measures.final_value)
    invested = float(measures.invested)
    withdrawn = float(measures.withdrawn)
    gain = float(measures.gain)
    net_deposits = invested - withdrawn
    cash_col = f"cash_{currency.lower()}"
    cash = float(data.nav[cash_col].iloc[-1]) if cash_col in data.nav.columns else None
    holdings = nav_value - cash if cash is not None else None

    ops = data.deposit_ops
    deposit_count = 0 if ops is None or ops.empty else int(len(ops))
    deposit_sum = 0.0 if ops is None or ops.empty else float(ops["amount"].sum())
    if ops is not None and not ops.empty and "year_month" in ops.columns and deposit_sum:
        month_totals = ops.groupby("year_month")["amount"].sum()
        months = int(month_totals.shape[0])
        max_share = float(month_totals.max() / deposit_sum)
        steady = months >= 6 and max_share < 0.40
    else:
        months = 0
        max_share = 1.0
        steady = False

    ctx: dict[str, Any] = {
        "net_deposits": net_deposits,
        "steady_deposits": steady,
        "xirr": _finite(measures.xirr),
        "benchmark_return": None,
        "benchmark_name": None,
    }
    primary = _primary_benchmark(data)
    if primary is not None:
        ctx["benchmark_return"] = _finite(primary.benchmark_return)
        ctx["benchmark_name"] = primary.name

    guides: dict[str, dict[str, Any]] = {}

    nav_display = _money(nav_value, currency)
    nav_steps = []
    if cash is not None and holdings is not None:
        nav_steps.append(
            _step(
                "Cash",
                "Uninvested cash across accounts, converted to the report currency.",
                _money(cash, currency),
            )
        )
        nav_steps.append(
            _step(
                "Open holdings",
                "Shares × unadjusted price × FX for every open position.",
                _money(holdings, currency),
            )
        )
    nav_steps.append(
        _step(
            "Portfolio NAV",
            "Cash + open holdings.",
            nav_display,
            result=True,
        )
    )
    nav_active, nav_note = _band_for("nav", nav_value, ctx)
    guides["nav"] = _pack(
        "nav",
        nav_display,
        nav_steps,
        active=nav_active,
        note=nav_note,
        check={"kind": "nav", "cash": cash, "holdings": holdings, "nav": nav_value},
    )

    contrib_display = _money(invested, currency)
    contrib_steps = [
        _step(
            "Inbound deposits",
            (
                f"{deposit_count} external deposits across {months} months. "
                f"The largest month is {max_share * 100:.1f}% of the total."
                if deposit_count
                else "No external deposits were found."
            ),
            _money(deposit_sum, currency) if deposit_count else contrib_display,
        ),
        _step(
            "Gross contributions",
            "Sum of external funding on the valuation ledger. Internal account transfers are excluded.",
            contrib_display,
            result=True,
        ),
    ]
    contrib_active, contrib_note = _band_for("contributions", invested, ctx)
    guides["contributions"] = _pack(
        "contributions",
        contrib_display,
        contrib_steps,
        active=contrib_active,
        note=contrib_note,
        check={
            "kind": "contributions",
            "invested": invested,
            "deposit_sum": deposit_sum,
            "steady": steady,
        },
    )

    pnl_display = _money(gain, currency)
    pnl_active, pnl_note = _band_for("profit_loss", gain, ctx)
    guides["profit_loss"] = _pack(
        "profit_loss",
        pnl_display,
        [
            _step("Portfolio NAV", "Value on the valuation date.", _money(nav_value, currency)),
            _step(
                "Withdrawals", "Cash taken out to an external account.", _money(withdrawn, currency)
            ),
            _step(
                "Gross contributions",
                "Cash paid in from outside the accounts.",
                _money(invested, currency),
            ),
            _step(
                "Profit / loss",
                "NAV + withdrawals − gross contributions.",
                pnl_display,
                result=True,
            ),
        ],
        active=pnl_active,
        note=pnl_note,
        check={"kind": "sum", "parts": [nav_value, withdrawn, -invested], "result": gain},
    )

    roi = float(measures.roi)
    roi_display = _fmt_pct(roi)
    roi_active, roi_note = _band_for("roi", roi, ctx)
    guides["roi"] = _pack(
        "roi",
        roi_display,
        [
            _step(
                "Profit / loss", "NAV + withdrawals − gross contributions.", _money(gain, currency)
            ),
            _step("Gross contributions", "The denominator.", _money(invested, currency)),
            _step(
                "ROI",
                "Profit / loss ÷ gross contributions.",
                roi_display,
                result=True,
            ),
        ],
        active=roi_active,
        note=roi_note,
        check={"kind": "ratio", "num": gain, "den": invested, "result": roi, "format": "pct"},
    )

    xirr = _finite(measures.xirr)
    mwr = _finite(measures.mwr)
    days = int(measures.period_days)
    mwr_display = _fmt_pct(mwr)
    mwr_active, mwr_note = _band_for("mwr_xirr", mwr, ctx)
    mwr_steps = [
        _step(
            "Cash-flow set",
            "Each external deposit is an outflow. The terminal NAV is the final inflow.",
            f"{days} days",
        )
    ]
    if xirr is not None:
        mwr_steps.append(
            _step(
                "Annualized XIRR",
                "Rate that sets the NPV of those cash flows to zero, using a 365.25-day year.",
                _fmt_pct(xirr),
            )
        )
        mwr_steps.append(
            _step(
                "Period MWR",
                f"(1 + XIRR)^({days} / 365.25) − 1. This is the figure on the dashboard card.",
                mwr_display,
                result=True,
            )
        )
    else:
        mwr_steps.append(
            _step(
                "Period MWR", "XIRR had no solution for these cash flows.", mwr_display, result=True
            )
        )
    guides["mwr_xirr"] = _pack(
        "mwr_xirr",
        mwr_display,
        mwr_steps,
        active=mwr_active,
        note=mwr_note,
        range_value=_fmt_pct(xirr) if xirr is not None else mwr_display,
        check={"kind": "mwr", "xirr": xirr, "days": days, "result": mwr},
    )

    growth = float((1 + daily).prod()) if not daily.empty else 1.0
    twr = float(measures.twr)
    twr_display = _fmt_pct(twr)
    twr_active, twr_note = _band_for("twr", twr, ctx)
    twr_steps = [
        _step(
            "Daily sub-period returns",
            "Each day uses NAV ÷ (previous NAV + that day's external flow) − 1.",
            f"{len(daily)} days",
        ),
        _step(
            "Growth of 1",
            "Product of (1 + daily TWR).",
            f"{growth:,.6f}",
        ),
        _step("TWR", "Growth of 1 − 1.", twr_display, result=True),
    ]
    if measures.twr_annualized is not None:
        twr_steps.insert(
            -1,
            _step(
                "Annualized TWR",
                f"The dashboard subtitle compounds TWR over {days} days.",
                _fmt_pct(measures.twr_annualized),
            ),
        )
    guides["twr"] = _pack(
        "twr",
        twr_display,
        twr_steps,
        active=twr_active,
        note=twr_note,
        check={"kind": "twr", "growth": growth, "result": twr, "n": int(len(daily))},
    )

    mean = float(daily.mean()) if len(daily) else float("nan")
    std = float(daily.std()) if len(daily) > 1 else float("nan")
    vol = float(risk.volatility_annual)
    vol_display = _fmt_pct(vol, sign=False)
    vol_active, vol_note = _band_for("volatility", vol, ctx)
    guides["volatility"] = _pack(
        "volatility",
        vol_display,
        [
            _step(
                "Sample size",
                "Daily time-weighted returns, sample standard deviation.",
                f"N = {len(daily)}",
            ),
            _step(
                "Daily standard deviation",
                "Square root of the sum of squared deviations from the mean, divided by N − 1.",
                _fmt_pct(std, decimals=4, sign=False) if _finite(std) is not None else "—",
            ),
            _step(
                "Annualized volatility",
                "Daily standard deviation × √252.",
                vol_display,
                result=True,
            ),
        ],
        active=vol_active,
        note=vol_note,
        check={"kind": "vol", "std": std, "result": vol},
    )

    sharpe = _finite(float(risk.sharpe)) if len(daily) > 1 else None
    sharpe_display = _fmt_num(sharpe)
    sharpe_active, sharpe_note = _band_for("sharpe", sharpe, ctx)
    guides["sharpe"] = _pack(
        "sharpe",
        sharpe_display,
        [
            _step(
                "Mean daily excess return",
                "Risk-free rate is 0, so this is the mean daily TWR.",
                f"{mean:.8f}" if _finite(mean) is not None else "—",
            ),
            _step(
                "Daily excess standard deviation",
                "Sample standard deviation of the same excess returns (σ_p).",
                f"{std:.8f}" if _finite(std) is not None else "—",
            ),
            _step(
                "Sharpe ratio",
                "√252 × mean excess return / σ_p.",
                sharpe_display,
                result=True,
            ),
        ],
        active=sharpe_active,
        note=sharpe_note,
        check={"kind": "sharpe", "mean": mean, "std": std, "result": sharpe},
    )

    excess = daily
    downside = (
        float(np.sqrt(np.minimum(excess, 0).pow(2).mean())) if not excess.empty else float("nan")
    )
    sortino = _finite(float(risk.sortino)) if not excess.empty else None
    sortino_display = _fmt_num(sortino)
    sortino_active, sortino_note = _band_for("sortino", sortino, ctx)
    guides["sortino"] = _pack(
        "sortino",
        sortino_display,
        [
            _step(
                "Mean daily excess return",
                "Risk-free rate is 0.",
                f"{mean:.8f}" if _finite(mean) is not None else "—",
            ),
            _step(
                "Downside deviation",
                "Square root of the average of squared negative excess returns, using all N days.",
                f"{downside:.8f}" if _finite(downside) is not None else "—",
            ),
            _step(
                "Sortino ratio",
                "√252 × mean excess return / downside deviation.",
                sortino_display,
                result=True,
            ),
        ],
        active=sortino_active,
        note=sortino_note,
        check={"kind": "sortino", "mean": mean, "downside": downside, "result": sortino},
    )

    alpha = _finite(primary.alpha_annual) if primary is not None else None
    beta = _finite(primary.beta) if primary is not None else None
    bench_name = primary.name if primary is not None else "benchmark"
    alpha_display = _fmt_pct(alpha)
    beta_display = _fmt_num(beta)
    alpha_active, alpha_note = _band_for("alpha", alpha, ctx)
    beta_active, beta_note = _band_for("beta", beta, ctx)
    mean_p = _finite(primary.mean_portfolio) if primary is not None else None
    mean_b = _finite(primary.mean_benchmark) if primary is not None else None
    observations = primary.observations if primary is not None else None
    if (
        primary is not None
        and alpha is not None
        and beta is not None
        and mean_p is not None
        and mean_b is not None
    ):
        guides["alpha"] = _pack(
            "alpha",
            alpha_display,
            [
                _step(
                    "Overlapping days",
                    f"Daily portfolio TWR aligned with {bench_name}.",
                    str(observations or 0),
                ),
                _step("Mean portfolio return", "Average daily TWR on those days.", f"{mean_p:.8f}"),
                _step(
                    "Mean benchmark return",
                    "Average daily benchmark return on those days.",
                    f"{mean_b:.8f}",
                ),
                _step("Beta", "Market sensitivity used in the alpha identity.", beta_display),
                _step(
                    "Annualized alpha",
                    f"({mean_p:.8f} − {beta:.8f} × {mean_b:.8f}) × {TRADING_DAYS}.",
                    alpha_display,
                    result=True,
                ),
            ],
            active=alpha_active,
            note=alpha_note,
            check={
                "kind": "alpha",
                "mean_p": mean_p,
                "mean_b": mean_b,
                "beta": beta,
                "days": TRADING_DAYS,
                "result": alpha,
                "name": bench_name,
            },
        )
        guides["beta"] = _pack(
            "beta",
            beta_display,
            [
                _step(
                    "Overlapping days",
                    f"The same alignment used for alpha versus {bench_name}.",
                    str(observations or 0),
                ),
                _step(
                    "Beta",
                    "Cov(daily portfolio return, daily benchmark return) / Var(daily benchmark return).",
                    beta_display,
                    result=True,
                ),
            ],
            active=beta_active,
            note=beta_note,
            check={"kind": "beta", "beta": beta, "name": bench_name, "observations": observations},
        )
    else:
        guides["alpha"] = _pack(
            "alpha",
            alpha_display,
            [
                _step(
                    "Annualized alpha",
                    "Not enough overlapping benchmark history.",
                    alpha_display,
                    result=True,
                )
            ],
            active=None,
            note="No benchmark relation was available.",
            check={"kind": "alpha", "alpha": alpha, "beta": beta},
        )
        guides["beta"] = _pack(
            "beta",
            beta_display,
            [_step("Beta", "Not enough overlapping benchmark history.", beta_display, result=True)],
            active=None,
            note="No benchmark relation was available.",
            check={"kind": "beta", "beta": beta},
        )

    mdd, mdd_start, mdd_end = _max_drawdown(daily)
    wealth = (1 + daily).cumprod() if not daily.empty else pd.Series(dtype=float)
    peak = float(wealth.loc[mdd_start]) if mdd_start is not None and not wealth.empty else None
    trough = float(wealth.loc[mdd_end]) if mdd_end is not None and not wealth.empty else None
    mdd_display = _fmt_pct(float(risk.max_drawdown))
    mdd_active, mdd_note = _band_for("max_drawdown", float(risk.max_drawdown), ctx)
    mdd_steps = []
    if mdd_start is not None and mdd_end is not None and peak is not None and trough is not None:
        mdd_steps.extend(
            [
                _step(
                    "Peak",
                    f"Time-weighted wealth index on {pd.Timestamp(mdd_start).date().isoformat()}.",
                    f"{peak:,.6f}",
                ),
                _step(
                    "Trough",
                    f"Wealth index on {pd.Timestamp(mdd_end).date().isoformat()}, before the next peak.",
                    f"{trough:,.6f}",
                ),
            ]
        )
    mdd_steps.append(
        _step(
            "Maximum drawdown",
            "Trough / peak − 1 on the time-weighted wealth index.",
            mdd_display,
            result=True,
        )
    )
    guides["max_drawdown"] = _pack(
        "max_drawdown",
        mdd_display,
        mdd_steps,
        active=mdd_active,
        note=mdd_note,
        check={
            "kind": "mdd",
            "peak": peak,
            "trough": trough,
            "result": float(risk.max_drawdown),
            "engine": mdd,
        },
    )

    annual = _annualized_return(daily)
    calmar = _finite(risk.calmar)
    calmar_display = _fmt_num(calmar)
    calmar_active, calmar_note = _band_for("calmar", calmar, ctx)
    guides["calmar"] = _pack(
        "calmar",
        calmar_display,
        [
            _step(
                "Annualized TWR",
                "Compound growth of the daily TWR chain over the holding period.",
                _fmt_pct(annual),
            ),
            _step(
                "Maximum drawdown",
                "The denominator, as a positive magnitude.",
                _fmt_pct(abs(float(risk.max_drawdown)), sign=False),
            ),
            _step(
                "Calmar ratio",
                "Annualized TWR / |maximum drawdown|.",
                calmar_display,
                result=True,
            ),
        ],
        active=calmar_active,
        note=calmar_note,
        check={
            "kind": "calmar",
            "annual": annual,
            "mdd": float(risk.max_drawdown),
            "result": calmar,
        },
    )

    var = float(risk.var_95_daily)
    var_display = _fmt_pct(var)
    var_active, var_note = _band_for("var_95", var, ctx)
    guides["var_95"] = _pack(
        "var_95",
        var_display,
        [
            _step("Daily returns", "The empirical distribution of daily TWR.", f"N = {len(daily)}"),
            _step(
                "Daily VaR (95%)",
                "Linear-interpolated 5th percentile. Losses this large or worse occurred on about 1 day in 20.",
                var_display,
                result=True,
            ),
        ],
        active=var_active,
        note=var_note,
        check={"kind": "var", "n": int(len(daily)), "result": var},
    )

    monthly = monthly_returns(daily)
    best = _finite(risk.best_month)
    worst = _finite(risk.worst_month)
    best_label = "—"
    worst_label = "—"
    if not monthly.empty and best is not None:
        best_label = pd.Timestamp(monthly.idxmax()).strftime("%b %Y")
    if not monthly.empty and worst is not None:
        worst_label = pd.Timestamp(monthly.idxmin()).strftime("%b %Y")
    best_display = _fmt_pct(best)
    worst_display = _fmt_pct(worst)
    best_active, best_note = _band_for("best_month", best, ctx)
    worst_active, worst_note = _band_for("worst_month", worst, ctx)
    guides["best_month"] = _pack(
        "best_month",
        best_display,
        [
            _step(
                "Calendar months",
                "Each month compounds that month's daily TWR.",
                f"{len(monthly)} months",
            ),
            _step("Highest month", best_label, best_display, result=True),
        ],
        active=best_active,
        note=best_note,
        check={"kind": "best_month", "label": best_label, "result": best},
    )
    guides["worst_month"] = _pack(
        "worst_month",
        worst_display,
        [
            _step(
                "Calendar months",
                "The same monthly TWR series as the best month.",
                f"{len(monthly)} months",
            ),
            _step("Lowest month", worst_label, worst_display, result=True),
        ],
        active=worst_active,
        note=worst_note,
        check={"kind": "worst_month", "label": worst_label, "result": worst},
    )

    stats = data.trade_stats or {}
    closed = int(stats.get("closed_lots") or 0)
    wins = int(stats.get("winning_lots") or 0)
    win_rate = _finite(float(stats["win_rate"])) if stats.get("win_rate") is not None else None
    profit_factor = (
        _finite(float(stats["profit_factor"])) if stats.get("profit_factor") is not None else None
    )
    matches = list(data.pit38.fifo_matches) if data.pit38 is not None else []
    gross_profit = float(sum(item.gain_loss_pln for item in matches if item.gain_loss_pln > 0))
    gross_loss = float(sum(item.gain_loss_pln for item in matches if item.gain_loss_pln < 0))
    win_display = _fmt_pct(win_rate, sign=False) if win_rate is not None else "—"
    pf_display = _fmt_num(profit_factor) if profit_factor is not None else "—"
    win_active, win_note = _band_for("win_rate", win_rate, ctx)
    pf_active, pf_note = _band_for("profit_factor", profit_factor, ctx)
    guides["win_rate"] = _pack(
        "win_rate",
        win_display,
        [
            _step("Winning lots", "Closed FIFO slices with a positive PLN result.", str(wins)),
            _step(
                "Closed lots",
                "Every matched sale slice, including losses and flat results.",
                str(closed),
            ),
            _step("Win rate", "Winning lots / closed lots.", win_display, result=True),
        ],
        active=win_active,
        note=win_note,
        check={"kind": "win_rate", "wins": wins, "closed": closed, "result": win_rate},
    )
    guides["profit_factor"] = _pack(
        "profit_factor",
        pf_display,
        [
            _step("Gross profit", "Sum of profitable closed slices.", _money(gross_profit, "PLN")),
            _step(
                "Gross loss",
                "Sum of losing closed slices, kept as a negative total.",
                _money(gross_loss, "PLN"),
            ),
            _step(
                "Profit factor",
                "Gross profit / |gross loss|.",
                pf_display,
                result=True,
            ),
        ],
        active=pf_active,
        note=pf_note,
        check={
            "kind": "profit_factor",
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "result": profit_factor,
        },
    )

    converted = float(data.conversion_stats.get("total_pln_converted", 0.0) or 0.0)
    fee = float(data.conversion_stats.get("total_loss_pln", 0.0) or 0.0)
    fee_display = _money(fee, "PLN")
    guides["fx_conversion_cost"] = _pack(
        "fx_conversion_cost",
        fee_display,
        [
            _step(
                "PLN converted",
                "Sum of PLN spent on external conversions into another account currency.",
                _money(converted, "PLN"),
            ),
            _step(
                "Estimated fee",
                "0.5% of converted PLN. The export does not state the fee; it is not deducted again from NAV.",
                fee_display,
                result=True,
            ),
        ],
        active=None,
        note="",
        check={"kind": "fee", "converted": converted, "result": fee},
    )

    guides["investment_gain"] = _fx_guide(data, "investment_gain")
    guides["fx_gain"] = _fx_guide(data, "fx_gain")
    return guides


def _fx_guide(data: Any, key: str) -> dict[str, Any]:
    attribution = data.attribution
    column = "investment_gain_pln" if key == "investment_gain" else "fx_gain_pln"
    total = float(getattr(attribution, column))
    display = _money(total, "PLN")
    steps: list[dict[str, Any]] = []
    parts: list[float] = []
    frame = attribution.by_currency
    if frame is not None and not frame.empty:
        for _, row in frame.iterrows():
            amount = float(row[column])
            parts.append(amount)
            if key == "investment_gain":
                detail = (
                    f"({_fmt_num(float(row['current_value_local']), 2)} − "
                    f"{_fmt_num(float(row['units_received']), 2)}) × "
                    f"{_fmt_num(float(row['current_rate']), 4)}"
                )
            else:
                detail = (
                    f"{_fmt_num(float(row['units_received']), 2)} × "
                    f"{_fmt_num(float(row['current_rate']), 4)} − "
                    f"{_fmt_num(float(row['pln_spent']), 2)}"
                )
            steps.append(_step(str(row["currency"]), detail, _money(amount, "PLN")))
    steps.append(
        _step(
            "Total",
            "Sum across PLN, USD, and EUR buckets.",
            display,
            result=True,
        )
    )
    return _pack(
        key,
        display,
        steps,
        active=None,
        check={"kind": "fx_sum", "parts": parts, "result": total},
    )


def _pit_scope_guides(
    summary: Pit38YearSummary,
    matches: list[Any],
    dividends: list[Any],
) -> dict[str, dict[str, Any]]:
    revenue = float(summary.section_c_revenue_pln)
    costs = float(summary.section_c_costs_pln)
    commissions = float(summary.section_c_commissions_pln)
    net = float(summary.section_c_net_pln)
    wht = float(summary.dividends_wht_credit_pln)
    wht_paid = float(summary.dividends_wht_paid_pln)
    div_due = float(summary.dividends_tax_due_pln)
    sec_tax = float(summary.section_c_tax_pln)
    total_tax = float(summary.total_tax_due_pln)
    lots = int(summary.sold_lots_count)
    div_count = int(summary.dividends_count)
    ledger_revenue = _q2(sum((Decimal(str(item.revenue_pln)) for item in matches), Decimal("0")))
    ledger_costs = _q2(
        sum((Decimal(str(item.deductible_cost_pln)) for item in matches), Decimal("0"))
    )
    wht_sum = _q2(sum((Decimal(str(item.wht_credit_pln)) for item in dividends), Decimal("0")))

    def money(value: float) -> str:
        return _money(value, "PLN")

    income_active, income_note = _band_for("pit38_income", net, {})
    revenue_display = money(revenue)
    costs_display = money(costs)
    income_display = f"{'+' if net > 0 else ''}{money(net)}" if net != 0 else money(0.0)
    # Dashboard uses a sign prefix only when net > 0 in the PIT card, and _fmt_num otherwise
    # includes the minus sign. Match _stat_card: f"{net_sign}{_fmt_num(net)} PLN" with net_sign '+' if net > 0.
    if net > 0:
        income_display = f"+{_fmt_num(net)} PLN"
    else:
        income_display = f"{_fmt_num(net)} PLN"
    wht_display = money(wht)
    tax_display = money(total_tax)
    return {
        "pit38_revenue": _pack(
            "pit38_revenue",
            revenue_display,
            [
                _step("Matched sales", "FIFO lot slices closed in this scope.", str(lots)),
                _step(
                    "Ledger sum",
                    "Each slice's foreign proceeds × the NBP Table A rate from the previous business day.",
                    money(float(ledger_revenue)),
                ),
                _step(
                    "Section C revenue",
                    "The sum shown on the PIT-38 card.",
                    revenue_display,
                    result=True,
                ),
            ],
            active=None,
            check={"kind": "pit_revenue", "ledger": float(ledger_revenue), "result": revenue},
        ),
        "pit38_costs": _pack(
            "pit38_costs",
            costs_display,
            [
                _step(
                    "FIFO deductible costs",
                    "Acquisition cost at each lot's own buy-date D−1 NBP rate, plus commissions on those lots.",
                    money(float(ledger_costs)),
                ),
                _step(
                    "Commissions in the cost total",
                    "Buy and sell commissions included in deductible costs, plus any standalone commission.",
                    money(commissions),
                ),
                _step(
                    "Deductible costs",
                    "The cost figure on the PIT-38 card.",
                    costs_display,
                    result=True,
                ),
            ],
            active=None,
            check={"kind": "pit_costs", "ledger": float(ledger_costs), "result": costs},
        ),
        "pit38_income": _pack(
            "pit38_income",
            income_display,
            [
                _step("Section C revenue", "Gross sale proceeds in PLN.", money(revenue)),
                _step("Deductible costs", "FIFO cost plus commissions.", money(costs)),
                _step(
                    "Profit / loss",
                    "Revenue − costs. A positive result is taxable income; a negative result is a loss.",
                    income_display,
                    result=True,
                ),
            ],
            active=income_active,
            note=income_note,
            check={"kind": "pit_income", "revenue": revenue, "costs": costs, "result": net},
        ),
        "pit38_wht_credit": _pack(
            "pit38_wht_credit",
            wht_display,
            [
                _step("Dividend payments", "Payments in this scope.", str(div_count)),
                _step(
                    "Foreign tax paid",
                    "Withholding tax converted at the dividend's D−1 NBP rate, before the 19% cap.",
                    money(wht_paid),
                ),
                _step(
                    "Creditable amount",
                    "Sum of min(foreign tax, 19% of that dividend) across payments.",
                    wht_display,
                    result=True,
                ),
            ],
            active=None,
            check={"kind": "pit_wht", "ledger": float(wht_sum), "result": wht},
        ),
        "pit38_total_tax": _pack(
            "pit38_total_tax",
            tax_display,
            [
                _step(
                    "Section C tax",
                    "19% of positive Section C income, in grosze. A loss contributes 0.",
                    money(sec_tax),
                ),
                _step(
                    "Dividend tax still due",
                    "Polish 19% dividend tax minus the foreign tax credit, summed per payment.",
                    money(div_due),
                ),
                _step(
                    "Total PIT-38 tax",
                    "Section C tax + dividend tax still due. This is the headline card, before the full-PLN statutory rounding shown underneath it.",
                    tax_display,
                    result=True,
                ),
            ],
            active=None,
            check={
                "kind": "pit_tax",
                "section_c": sec_tax,
                "dividend": div_due,
                "result": total_tax,
            },
        ),
    }


def build_indicator_guides(data: Any) -> dict[str, Any]:
    """Return dashboard-reconciled guide copy for every defined indicator."""
    guides = _core_guides(data)
    pit = data.pit38
    scopes: dict[str, dict[str, dict[str, Any]]] = {}
    default_scope = "all"
    if pit is not None:
        default_scope = str(pit.latest_year) if pit.latest_year is not None else "all"
        for year, summary in pit.by_year.items():
            year_matches = [item for item in pit.fifo_matches if item.tax_year == year]
            year_divs = [item for item in pit.dividends if item.tax_year == year]
            scopes[str(year)] = _pit_scope_guides(summary, year_matches, year_divs)
        scopes["all"] = _pit_scope_guides(
            pit.all_years_summary, list(pit.fifo_matches), list(pit.dividends)
        )
        chosen = scopes.get(default_scope) or scopes.get("all") or {}
        guides.update(chosen)
    missing = set(METRIC_DEFINITIONS) - set(guides)
    if missing:
        raise KeyError(f"Indicator guides missing: {sorted(missing)}")
    for guide in guides.values():
        if not guide["steps"] or guide["steps"][-1]["value"] != guide["display_value"]:
            raise ValueError(f"Guide {guide['key']} does not end on its dashboard value")
    return {
        "order": list(METRIC_DEFINITIONS),
        "default_pit_scope": default_scope,
        "indicators": guides,
        "pit_scopes": scopes,
    }
