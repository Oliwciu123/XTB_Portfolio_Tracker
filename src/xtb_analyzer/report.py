"""Professional interactive HTML report for the XTB portfolio.

``generate_report()`` is the single entry point: it loads XLSX/CSV exports,
computes every metric and renders a self-contained ``report.html`` with
interactive Plotly charts with Plotly.js embedded for offline viewing.
"""

from __future__ import annotations

import html as html_lib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from xtb_analyzer.attribution import FxAttribution, compute_fx_attribution
from xtb_analyzer.benchmark import (
    BENCHMARK_TICKERS,
    benchmark_in_currency,
    build_benchmark_suite,
    build_deposit_benchmark,
    instrument_currency,
)
from xtb_analyzer.cash import income_by_currency
from xtb_analyzer.charts import (
    BENCHMARK_META,
    PLOTLY_SHOW_CONFIG,
    _format_decimal,
    build_return_comparison_figure,
    plot_company_pnl,
    plot_currency_allocation,
    plot_holdings_allocation,
    plot_monthly_returns_heatmap,
    plot_nav_with_deposits,
    plot_sector_allocation,
    prepare_return_comparison_data,
)
from xtb_analyzer.flows import analyze_conversion_losses, attach_deposits_to_nav, conversion_summary
from xtb_analyzer.fx import fetch_fx_rates
from xtb_analyzer.market_data import MarketData
from xtb_analyzer.metrics import company_pnl_summary, format_company_pnl_table
from xtb_analyzer.models import Account
from xtb_analyzer.parser import discover_export_files, load_accounts
from xtb_analyzer.portfolio import build_nav_series
from xtb_analyzer.prices import fetch_benchmarks, xtb_to_yahoo
from xtb_analyzer.returns import ReturnMeasures, compute_return_measures, twr_daily_returns
from xtb_analyzer.risk import RiskStats, compute_risk_stats
from xtb_analyzer.sectors import enrich_positions_with_sectors, sector_allocation


@lru_cache(maxsize=1)
def _plotly_bundle() -> str:
    return get_plotlyjs()


@dataclass
class ReportData:
    accounts: list[Account]
    nav: pd.DataFrame
    positions: pd.DataFrame
    sector_alloc: pd.DataFrame
    measures: ReturnMeasures
    risk: RiskStats
    attribution: FxAttribution
    twr_returns: pd.Series
    benchmarks: dict[str, pd.Series]
    conversion_losses: pd.DataFrame
    conversion_stats: dict[str, float]
    income: pd.DataFrame
    currency: str
    company_pnl: pd.DataFrame = field(default_factory=pd.DataFrame)
    custom_benchmarks: dict[str, dict[str, object]] = field(default_factory=dict)
    is_demo: bool = False


def build_custom_benchmark_payload(
    accounts: list[Account],
    nav: pd.DataFrame,
    ticker_input: str,
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
    index_series: pd.Series | None = None,
) -> dict[str, object]:
    """Simulate a deposit-matched benchmark for any Yahoo Finance / XTB ticker and format for Plotly."""
    raw = (ticker_input or "").strip().upper()
    if not raw:
        raise ValueError("Enter an instrument symbol, such as AAPL, NVDA, or BTC-USD.")
    import re

    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=_-]{0,39}", raw):
        raise ValueError("Invalid ticker. Use a Yahoo Finance symbol, such as XTB.WA or BTC-USD.")

    yf_ticker = xtb_to_yahoo(raw)
    if index_series is None:
        start = (nav.index[0] - pd.Timedelta(days=7)).date().isoformat()
        end = (nav.index[-1] + pd.Timedelta(days=1)).date().isoformat()
        fetched = fetch_benchmarks(
            [yf_ticker],
            start=start,
            end=end,
            use_cache=use_cache,
            refresh_latest=refresh_latest,
        )
        index_series = fetched.get(yf_ticker, pd.Series(dtype=float))

    if index_series is None or index_series.dropna().empty:
        raise ValueError(f"No historical data found for symbol '{raw}' ({yf_ticker}).")

    key = f"custom_{yf_ticker.lower().replace('^', '').replace('-', '_').replace('.', '_')}"
    sim_series = build_deposit_benchmark(
        accounts,
        nav.index,
        currency=currency,
        ticker=yf_ticker,
        series_name=key,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
        index_series=index_series,
        quote_currency=instrument_currency(yf_ticker),
    )
    if sim_series.dropna().empty:
        raise ValueError(
            f"Historia '{raw}' does not cover the full portfolio period, or FX rates are missing."
        )

    comp = prepare_return_comparison_data(nav, {key: sim_series}, currency=currency)
    monthly = comp.benchmarks_monthly[key]
    final_ret = float(comp.final_returns[key])
    label = raw if raw == yf_ticker else f"{raw} ({yf_ticker})"

    return {
        "key": key,
        "ticker": raw,
        "yf_ticker": yf_ticker,
        "label": label,
        "x": [pd.Timestamp(ts).strftime("%Y-%m-%d") for ts in monthly.index],
        "y": [round(float(v), 2) for v in monthly.tolist()],
        "final_return": round(final_ret, 2),
        "trace_name": f"{label} ({_format_decimal(final_ret)}%)",
    }


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def collect_report_data(
    accounts: list[Account],
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
    on_progress: Callable[[float, str], None] | None = None,
    market_data: MarketData | None = None,
) -> ReportData:
    currency = currency.lower()

    def progress(fraction: float, message: str) -> None:
        if on_progress is not None:
            on_progress(fraction, message)

    progress(0.35, "Fetching prices and exchange rates...")
    dates = [tx.timestamp for account in accounts for tx in account.transactions]
    if not dates:
        raise ValueError("No transactions found. Import the complete XTB cash-operation history.")
    fx = (
        market_data.fx
        if market_data is not None
        else fetch_fx_rates(
            start=(pd.Timestamp(min(dates)) - pd.Timedelta(days=7)).date().isoformat(),
            use_cache=use_cache,
            refresh_latest=refresh_latest,
        )
    )
    nav_kwargs = (
        {"prices": market_data.prices, "quote_currencies": market_data.quote_currencies}
        if market_data is not None
        else {}
    )
    nav, _, positions = build_nav_series(
        accounts, use_cache=use_cache, live_prices=refresh_latest, fx=fx, **nav_kwargs
    )
    progress(0.55, "Calculating cash flows and returns...")
    nav = attach_deposits_to_nav(nav, accounts, use_cache=use_cache, fx=fx)
    if market_data is None:
        positions = enrich_positions_with_sectors(positions)
    elif not positions.empty:
        positions = positions.assign(
            sector=positions["symbol"].map(market_data.sectors).fillna("Unknown")
        )

    measures = compute_return_measures(accounts, nav, currency, fx=fx, use_cache=use_cache)
    twr_returns = twr_daily_returns(nav, currency)
    attribution = compute_fx_attribution(accounts, nav, fx=fx, use_cache=use_cache)

    progress(0.68, "Comparing benchmarks...")
    start = (
        ((twr_returns.index[0] if not twr_returns.empty else nav.index[0]) - pd.Timedelta(days=7))
        .date()
        .isoformat()
    )
    end = (nav.index[-1] + pd.Timedelta(days=1)).date().isoformat()
    index_levels = (
        market_data.benchmarks
        if market_data is not None
        else fetch_benchmarks(
            list(BENCHMARK_TICKERS.values()),
            start=start,
            end=end,
            use_cache=use_cache,
            refresh_latest=refresh_latest,
        )
    )
    benchmark_specs = (
        {key: key for key in index_levels} if market_data is not None else BENCHMARK_TICKERS
    )
    risk = compute_risk_stats(
        twr_returns,
        benchmarks={
            BENCHMARK_META[key][0]: benchmark_in_currency(
                index_levels.get(ticker, pd.Series(dtype=float)),
                market_data.benchmark_currencies.get(key, "USD") if market_data else "USD",
                currency,
                fx,
            )
            for key, ticker in benchmark_specs.items()
        },
    )

    benchmarks = (
        {
            key: build_deposit_benchmark(
                accounts,
                nav.index,
                currency,
                index_series=levels,
                fx=fx,
                series_name=key,
                quote_currency=market_data.benchmark_currencies.get(key, "USD"),
            )
            for key, levels in index_levels.items()
        }
        if market_data is not None
        else build_benchmark_suite(
            accounts,
            nav.index,
            currency=currency,
            use_cache=use_cache,
            refresh_latest=refresh_latest,
            fx=fx,
            indices=index_levels,
        )
    )

    conversion_losses = analyze_conversion_losses(accounts, fx=fx)
    company_pnl = company_pnl_summary(
        accounts, positions, currency=currency, fx_row=fx.iloc[-1], use_cache=use_cache
    )

    custom_benchmarks: dict[str, dict[str, object]] = {}

    progress(0.88, "Building the report...")

    return ReportData(
        accounts=accounts,
        nav=nav,
        positions=positions,
        sector_alloc=sector_allocation(positions),
        measures=measures,
        risk=risk,
        attribution=attribution,
        twr_returns=twr_returns,
        benchmarks=benchmarks,
        conversion_losses=conversion_losses,
        conversion_stats=conversion_summary(conversion_losses),
        income=income_by_currency(accounts),
        currency=currency,
        company_pnl=company_pnl,
        custom_benchmarks=custom_benchmarks,
        is_demo=market_data.synthetic if market_data is not None else False,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}"


def _fmt_pct(value: float | None, decimals: int = 2, sign: bool = True) -> str:
    if value is None or pd.isna(value):
        return "—"
    pattern = f"{{:+.{decimals}f}}%" if sign else f"{{:.{decimals}f}}%"
    return pattern.format(value * 100)


_FIXED_CHARTS = {"chart-monthly", "chart-pnl", "chart-holdings"}


def _report_figure(fig: go.Figure, plot_id: str | None = None) -> go.Figure:
    fig = go.Figure(fig)
    fig.update_layout(width=None, autosize=True, title_text="", margin_t=24)
    if plot_id in _FIXED_CHARTS:
        fig.update_layout(dragmode=False)
        fig.update_xaxes(fixedrange=True)
        fig.update_yaxes(fixedrange=True)
    return fig


def _chart_heading(fig: go.Figure) -> str:
    import re

    parts = re.split(r"<br\s*/?>", fig.layout.title.text or "", maxsplit=1)

    def clean(text):
        return html_lib.escape(html_lib.unescape(re.sub(r"<[^>]+>", "", text)))

    subtitle = f"<p>{clean(parts[1])}</p>" if len(parts) > 1 else ""
    return f"<div class='chart-heading'><h3>{clean(parts[0])}</h3>{subtitle}</div>"


def _fig_html(fig: go.Figure, plot_id: str | None = None) -> str:
    fig = _report_figure(fig, plot_id)
    config = dict(PLOTLY_SHOW_CONFIG)
    if plot_id in _FIXED_CHARTS:
        config.update(scrollZoom=False, doubleClick=False)
    return fig.to_html(full_html=False, include_plotlyjs=False, config=config, div_id=plot_id)


def _chart(fig: go.Figure, extra_class: str = "", plot_id: str | None = None) -> str:
    cls = f"chart {extra_class}".strip()
    controls = ""
    if plot_id:
        if plot_id in ("chart-nav", "chart-benchmark"):
            controls += (
                "<div class='chart-ranges' role='group' aria-label='Time range'>"
                + "".join(
                    f"<button type='button' data-chart-range='{period}'>{label}</button>"
                    for period, label in (
                        ("1d", "1D"),
                        ("1w", "1W"),
                        ("1m", "1M"),
                        ("3m", "3M"),
                        ("6m", "6M"),
                        ("ytd", "YTD"),
                        ("1y", "1Y"),
                        ("3y", "3Y"),
                        ("5y", "5Y"),
                        ("all", "All"),
                    )
                )
                + "</div>"
            )
        controls += "<div class='chart-actions'>"
        if plot_id not in _FIXED_CHARTS | {"chart-currency", "chart-sector"}:
            controls += "<button type='button' data-chart-reset>Reset view</button>"
        controls += "<button type='button' data-chart-export>Save PNG</button></div>"
        controls = f"<div class='chart-controls' data-chart-target='{plot_id}'>{controls}</div>"
    return f"<div class='{cls}'>{_chart_heading(fig)}{controls}{_fig_html(fig, plot_id)}</div>"


def _table_html(frame: pd.DataFrame, float_decimals: int = 2, table_id: str = "") -> str:
    if frame.empty:
        return "<p class='muted'>No data available.</p>"
    formatted = frame.copy()
    for column in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda v: _fmt_num(v, float_decimals))
    id_attr = f" id='{table_id}'" if table_id else ""
    table = formatted.to_html(index=False, classes="data", border=0, escape=True, na_rep="—")
    if id_attr:
        table = table.replace("<table ", f"<table{id_attr} ", 1)
    return f"<div class='table-wrap'>{table}</div>"


def _tone(value: float | None) -> str:
    if value is None:
        return "neutral"
    return "pos" if value >= 0 else "neg"


def _stat_card(
    label: str, value: str, sub: str = "", tone: str = "neutral", big: bool = False
) -> str:
    size = " stat-big" if big else ""
    sub_html = f"<div class='stat-sub'>{html_lib.escape(sub)}</div>" if sub else ""
    return (
        f"<div class='stat{size} stat-{tone}'>"
        f"<div class='stat-label'>{html_lib.escape(label)}</div>"
        f"<div class='stat-value'>{html_lib.escape(value)}</div>"
        f"{sub_html}"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _kpi_section(data: ReportData) -> str:
    measures = data.measures
    currency = measures.currency
    cards = [
        _stat_card(
            "Portfolio NAV",
            f"{_fmt_num(measures.final_value)} {currency}",
            "current account valuation",
            big=True,
        ),
        _stat_card(
            "Gross contributions",
            f"{_fmt_num(measures.invested)} {currency}",
            f"withdrawals: {_fmt_num(measures.withdrawn)} {currency}",
            big=True,
        ),
        _stat_card(
            "Profit / loss",
            f"{_fmt_num(measures.gain)} {currency}",
            "NAV + withdrawals − contributions",
            _tone(measures.gain),
            big=True,
        ),
        _stat_card(
            "ROI",
            _fmt_pct(measures.roi),
            "profit divided by gross contributions",
            _tone(measures.roi),
            big=True,
        ),
        _stat_card(
            "MWR (XIRR)",
            _fmt_pct(measures.mwr),
            f"annualized: {_fmt_pct(measures.xirr)}",
            _tone(measures.mwr),
            big=True,
        ),
        _stat_card(
            "TWR",
            _fmt_pct(measures.twr),
            f"annualized: {_fmt_pct(measures.twr_annualized)}",
            _tone(measures.twr),
            big=True,
        ),
    ]
    return "<div class='stat-grid kpi'>" + "".join(cards) + "</div>"


def _risk_cards_html(risk: RiskStats) -> str:
    drawdown_period = (
        f"{risk.max_drawdown_start} → {risk.max_drawdown_end}"
        if risk.max_drawdown_start and risk.max_drawdown_end
        else "based on TWR"
    )
    primary_bench = next(
        (b for b in risk.benchmarks if b.beta is not None or b.alpha_annual is not None),
        risk.benchmarks[0] if risk.benchmarks else None,
    )
    alpha_val = primary_bench.alpha_annual if primary_bench else None
    beta_val = primary_bench.beta if primary_bench else None
    bench_name = primary_bench.name if primary_bench else "S&P 500 TR"

    cards = [
        _stat_card(
            "Annualized volatility",
            _fmt_pct(risk.volatility_annual, sign=False),
            "standard deviation of daily returns",
        ),
        _stat_card("Sharpe ratio", _fmt_num(risk.sharpe), "return relative to volatility"),
        _stat_card("Sortino ratio", _fmt_num(risk.sortino), "return relative to downside risk"),
        _stat_card(
            "Annualized alpha", _fmt_pct(alpha_val), f"relative to {bench_name}", _tone(alpha_val)
        ),
        _stat_card("Beta", _fmt_num(beta_val), f"sensitivity relative to {bench_name}"),
        _stat_card(
            "Maximum drawdown",
            _fmt_pct(risk.max_drawdown),
            drawdown_period,
            _tone(risk.max_drawdown),
        ),
        _stat_card("Best month", _fmt_pct(risk.best_month), tone="pos"),
        _stat_card("Worst month", _fmt_pct(risk.worst_month), tone="neg"),
    ]
    return "<div class='stat-grid'>" + "".join(cards) + "</div>"


def _conversion_summary_section(stats: dict[str, float], losses: pd.DataFrame) -> str:
    total_loss = float(stats.get("total_loss_pln", 0.0) or 0.0)
    total_converted = float(stats.get("total_pln_converted", 0.0) or 0.0)
    ops_count = len(losses) if losses is not None else 0

    cards = [
        _stat_card(
            "Estimated FX conversion cost (0.5%)",
            f"{_fmt_num(total_loss)} PLN",
            f"assumed fee · conversions: {ops_count}",
            "neg" if total_loss > 0 else "neutral",
            big=True,
        ),
        _stat_card(
            "Total converted capital",
            f"{_fmt_num(total_converted)} PLN",
            "total PLN conversion volume",
            "neutral",
            big=True,
        ),
    ]
    return "<div class='stat-grid attribution'>" + "".join(cards) + "</div>"


def _attribution_section(attribution: FxAttribution) -> str:
    total = attribution.total_gain_pln
    inv_share = attribution.investment_gain_pln / total if total else None
    fx_share = attribution.fx_gain_pln / total if total else None

    cards = [
        _stat_card(
            "Investment gain",
            f"{_fmt_num(attribution.investment_gain_pln)} PLN",
            f"{_fmt_pct(inv_share, 0, sign=False)} of total gain" if inv_share is not None else "",
            _tone(attribution.investment_gain_pln),
            big=True,
        ),
        _stat_card(
            "FX gain",
            f"{_fmt_num(attribution.fx_gain_pln)} PLN",
            f"{_fmt_pct(fx_share, 0, sign=False)} of total gain" if fx_share is not None else "",
            _tone(attribution.fx_gain_pln),
            big=True,
        ),
        _stat_card(
            "Total gain",
            f"{_fmt_num(total)} PLN",
            "investment + FX",
            _tone(total),
            big=True,
        ),
    ]
    grid = "<div class='stat-grid attribution'>" + "".join(cards) + "</div>"

    if attribution.by_currency.empty:
        return grid

    frame = attribution.by_currency.copy()
    frame["fx_change"] = frame.apply(
        lambda row: (
            row["current_rate"] / row["avg_deposit_rate"] - 1 if row["avg_deposit_rate"] else None
        ),
        axis=1,
    )
    display = pd.DataFrame(
        {
            "Currency": frame["currency"],
            "PLN capital cost": frame["pln_spent"].map(_fmt_num),
            "Received": frame.apply(
                lambda r: f"{_fmt_num(r['units_received'])} {r['currency']}", axis=1
            ),
            "Average contribution FX": frame["avg_deposit_rate"].map(lambda v: _fmt_num(v, 4)),
            "Current FX": frame["current_rate"].map(lambda v: _fmt_num(v, 4)),
            "FX change": frame["fx_change"].map(_fmt_pct),
            "Investment gain": frame["investment_gain_pln"].map(lambda v: f"{_fmt_num(v)} PLN"),
            "FX gain": frame["fx_gain_pln"].map(lambda v: f"{_fmt_num(v)} PLN"),
            "Total": frame["total_gain_pln"].map(lambda v: f"{_fmt_num(v)} PLN"),
        }
    )
    return grid + _table_html(display)


def _income_table(income: pd.DataFrame) -> str:
    if income.empty:
        return "<p class='muted'>No dividends or interest in this period.</p>"
    frame = income.rename(
        columns={
            "currency": "Currency",
            "dividends": "Dividends",
            "interest": "Interest",
            "taxes": "Withholding taxes",
            "net_income": "Net income",
        }
    )
    return _table_html(frame)


_DESIGN_CSS = """
:root { --bg:#0b1221; --surface:#101e33; --card:#15253e; --border:#263c59; --accent:#818cf8; --accent-light:#a5b4fc; }
body { background:radial-gradient(ellipse at 10% 0%,#182d49 0%,transparent 45%),var(--bg); }
.hero-title-group h1 { letter-spacing:-1.3px; }
.panel-block { background:#101e33; border:1px solid #263c59; border-radius:22px; padding:26px; margin-top:24px; }
.panel-block h2 { color:#c7d2fe; }
.nav-cloud:nth-child(1) { border-top:3px solid #34d399; }
.nav-cloud:nth-child(2) { border-top:3px solid #a78bfa; }
.nav-cloud:nth-child(3) { border-top:3px solid #38bdf8; }
.nav-cloud:nth-child(4) { border-top:3px solid #fbbf24; }
.nav-cloud.active { background:#233456; border-color:#818cf8; }
.stat { border-radius:16px; border:1px solid #2b405d; }
.kpi .stat:nth-child(1) { background:#163b39; }
.kpi .stat:nth-child(2) { background:#203e60; }
.kpi .stat:nth-child(3) { background:#34305a; }
.kpi .stat:nth-child(4) { background:#3d3441; }
.chart { border-radius:16px; background:#101e33; }
.search-input:focus { outline:2px solid #a78bfa; outline-offset:3px; }
button:focus-visible,a:focus-visible { outline:2px solid #38bdf8; outline-offset:4px; }
.bench-feedback { min-height:24px; color:#c4b5fd; }
.js-plotly-plot .plotly .modebar { background:#15253e!important; border-radius:8px; }
.js-plotly-plot .plotly .modebar { display:none!important; }
.chart-heading { padding:22px 24px 4px; text-align:left; }
.chart-heading h3 { margin:0; font-size:17px; line-height:1.5; color:#e2e8f0; overflow-wrap:anywhere; }
.chart-heading p { margin:6px 0 0; color:#94a3b8; font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.chart-controls { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; padding:12px 24px; }
.chart-ranges,.chart-actions { display:flex; flex-wrap:wrap; gap:6px; }
.chart-controls button { font:inherit; font-size:12px; cursor:pointer; border:1px solid transparent; border-radius:8px; padding:7px 12px; background:#172840; color:#a7b8d1; }
.chart-controls button:hover,.chart-controls button.active { background:#293c60; color:#e0e7ff; border-color:#52638f; }
@media(max-width:700px) { .chart-heading { padding:16px 12px 4px; } .chart-controls { padding:10px 12px; } .chart-actions { margin-left:auto; } }
@media(max-width:700px) { .panel-block { padding:12px; border-radius:16px; } .container { padding:0 12px 32px; } }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { animation:none!important; transition:none!important; scroll-behavior:auto!important; } }
@media(min-width:1100px) {
  .container { max-width:1520px; padding:0 28px 60px; }
  header.hero { flex-direction:row; justify-content:space-between; text-align:left; padding:14px 0; gap:16px; }
  .hero-title-group { align-items:flex-start; }
  .hero-title-group h1 { font-size:28px; text-align:left; margin-bottom:4px; }
  .hero-meta { font-size:12px; justify-content:flex-start; }
  .section-switcher-wrap { margin:10px 0 14px; }
  .switcher-header { margin-bottom:6px; }
  .view-mode-btn { padding:4px 10px; }
  .nav-cloud { padding:8px 16px; gap:2px; }
  .cloud-top { display:none; }
  .cloud-title { font-size:16px; }
  .panel-block { padding:16px 20px; margin:16px 0; }
  .panel-block h2 { font-size:18px; }
  .section-desc { margin-bottom:8px; font-size:12px; }
  .stat-grid.kpi { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; margin:10px 0 0; }
  .stat-grid.kpi .stat { min-width:0; max-width:none; padding:12px 8px; }
  .kpi .stat-value { font-size:18px; }
  .kpi .stat-label,.kpi .stat-sub { font-size:11px; }
}
"""

_CSS = """
:root {
  --bg: #0b0f17;
  --surface: #111827;
  --card: #151d2e;
  --card-hover: #1b253b;
  --card-inner: #0f1522;
  --border: #1e293b;
  --border-strong: #334155;
  --text: #f1f5f9;
  --muted: #94a3b8;
  --pos: #34d399;
  --pos-bg: rgba(52, 211, 153, 0.12);
  --neg: #f87171;
  --neg-bg: rgba(248, 113, 113, 0.12);
  --accent: #3b82f6;
  --accent-light: #60a5fa;
  --accent-glow: rgba(59, 130, 246, 0.16);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  line-height: 1.6;
  font-variant-numeric: tabular-nums;
  -webkit-font-smoothing: antialiased;
}
.container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 28px 80px;
}
header.hero {
  padding: 34px 0 22px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 16px;
}
.hero-title-group {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.hero-title-group h1 {
  margin: 0 0 8px;
  font-size: clamp(26px, 3vw, 34px);
  font-weight: 700;
  letter-spacing: -0.025em;
  color: var(--text);
  text-wrap: balance;
  text-align: center;
}
.hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px 12px;
  color: var(--muted);
  font-size: 13.5px;
}
.hero-meta b {
  color: var(--text);
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}
.meta-sep {
  color: var(--border-strong);
  user-select: none;
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.currency-switcher {
  display: inline-flex;
  align-items: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 3px;
  gap: 2px;
}
.currency-switch-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  padding: 0 8px 0 10px;
}
.currency-btn {
  appearance: none;
  background: transparent;
  border: none;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s ease;
  text-decoration: none;
}
.currency-btn:hover {
  color: var(--text);
}
.currency-btn.active {
  background: var(--accent);
  color: #ffffff;
}

/* Live Stats Toggle Button (Green when ON, Red when OFF) */
.live-trigger {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 10px;
  padding: 9px 16px;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}
.live-trigger.is-on {
  border-color: rgba(52, 211, 153, 0.45);
  background: rgba(52, 211, 153, 0.08);
}
.live-trigger.is-off {
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(248, 113, 113, 0.08);
}
.live-trigger:hover {
  transform: translateY(-1px);
}
.live-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
  transition: background 0.15s ease, box-shadow 0.15s ease;
}
.live-dot.on {
  background: var(--pos);
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.85);
}
.live-dot.off {
  background: var(--neg);
  box-shadow: 0 0 10px rgba(248, 113, 113, 0.85);
}

/* Interactive 4-Section Cloud Switcher (Clean, without bottom sub-captions) */
.section-switcher-wrap {
  margin: 24px 0 28px;
}
.switcher-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.switcher-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}
.view-mode-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.view-mode-btn:hover, .view-mode-btn.active {
  color: var(--text);
  border-color: var(--accent-light);
  background: var(--accent-glow);
}
.nav-clouds {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 1024px) {
  .nav-clouds { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .nav-clouds { grid-template-columns: 1fr; }
}
.nav-cloud {
  appearance: none;
  text-align: left;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 18px 20px;
  color: var(--text);
  font-family: inherit;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  transition: transform 0.16s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.16s ease, background 0.16s ease;
}
.nav-cloud:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  background: var(--card-hover);
}
.nav-cloud.active {
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.16) 0%, rgba(21, 29, 46, 0.95) 100%);
  border-color: var(--accent-light);
  box-shadow: 0 8px 24px -8px rgba(59, 130, 246, 0.35);
}
.cloud-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.cloud-step {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-light);
}
.cloud-arrow {
  font-size: 14px;
  color: var(--muted);
  transition: transform 0.16s ease, color 0.16s ease;
}
.nav-cloud.active .cloud-arrow, .nav-cloud:hover .cloud-arrow {
  transform: translateX(3px);
  color: var(--accent-light);
}
.cloud-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text);
}

/* Tab Panels */
.tab-panel {
  display: none;
  animation: panelFadeIn 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.tab-panel.active, body.show-all-sections .tab-panel {
  display: block;
}
body.show-all-sections .tab-panel {
  margin-bottom: 56px;
  padding-bottom: 36px;
  border-bottom: 1px solid var(--border);
}
@keyframes panelFadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel-block {
  margin: 30px 0;
}
.panel-block:first-child {
  margin-top: 6px;
}
h2 {
  font-size: 21px;
  font-weight: 700;
  margin: 0 0 6px;
  letter-spacing: -0.02em;
  text-wrap: balance;
  text-align: center;
}
h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 26px 0 8px;
  color: var(--text);
  text-align: center;
}
.section-desc {
  color: var(--muted);
  font-size: 14px;
  margin: 0 auto 16px;
  max-width: 820px;
  text-align: center;
}
.muted { color: var(--muted); font-size: 14px; }

/* Stat Grid (Centered rectangles) */
.stat-grid {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 14px;
  margin: 16px auto;
}
.stat-grid .stat {
  flex: 1 1 220px;
  max-width: 285px;
  min-width: 200px;
}
.stat-grid.kpi .stat {
  flex: 1 1 320px;
  max-width: 380px;
}
.stat-grid.attribution .stat {
  flex: 1 1 300px;
  max-width: 380px;
}
.stat {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.stat:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
}
.stat-label {
  color: var(--muted);
  font-size: 12.5px;
  font-weight: 600;
}
.stat-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  margin: 6px 0 4px;
  letter-spacing: -0.02em;
}
.stat-big .stat-value { font-size: 24px; }
.stat-sub { color: var(--muted); font-size: 12.5px; }
.stat-pos .stat-value { color: var(--pos); }
.stat-neg .stat-value { color: var(--neg); }

/* Interactive Controls Bar (Filters / Search / Custom Benchmark Picker) */
.interactive-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin: 14px auto 12px;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.filter-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.filter-btn {
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--muted);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.filter-btn:hover {
  color: var(--text);
  border-color: var(--border-strong);
}
.filter-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #ffffff;
}
.search-input {
  background: var(--card-inner);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 13px;
  font-family: inherit;
  min-width: 220px;
  outline: none;
  transition: border-color 0.15s ease;
}
.search-input:focus {
  border-color: var(--accent-light);
}
.custom-bench-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.preset-select {
  background: var(--card-inner);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 12.5px;
  font-family: inherit;
  outline: none;
  cursor: pointer;
}
.preset-select:focus {
  border-color: var(--accent-light);
}
.bench-add-btn {
  background: var(--accent);
  border: 1px solid var(--accent);
  color: #ffffff;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease;
}
.bench-add-btn:hover {
  background: #2563eb;
}
.bench-add-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}
.bench-feedback {
  font-size: 12.5px;
  color: var(--neg);
  margin-left: 4px;
}
.bench-catalog-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 14px;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.bench-cat-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.bench-cat-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  min-width: 115px;
}
.bench-quick-chip {
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--muted);
  border-radius: 7px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
}
.bench-quick-chip:hover {
  color: var(--text);
  border-color: var(--accent-light);
  background: var(--card-hover);
}
.bench-quick-chip.added {
  border-color: var(--accent-light);
  color: var(--accent-light);
  background: var(--accent-glow);
}

/* Charts */
.chart {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 12px;
  margin: 16px 0;
  overflow: visible;
}
.js-plotly-plot .plotly .modebar-logo {
  display: none !important;
}
.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.chart-grid .chart { margin: 0; }
@media (max-width: 860px) {
  .chart-grid { grid-template-columns: 1fr; }
}

/* Data Tables */
.table-wrap {
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: auto;
  margin: 14px 0 24px;
  background: var(--card);
}
table.data {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
}
table.data th, table.data td {
  padding: 11px 16px;
  text-align: left;
  white-space: nowrap;
}
table.data td:last-child, table.data th:last-child {
  white-space: normal;
}
table.data th {
  background: var(--card-inner);
  color: var(--muted);
  font-weight: 600;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  user-select: none;
  transition: color 0.15s ease;
}
table.data th:hover {
  color: var(--text);
}
table.data td {
  border-bottom: 1px solid var(--border);
}
table.data tr:last-child td { border-bottom: none; }
table.data tbody tr { transition: background 0.1s ease; }
table.data tbody tr:hover { background: rgba(59, 130, 246, 0.06); }
td.val-pos { color: var(--pos); font-weight: 600; font-family: 'JetBrains Mono', monospace; }
td.val-neg { color: var(--neg); font-weight: 600; font-family: 'JetBrains Mono', monospace; }

footer {
  color: var(--muted);
  font-size: 13px;
  border-top: 1px solid var(--border);
  padding-top: 22px;
  margin-top: 56px;
}
@keyframes statFlash {
  0% { background-color: rgba(59, 130, 246, 0.22); border-color: var(--accent-light); }
  100% { background-color: var(--card); border-color: var(--border); }
}
@keyframes cellFlash {
  0% { background-color: rgba(59, 130, 246, 0.22); }
  100% { background-color: transparent; }
}
.stat.live-updated { animation: statFlash 1.1s ease-out; }
td.live-updated { animation: cellFlash 1.1s ease-out; }
"""


def _now_utc() -> pd.Timestamp:
    """Current report-generation timestamp in UTC."""
    return pd.Timestamp.now(tz="UTC")


def build_live_payload(
    data: ReportData, custom_tickers: list[str] | None = None
) -> dict[str, object]:
    """Build live HTML fragments and metadata for in-place DOM updates."""
    now_ts = _now_utc()
    now_str = now_ts.strftime("%H:%M:%S")
    generated_str = now_ts.strftime("%Y-%m-%d %H:%M:%S")
    figures = report_figures(data)
    return {
        "currency": data.currency,
        "as_of": f"{data.measures.as_of} ({now_str})",
        "period_days": f"{data.measures.period_days} days",
        "generated": generated_str,
        "charts": {
            key: json.loads(_report_figure(fig, key).to_json()) for key, fig in figures.items()
        },
        "chart_headings": {key: _chart_heading(fig) for key, fig in figures.items()},
        "custom_benchmarks": [
            build_custom_benchmark_payload(data.accounts, data.nav, ticker, data.currency)
            for ticker in (custom_tickers or [])
        ],
        "kpi_html": _kpi_section(data),
        "attribution_html": _attribution_section(data.attribution),
        "conversion_html": _conversion_summary_section(
            data.conversion_stats, data.conversion_losses
        ),
        "income_html": _income_table(data.income),
        "risk_html": _risk_cards_html(data.risk),
        "company_pnl_html": _table_html(format_company_pnl_table(data.company_pnl, data.currency)),
    }


def report_figures(data: ReportData) -> dict[str, go.Figure]:
    return {
        "chart-nav": plot_nav_with_deposits(data.nav, data.currency),
        "chart-monthly": plot_monthly_returns_heatmap(data.twr_returns, data.currency),
        "chart-benchmark": build_return_comparison_figure(data.nav, data.benchmarks, data.currency),
        "chart-pnl": plot_company_pnl(data.company_pnl, data.currency),
        "chart-holdings": plot_holdings_allocation(data.positions),
        "chart-currency": plot_currency_allocation(data.positions),
        "chart-sector": plot_sector_allocation(data.sector_alloc),
    }


_LIVE_SCRIPT = """
<script>
(function() {
  const CURRENCY = __CURRENCY_JSON__;
  const IS_DEMO = __DEMO_JSON__;
  const PRELOADED_BENCHMARKS = __CUSTOM_BENCHMARKS_JSON__;
  const POLL_INTERVAL_MS = 10000;
  const EXTRA_COLORS = ['#f472b6', '#a3e635', '#fb923c', '#818cf8', '#2dd4bf', '#e879f9', '#38bdf8', '#facc15'];
  let extraColorIdx = 0;
  let liveEnabled = !IS_DEMO;
  let busy = false;
  let currentCompanyFilter = 'all';
  let currentCompanySearch = '';
  const addedCustomKeys = new Set();

  function resizeVisiblePlots(scope) {
    if (!window.Plotly) return;
    const root = scope || document;
    const plots = root.querySelectorAll('.js-plotly-plot');
    plots.forEach(function(gd) {
      try {
        window.Plotly.Plots.resize(gd);
      } catch (e) {}
    });
  }

  function activateSection(sectionId) {
    document.body.classList.remove('show-all-sections');
    const showAllBtn = document.getElementById('btn-show-all');
    if (showAllBtn) showAllBtn.classList.remove('active');

    const panels = document.querySelectorAll('.tab-panel');
    const clouds = document.querySelectorAll('.nav-cloud');
    panels.forEach(function(panel) {
      panel.classList.toggle('active', panel.id === sectionId);
    });
    clouds.forEach(function(cloud) {
      const active = cloud.getAttribute('data-target') === sectionId;
      cloud.classList.toggle('active', active);
      cloud.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    try {
      history.replaceState(null, '', '#' + sectionId);
    } catch (e) {}
    requestAnimationFrame(function() {
      const activePanel = document.getElementById(sectionId);
      resizeVisiblePlots(activePanel);
    });
  }

  function toggleShowAll() {
    const showingAll = document.body.classList.toggle('show-all-sections');
    const showAllBtn = document.getElementById('btn-show-all');
    if (showAllBtn) showAllBtn.classList.toggle('active', showingAll);
    requestAnimationFrame(function() {
      resizeVisiblePlots(document);
    });
  }

  function decorateTableSemantics(root) {
    const scope = root || document;
    scope.querySelectorAll('table.data tbody td').forEach(function(td) {
      const txt = (td.textContent || '').trim();
      td.classList.remove('val-pos', 'val-neg');
      if (!txt || txt === '—') return;
      if (txt.startsWith('+') && (txt.endsWith('%') || txt.endsWith('PLN') || txt.endsWith('USD') || txt.endsWith('EUR'))) {
        td.classList.add('val-pos');
      } else if (txt.startsWith('-') && (txt.endsWith('%') || txt.endsWith('PLN') || txt.endsWith('USD') || txt.endsWith('EUR'))) {
        td.classList.add('val-neg');
      }
    });
  }

  function applyCompanyTableFilter() {
    const container = document.getElementById('live-company-pnl');
    if (!container) return;
    const rows = container.querySelectorAll('table.data tbody tr');
    const query = (currentCompanySearch || '').trim().toLowerCase();

    rows.forEach(function(tr) {
      const cells = tr.querySelectorAll('td');
      if (cells.length < 8) return;
      const symbol = (cells[1].textContent || '').toLowerCase();
      const status = (cells[2].textContent || '').toLowerCase();
      const totalPnlText = (cells[7].textContent || '').trim();
      const isGain = totalPnlText.startsWith('+');
      const isLoss = totalPnlText.startsWith('-');

      let matchFilter = true;
      if (currentCompanyFilter === 'gain') matchFilter = isGain;
      else if (currentCompanyFilter === 'loss') matchFilter = isLoss;
      else if (currentCompanyFilter === 'open') matchFilter = (status.includes('open') || status.includes('partially'));
      else if (currentCompanyFilter === 'closed') matchFilter = status.includes('closed');

      const matchQuery = !query || symbol.includes(query) || status.includes(query);
      tr.style.display = (matchFilter && matchQuery) ? '' : 'none';
    });
  }

  function enableTableSorting(root) {
    const scope = root || document;
    scope.querySelectorAll('table.data').forEach(function(table) {
      const headers = table.querySelectorAll('thead th');
      headers.forEach(function(th, colIdx) {
        if (th.dataset.sortBound === '1') return;
        th.dataset.sortBound = '1';
        th.title = 'Click to sort this column';
        th.addEventListener('click', function() {
          const tbody = table.querySelector('tbody');
          if (!tbody) return;
          const rows = Array.from(tbody.querySelectorAll('tr'));
          const asc = th.dataset.sortDir !== 'asc';
          th.dataset.sortDir = asc ? 'asc' : 'desc';

          function parseVal(cellText) {
            const clean = (cellText || '')
              .replace(/\\u00a0/g, '')
              .replace(/\\s+/g, '')
              .replace(/PLN|USD|EUR|%|#/gi, '')
              .replace(/,/g, '');
            const num = parseFloat(clean);
            return Number.isNaN(num) ? cellText.toLowerCase() : num;
          }

          rows.sort(function(a, b) {
            const aTxt = (a.children[colIdx] && a.children[colIdx].textContent) || '';
            const bTxt = (b.children[colIdx] && b.children[colIdx].textContent) || '';
            const va = parseVal(aTxt);
            const vb = parseVal(bTxt);
            if (typeof va === 'number' && typeof vb === 'number') {
              return asc ? va - vb : vb - va;
            }
            return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
          });
          rows.forEach(function(r) { tbody.appendChild(r); });
        });
      });
    });
  }

  function updateContainerInPlace(containerId, newHtml) {
    const container = document.getElementById(containerId);
    if (!container || !newHtml) return;
    const temp = document.createElement('div');
    temp.innerHTML = newHtml;
    decorateTableSemantics(temp);

    const oldStats = container.querySelectorAll('.stat');
    const newStats = temp.querySelectorAll('.stat');
    const oldCells = container.querySelectorAll('table.data tbody td');
    const newCells = temp.querySelectorAll('table.data tbody td');

    if (oldStats.length === newStats.length && oldCells.length === newCells.length) {
      oldStats.forEach((oldCard, idx) => {
        const newCard = newStats[idx];
        if (oldCard.innerHTML !== newCard.innerHTML) {
          oldCard.className = newCard.className;
          oldCard.innerHTML = newCard.innerHTML;
          oldCard.classList.remove('live-updated');
          void oldCard.offsetWidth;
          oldCard.classList.add('live-updated');
        }
      });
      oldCells.forEach((oldTd, idx) => {
        const newTd = newCells[idx];
        if (oldTd.textContent !== newTd.textContent) {
          oldTd.className = newTd.className;
          oldTd.innerHTML = newTd.innerHTML;
          oldTd.classList.remove('live-updated');
          void oldTd.offsetWidth;
          oldTd.classList.add('live-updated');
        }
      });
    } else {
      container.innerHTML = temp.innerHTML;
      enableTableSorting(container);
    }
  }

  function setLiveButtonState(lastTime) {
    const badge = document.getElementById('live-market-badge');
    const dot = document.getElementById('live-dot');
    const text = document.getElementById('live-status-text');
    if (!badge || !dot || !text) return;
    if (IS_DEMO) { badge.disabled = true; text.textContent = 'Offline synthetic demo'; dot.classList.remove('on'); return; }
    if (!(window.pywebview && window.pywebview.api && window.pywebview.api.get_live_update)) {
      badge.disabled = true;
      text.textContent = 'Saved snapshot';
      dot.classList.remove('on');
      dot.classList.add('off');
      return;
    }
    badge.disabled = false;
    if (liveEnabled) {
      badge.classList.add('is-on');
      badge.classList.remove('is-off');
      dot.classList.add('on');
      dot.classList.remove('off');
      text.textContent = lastTime ? 'Live updates: ON · ' + lastTime : 'Live updates: ON';
    } else {
      badge.classList.add('is-off');
      badge.classList.remove('is-on');
      dot.classList.add('off');
      dot.classList.remove('on');
      text.textContent = 'Live updates: OFF';
    }
  }

  async function fetchLivePayload() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_live_update) {
      return await window.pywebview.api.get_live_update(CURRENCY);
    }
    return null;
  }

  async function tick() {
    if (!liveEnabled || busy || document.hidden) return;
    busy = true;
    try {
      const payload = await fetchLivePayload();
      if (payload) {
        if (payload.error) throw new Error(payload.error);
        for (const [id, figure] of Object.entries(payload.charts || {})) {
          const gd = document.getElementById(id);
          if (!gd || !window.Plotly) continue;
          const heading = gd.closest('.chart').querySelector('.chart-heading');
          if (heading && payload.chart_headings && payload.chart_headings[id]) heading.outerHTML = payload.chart_headings[id];
          const traces = figure.data;
          if (id === 'chart-benchmark') {
            const extra = gd.data.slice(figure.data.length);
            figure.data.forEach((trace, i) => { if (gd.data[i]) trace.visible = gd.data[i].visible; });
            traces.push(...extra);
          }
          await window.Plotly.react(gd, traces, Object.assign({}, figure.layout, {width: null, autosize: true}), gd._context);
        }
        for (const custom of payload.custom_benchmarks || []) {
          const btn = document.querySelector('[data-bench-key="' + custom.key + '"]');
          if (btn) await window.Plotly.restyle('chart-benchmark', {x: [custom.x], y: [custom.y], name: custom.trace_name}, [Number(btn.dataset.benchTrace)]);
        }
        updateContainerInPlace('live-kpi', payload.kpi_html);
        updateContainerInPlace('live-attribution', payload.attribution_html);
        updateContainerInPlace('live-conversion', payload.conversion_html);
        updateContainerInPlace('live-income', payload.income_html);
        updateContainerInPlace('live-risk', payload.risk_html);
        updateContainerInPlace('live-company-pnl', payload.company_pnl_html);
        applyCompanyTableFilter();

        const asOfEl = document.getElementById('live-as-of');
        if (asOfEl && payload.as_of) asOfEl.textContent = payload.as_of;
        const periodEl = document.getElementById('live-period-days');
        if (periodEl && payload.period_days) periodEl.textContent = payload.period_days;
        const genEl = document.getElementById('live-generated');
        if (genEl && payload.generated) genEl.textContent = payload.generated;
        const timePart = (payload.generated || '').split(' ')[1] || '';
        setLiveButtonState(timePart);
      } else {
        const text = document.getElementById('live-status-text');
        if (text) text.textContent = 'Saved report · live updates require the app';
      }
    } catch (e) {
      const text = document.getElementById('live-status-text');
      if (text) text.textContent = 'Reconnecting · last successful data remains visible';
      const dot = document.getElementById('live-dot');
      if (dot) { dot.classList.remove('on'); dot.classList.add('off'); }
    } finally {
      busy = false;
    }
  }

  function bindBenchmarkToggleButton(btn) {
    if (btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', function() {
      const traceIdx = parseInt(btn.getAttribute('data-bench-trace') || '0', 10);
      const benchContainer = document.getElementById('benchmark-chart-box');
      const gd = benchContainer ? benchContainer.querySelector('.js-plotly-plot') : null;
      if (!gd || !window.Plotly || !gd.data || !gd.data[traceIdx]) return;
      const currentlyVisible = gd.data[traceIdx].visible !== false && gd.data[traceIdx].visible !== 'legendonly';
      const nextState = currentlyVisible ? false : true;
      window.Plotly.restyle(gd, { visible: nextState }, [traceIdx]);
      btn.classList.toggle('active', nextState);
    });
  }

  async function addCustomInstrumentToChart(rawTicker) {
    const ticker = (rawTicker || '').trim().toUpperCase();
    const feedback = document.getElementById('custom-bench-feedback');
    const addBtn = document.getElementById('custom-bench-add-btn');
    if (feedback) feedback.textContent = '';
    if (IS_DEMO) { if (feedback) feedback.textContent = 'Offline demo: comparison indices are synthetic. Load your export in the desktop app to fetch instruments.'; return; }
    if (!ticker) return;

    const benchContainer = document.getElementById('benchmark-chart-box');
    const gd = benchContainer ? benchContainer.querySelector('.js-plotly-plot') : null;
    if (!gd || !window.Plotly) return;

    if (addBtn) addBtn.disabled = true;
    if (feedback) feedback.textContent = 'Fetching history and converting currencies...';
    try {
      let data = PRELOADED_BENCHMARKS[ticker] || null;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.get_custom_benchmark) {
        const res = await window.pywebview.api.get_custom_benchmark(ticker, CURRENCY);
        if (!res || res.error) {
          throw new Error((res && res.error) || ('Unable to fetch data for ' + ticker));
        }
        data = res;
      }
      if (!data) {
        throw new Error('Open this report in the desktop app to fetch ' + ticker);
      }

      if (addedCustomKeys.has(data.key)) {
        const existingBtn = document.querySelector('[data-bench-key="' + data.key + '"]');
        if (existingBtn && !existingBtn.classList.contains('active')) {
          existingBtn.click();
        }
        return;
      }

      const color = EXTRA_COLORS[extraColorIdx % EXTRA_COLORS.length];
      extraColorIdx++;
      const newTraceIdx = gd.data.length;

      await window.Plotly.addTraces(gd, {
        x: data.x,
        y: data.y,
        name: data.trace_name,
        mode: 'lines',
        line: { color: color, width: 2.5, shape: 'linear', dash: 'solid' },
        hovertemplate: '%{x|%b %Y}<br><b>%{y:.1f}%</b><extra></extra>',
        visible: true
      });

      addedCustomKeys.add(data.key);
      if (feedback) feedback.textContent = 'Added ' + data.label;
      const group = document.getElementById('bench-toggle-group');
      if (group) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'filter-btn active';
        btn.setAttribute('data-bench-trace', String(newTraceIdx));
        btn.setAttribute('data-bench-key', data.key);
        btn.textContent = data.label;
        group.appendChild(btn);
        bindBenchmarkToggleButton(btn);
      }
    } catch (err) {
      if (feedback) feedback.textContent = err.message || 'Instrument not found';
    } finally {
      if (addBtn) addBtn.disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    decorateTableSemantics(document);
    enableTableSorting(document);
    document.querySelectorAll('.chart-controls').forEach(function(controls) {
      controls.addEventListener('click', async function(event) {
        const button = event.target.closest('button');
        const gd = document.getElementById(controls.dataset.chartTarget);
        if (!button || !gd || !window.Plotly) return;
        if (button.hasAttribute('data-chart-export')) {
          await Plotly.downloadImage(gd, {format:'png', filename:controls.dataset.chartTarget, scale:2});
        } else if (button.hasAttribute('data-chart-reset')) {
          await Plotly.relayout(gd, {'xaxis.autorange':true, 'yaxis.autorange':true});
          controls.querySelectorAll('[data-chart-range]').forEach(b => b.classList.remove('active'));
        } else if (button.hasAttribute('data-chart-range')) {
          const dates = Array.from(gd.data[0].x || []).map(x => new Date(x)).filter(x => !isNaN(x));
          if (!dates.length) return;
          const last = new Date(Math.max(...dates));
          const first = new Date(Math.min(...dates));
          const period = button.dataset.chartRange;
          let start = new Date(last);
          if (period === 'all') {
            start = first;
          } else if (period === 'ytd') {
            start = new Date(last.getFullYear(), 0, 1);
          } else {
            const count = parseInt(period, 10);
            const unit = period.slice(-1);
            if (unit === 'd' || unit === 'w') {
              start.setDate(start.getDate() - count * (unit === 'w' ? 7 : 1));
            } else {
              const day = start.getDate();
              start.setDate(1);
              start.setMonth(start.getMonth() - count * (unit === 'y' ? 12 : 1));
              const monthEnd = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate();
              start.setDate(Math.min(day, monthEnd));
            }
          }
          if (start < first) start = first;
          await Plotly.relayout(gd, {'xaxis.range':[start, last], 'xaxis.autorange':false});
          controls.querySelectorAll('[data-chart-range]').forEach(b => b.classList.toggle('active', b === button));
        }
      });
    });

    // 4-Section Cloud Navigation
    document.querySelectorAll('.nav-cloud').forEach(function(cloud) {
      cloud.addEventListener('click', function() {
        const target = cloud.getAttribute('data-target');
        if (target) activateSection(target);
      });
    });

    const showAllBtn = document.getElementById('btn-show-all');
    if (showAllBtn) {
      showAllBtn.addEventListener('click', toggleShowAll);
    }

    const hash = (window.location.hash || '').replace('#', '');
    if (['overview', 'holdings', 'benchmarks', 'costs'].includes(hash)) {
      activateSection(hash);
    }

    // Company P&L interactive filters
    document.querySelectorAll('[data-company-filter]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        currentCompanyFilter = btn.getAttribute('data-company-filter') || 'all';
        document.querySelectorAll('[data-company-filter]').forEach(function(b) {
          b.classList.toggle('active', b === btn);
        });
        applyCompanyTableFilter();
      });
    });

    const companySearchInput = document.getElementById('company-search-input');
    if (companySearchInput) {
      companySearchInput.addEventListener('input', function(e) {
        currentCompanySearch = e.target.value || '';
        applyCompanyTableFilter();
      });
    }

    // Benchmark quick-toggle buttons
    document.querySelectorAll('[data-bench-trace]').forEach(bindBenchmarkToggleButton);

    // Custom benchmark add controls
    const exportBtn = document.getElementById('export-bench-csv');
    if (exportBtn) exportBtn.addEventListener('click', function() {
      const gd = document.getElementById('chart-benchmark');
      const rows = [['Date', 'Instrument', 'ROI (%)']];
      (gd.data || []).filter(t => t.visible !== false && t.visible !== 'legendonly').forEach(t => {
        Array.from(t.x).forEach((x, i) => rows.push([x, t.name, t.y[i]]));
      });
      const csv = '\\ufeff' + rows.map(row => row.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(';')).join('\\r\\n');
      const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8;'}));
      const a = document.createElement('a'); a.href = url; a.download = 'comparison-' + CURRENCY + '.csv'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    const customInput = document.getElementById('custom-bench-input');
    const customAddBtn = document.getElementById('custom-bench-add-btn');
    const presetSelect = document.getElementById('preset-bench-select');
    if (customAddBtn && customInput) {
      customAddBtn.addEventListener('click', function() {
        addCustomInstrumentToChart(customInput.value);
      });
      customInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          addCustomInstrumentToChart(customInput.value);
        }
      });
    }
    if (presetSelect) {
      presetSelect.addEventListener('change', function() {
        const val = presetSelect.value;
        if (val) {
          addCustomInstrumentToChart(val);
          presetSelect.value = '';
        }
      });
    }
    document.querySelectorAll('[data-quick-bench]').forEach(function(chip) {
      chip.addEventListener('click', async function() {
        const sym = chip.getAttribute('data-quick-bench');
        if (!sym) return;
        chip.classList.add('added');
        await addCustomInstrumentToChart(sym);
      });
    });

    // Recalculation requires the desktop bridge; standalone HTML is a snapshot.
    document.querySelectorAll('[data-switch-currency]').forEach(function(btn) {
      btn.addEventListener('click', async function(e) {
        e.preventDefault();
        if (IS_DEMO) { e.preventDefault(); return; }
        const targetCurr = (btn.getAttribute('data-switch-currency') || '').toLowerCase();
        if (!targetCurr || targetCurr === CURRENCY) return;
        if (window.pywebview && window.pywebview.api && window.pywebview.api.switch_currency) {
          e.preventDefault();
          btn.textContent = '…';
          const res = await window.pywebview.api.switch_currency(targetCurr);
          if (res && res.ok) {
            window.location.reload();
          }
          return;
        }
      });
    });

    // Live toggle button (Green when ON, Red when OFF, independent of market hours)
    const badge = document.getElementById('live-market-badge');
    if (badge) {
      badge.addEventListener('click', function() {
        liveEnabled = !liveEnabled;
        setLiveButtonState();
        if (liveEnabled) tick();
      });
    }

    setLiveButtonState();
    setTimeout(function() { tick(); }, 1500);
    setInterval(function() { tick(); }, POLL_INTERVAL_MS);
    document.addEventListener('visibilitychange', function() { if (!document.hidden) tick(); });
    window.addEventListener('pywebviewready', function() { setLiveButtonState(); tick(); });
  });
})();
</script>
"""


def render_html_report(data: ReportData) -> str:
    now_ts = _now_utc()
    generated = now_ts.strftime("%Y-%m-%d %H:%M:%S")
    as_of_with_time = f"{data.measures.as_of} ({now_ts.strftime('%H:%M:%S')})"

    benchmark_fig = build_return_comparison_figure(data.nav, data.benchmarks, data.currency)

    # Default benchmark toggle buttons (matching trace order in benchmark_fig: 0 is portfolio, 1..N are benchmarks)
    bench_keys = list(data.benchmarks.keys())
    bench_buttons = "".join(
        f"<button type='button' class='filter-btn active' data-bench-trace='{idx}'>"
        f"{html_lib.escape(BENCHMARK_META.get(key, (key,))[0])}"
        f"</button>"
        for idx, key in enumerate(bench_keys, start=1)
    )

    # Expanded catalog of indices, ETFs, commodities/crypto, and US/Europe/GPW companies
    portfolio_syms = (
        [str(s) for s in data.company_pnl["symbol"].tolist()] if not data.company_pnl.empty else []
    )

    catalog_indices = [
        ("^GDAXI", "DAX 40 (Germany)"),
        ("WIG20.WA", "WIG20 (Warsaw)"),
        ("^DJI", "Dow Jones 30 (US)"),
        ("^RUT", "Russell 2000 (US small caps)"),
        ("^STOXX50E", "Euro Stoxx 50 (Europe)"),
        ("^FTSE", "FTSE 100 (UK)"),
        ("^N225", "Nikkei 225 (Japan)"),
        ("^HSI", "Hang Seng (Hong Kong)"),
    ]
    catalog_etfs_commodities = [
        ("SPY", "SPDR S&P 500 ETF"),
        ("QQQ", "Invesco QQQ (NASDAQ 100 ETF)"),
        ("IWDA.AS", "iShares Core MSCI World ETF"),
        ("EEM", "iShares Emerging Markets ETF"),
        ("SMH", "VanEck Semiconductor ETF"),
        ("SOXX", "iShares Semiconductor ETF"),
        ("XLK", "Technology Sector SPDR ETF"),
        ("XLF", "Financial Sector SPDR ETF"),
        ("XLV", "Health Care Sector SPDR ETF"),
        ("XLE", "Energy Sector SPDR ETF"),
        ("TLT", "US Treasury 20Y+ ETF (TLT)"),
        ("GLD", "Gold ETF (SPDR Gold)"),
        ("SLV", "Silver ETF (iShares Silver)"),
        ("BTC-USD", "Bitcoin (BTC/USD)"),
        ("ETH-USD", "Ethereum (ETH/USD)"),
    ]
    catalog_stocks = [
        ("NVDA", "NVIDIA"),
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("GOOGL", "Alphabet (Google)"),
        ("AMZN", "Amazon"),
        ("META", "Meta Platforms"),
        ("TSLA", "Tesla"),
        ("AMD", "AMD"),
        ("AVGO", "Broadcom"),
        ("TSM", "TSMC"),
        ("ASML", "ASML Holding"),
        ("NFLX", "Netflix"),
        ("PLTR", "Palantir"),
        ("BRK-B", "Berkshire Hathaway"),
        ("LLY", "Eli Lilly"),
        ("NVO", "Novo Nordisk"),
        ("XTB.WA", "XTB S.A. (GPW)"),
        ("PKO.WA", "PKO BP (GPW)"),
        ("PKN.WA", "Orlen (GPW)"),
        ("KGH.WA", "KGHM (GPW)"),
        ("CDR.WA", "CD Projekt (GPW)"),
        ("DNP.WA", "Dino Polska (GPW)"),
        ("LPP.WA", "LPP (GPW)"),
    ]

    seen_tickers: set[str] = set()
    datalist_options: list[str] = []
    for sym in portfolio_syms:
        if sym not in seen_tickers:
            seen_tickers.add(sym)
            datalist_options.append(
                f"<option value='{html_lib.escape(sym)}'>Portfolio holding ({html_lib.escape(sym)})</option>"
            )
    for sym, desc in catalog_indices + catalog_etfs_commodities + catalog_stocks:
        if sym not in seen_tickers:
            seen_tickers.add(sym)
            datalist_options.append(
                f"<option value='{html_lib.escape(sym)}'>{html_lib.escape(desc)}</option>"
            )
    datalist_html = "".join(datalist_options)

    def _optgroup_html(title: str, items: list[tuple[str, str]]) -> str:
        opts = "".join(
            f"<option value='{html_lib.escape(sym)}'>{html_lib.escape(desc)} ({html_lib.escape(sym)})</option>"
            for sym, desc in items
        )
        return f"<optgroup label='{html_lib.escape(title)}'>{opts}</optgroup>"

    portfolio_opt_items = [(sym, f"Portfolio holding {sym}") for sym in portfolio_syms]
    preset_select_html = (
        "<select id='preset-bench-select' class='preset-select' aria-label='Choose an instrument'>"
        "<option value=''>Choose an index, ETF, or stock...</option>"
        + (_optgroup_html("Your portfolio", portfolio_opt_items) if portfolio_opt_items else "")
        + _optgroup_html("Market indices", catalog_indices)
        + _optgroup_html("ETFs, bonds, commodities and crypto", catalog_etfs_commodities)
        + _optgroup_html("Popular stocks (US / Europe / Warsaw)", catalog_stocks)
        + "</select>"
    )

    curr_buttons_html = "".join(
        f"<a href='/?currency={c}' data-switch-currency='{c}' "
        f"class='currency-btn {'active' if c == data.currency.lower() else ''}'>{c.upper()}</a>"
        for c in ("pln", "usd", "eur")
    )

    # Panel 1: Overview with alpha and beta in the risk section.
    panel_overview = (
        "<section id='overview' class='tab-panel active' role='tabpanel'>"
        "<div class='panel-block' id='overview-kpis'>"
        "<h2>Portfolio overview</h2>"
        f"<div id='live-kpi'>{_kpi_section(data)}</div>"
        "</div>"
        "<div class='panel-block' id='nav-history'>"
        f"{_chart(plot_nav_with_deposits(data.nav, data.currency), plot_id='chart-nav')}"
        "</div>"
        "<div class='panel-block' id='risk-monthly'>"
        "<h2>Risk and monthly TWR returns</h2>"
        "<p class='section-desc'>Volatility, alpha, beta, and a monthly return heatmap.</p>"
        f"<div id='live-risk'>{_risk_cards_html(data.risk)}</div>"
        f"{_chart(plot_monthly_returns_heatmap(data.twr_returns, data.currency), plot_id='chart-monthly')}"
        "</div>"
        "</section>"
    )

    # Panel 2: Benchmarks (default 4 indices + single clean selector & custom search)
    panel_benchmarks = (
        "<section id='benchmarks' class='tab-panel' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Compare portfolio performance</h2>"
        "<div class='interactive-toolbar'>"
        "<div class='filter-group' id='bench-toggle-group'>"
        f"{bench_buttons}"
        "</div>"
        "<div class='custom-bench-form'>"
        f"{preset_select_html}"
        "<input type='text' id='custom-bench-input' list='custom-bench-list' class='search-input' "
        "placeholder='Or enter a ticker (e.g. AAPL, SMH, XTB.WA)...'>"
        f"<datalist id='custom-bench-list'>{datalist_html}</datalist>"
        "<button type='button' id='custom-bench-add-btn' class='bench-add-btn'>+ Add comparison</button>"
        "<button type='button' id='export-bench-csv' class='filter-btn'>Download comparison CSV</button>"
        "<span id='custom-bench-feedback' class='bench-feedback' role='status' aria-live='polite'></span>"
        "</div>"
        "</div>"
        f"<div id='benchmark-chart-box'>{_chart(benchmark_fig, plot_id='chart-benchmark')}</div>"
        "</div>"
        "</section>"
    )

    # Panel 3: Holdings (Company P&L chart + table + allocation charts, WITHOUT open positions table)
    panel_holdings = (
        "<section id='holdings' class='tab-panel' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Company profit and loss (ranked by total profit and loss)</h2>"
        "<p class='section-desc'>Open and closed positions ranked "
        "from highest profit to largest loss.</p>"
        f"{_chart(plot_company_pnl(data.company_pnl, data.currency), plot_id='chart-pnl')}"
        "<div class='interactive-toolbar'>"
        "<div class='filter-group'>"
        "<button type='button' class='filter-btn active' data-company-filter='all'>All companies</button>"
        "<button type='button' class='filter-btn' data-company-filter='gain'>Profitable (+)</button>"
        "<button type='button' class='filter-btn' data-company-filter='loss'>Loss-making (−)</button>"
        "<button type='button' class='filter-btn' data-company-filter='open'>Open positions</button>"
        "<button type='button' class='filter-btn' data-company-filter='closed'>Closed positions</button>"
        "</div>"
        "<input type='search' id='company-search-input' class='search-input' placeholder='Search by ticker (e.g. AMD, NVDA)...'>"
        "</div>"
        f"<div id='live-company-pnl'>{_table_html(format_company_pnl_table(data.company_pnl, data.currency))}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Asset allocation</h2>"
        "<p class='section-desc'>Holdings, currencies, and sectors as shares of invested assets; cash excluded.</p>"
        f"{_chart(plot_holdings_allocation(data.positions), plot_id='chart-holdings')}"
        "<div class='chart-grid'>"
        f"{_chart(plot_currency_allocation(data.positions), plot_id='chart-currency')}"
        f"{_chart(plot_sector_allocation(data.sector_alloc), plot_id='chart-sector')}"
        "</div>"
        "</div>"
        "</section>"
    )

    # Panel 4: FX, costs and income (FX conversion stats + FX attribution + Dividends & Interest)
    panel_costs = (
        "<section id='costs' class='tab-panel' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Estimated FX conversion costs</h2>"
        "<p class='section-desc'>Assumes a 0.5% fee on external currency conversions. The export does not verify "
        "the actual fee. Costs already reflected in NAV are not deducted again.</p>"
        f"<div id='live-conversion'>{_conversion_summary_section(data.conversion_stats, data.conversion_losses)}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>FX attribution: investment and currency</h2>"
        "<p class='section-desc'>PLN gains split between investment performance and currency exposure.</p>"
        f"<div id='live-attribution'>{_attribution_section(data.attribution)}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Dividends and interest</h2>"
        "<p class='section-desc'>Dividends, interest, and withholding taxes by account currency.</p>"
        f"<div id='live-income'>{_income_table(data.income)}</div>"
        "</div>"
        "</section>"
    )

    account_ids = ", ".join(account.account_id for account in data.accounts)
    live_script = (
        _LIVE_SCRIPT.replace("__CURRENCY_JSON__", json.dumps(data.currency))
        .replace("__DEMO_JSON__", json.dumps(data.is_demo))
        .replace("__CUSTOM_BENCHMARKS_JSON__", json.dumps(data.custom_benchmarks))
    )

    data_notice = (
        "Synthetic demo: fictional trades, quotes, FX, and indices. No network access."
        if data.is_demo
        else "Prices: Yahoo Finance. FX: NBP with Yahoo fallback. Quotes may be delayed."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>XTB Portfolio Report – {data.measures.as_of}</title>
<script>{_plotly_bundle()}</script>
<style>{_CSS}{_DESIGN_CSS}</style>
</head>
<body>
<div class="container">
<p class="section-desc" id="data-source-notice">{data_notice}</p>
<header class="hero">
  <div class="hero-title-group">
    <h1>XTB Portfolio Report</h1>
    <div class="hero-meta">
      <span>Accounts: <b>{account_ids}</b></span>
      <span class="meta-sep" aria-hidden="true">·</span>
      <span>As of: <b id="live-as-of">{as_of_with_time}</b></span>
      <span class="meta-sep" aria-hidden="true">·</span>
      <span>Period: <b id="live-period-days">{data.measures.period_days} days</b></span>
    </div>
  </div>
  <div class="hero-actions">
    <div class="currency-switcher" role="group" aria-label="Report currency">
      <span class="currency-switch-label">Currency:</span>
      {curr_buttons_html}
    </div>
    <button type="button" class="live-trigger is-on" id="live-market-badge" title="Toggle live polling. Provider quotes may be delayed.">
      <span class="live-dot on" id="live-dot"></span>
      <span id="live-status-text">Live updates: ON</span>
    </button>
  </div>
</header>

<div class="section-switcher-wrap">
  <div class="switcher-header">
    <span class="switcher-title">Explore your portfolio</span>
    <button type="button" class="view-mode-btn" id="btn-show-all">Show all sections</button>
  </div>
  <div class="nav-clouds" role="tablist" aria-label="Report sections">
    <button type="button" class="nav-cloud active" data-target="overview" role="tab" aria-selected="true">
      <div class="cloud-top">
        <span class="cloud-step">01</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Overview</div>
    </button>

    <button type="button" class="nav-cloud" data-target="benchmarks" role="tab" aria-selected="false">
      <div class="cloud-top">
        <span class="cloud-step">02</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Benchmarks</div>
    </button>

    <button type="button" class="nav-cloud" data-target="holdings" role="tab" aria-selected="false">
      <div class="cloud-top">
        <span class="cloud-step">03</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Holdings</div>
    </button>

    <button type="button" class="nav-cloud" data-target="costs" role="tab" aria-selected="false">
      <div class="cloud-top">
        <span class="cloud-step">04</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">FX, costs and income</div>
    </button>
  </div>
</div>

{panel_overview}
{panel_benchmarks}
{panel_holdings}
{panel_costs}

<footer>
Generated <span id="live-generated">{generated}</span> UTC by XTB Portfolio Analyzer. {data_notice}
For educational analysis; not investment or tax advice.
</footer>
</div>
{live_script}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_report(
    data_dir: str | Path = "data",
    output_dir: str | Path = "output",
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
    on_progress: Callable[[float, str], None] | None = None,
    market_data: MarketData | None = None,
) -> Path:
    """Load XTB CSV exports, compute all analytics and write output/report.html."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    def progress(fraction: float, message: str) -> None:
        if on_progress is not None:
            on_progress(fraction, message)

    try:
        csv_files = discover_export_files(data_dir)
    except ValueError as exc:
        from xtb_analyzer.parser import describe_export_discovery

        raise FileNotFoundError(str(exc) + "\n\n" + describe_export_discovery(data_dir)) from exc
    if not csv_files:
        from xtb_analyzer.parser import describe_export_discovery

        raise FileNotFoundError(
            f"No XTB exports found in {data_dir.resolve()}.\n" + describe_export_discovery(data_dir)
        )

    progress(0.12, "Reading account histories...")
    accounts = load_accounts(csv_files)
    data = collect_report_data(
        accounts,
        currency=currency,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
        on_progress=on_progress,
        market_data=market_data,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    report_path.write_text(render_html_report(data), encoding="utf-8")
    return report_path
