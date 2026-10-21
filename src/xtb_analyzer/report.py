"""Professional interactive HTML report for the XTB portfolio.

``generate_report()`` is the single entry point: it loads the CSV exports,
computes every metric and renders a self-contained ``report.html`` with
interactive Plotly charts (plotly.js loaded from CDN).
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from xtb_analyzer.attribution import FxAttribution, compute_fx_attribution
from xtb_analyzer.benchmark import BENCHMARK_TICKERS, build_benchmark_suite, build_deposit_benchmark
from xtb_analyzer.cash import income_by_currency
from xtb_analyzer.charts import (
    BENCHMARK_META,
    PLOTLY_SHOW_CONFIG,
    _polish_decimal,
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
from xtb_analyzer.metrics import company_pnl_summary, format_company_pnl_table
from xtb_analyzer.models import Account
from xtb_analyzer.parser import discover_export_files, load_accounts
from xtb_analyzer.portfolio import build_nav_series
from xtb_analyzer.prices import fetch_benchmarks, fetch_prices, xtb_to_yahoo
from xtb_analyzer.returns import ReturnMeasures, compute_return_measures, twr_daily_returns
from xtb_analyzer.risk import RiskStats, compute_risk_stats
from xtb_analyzer.sectors import enrich_positions_with_sectors, sector_allocation


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
        raise ValueError("Podaj symbol instrumentu (np. AAPL, NVDA, BTC-USD).")

    yf_ticker = xtb_to_yahoo(raw)
    if index_series is None:
        start = nav.index[0].date().isoformat()
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
        raise ValueError(f"Nie znaleziono danych historycznych dla symbolu '{raw}' ({yf_ticker}).")

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
    )
    if sim_series.dropna().empty:
        raise ValueError(f"Brak pokrycia dat dla symbolu '{raw}'.")

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
        "trace_name": f"{label} ({_polish_decimal(final_ret)}%)",
    }


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def collect_report_data(
    accounts: list[Account],
    currency: str = "pln",
    use_cache: bool = True,
    refresh_latest: bool = True,
    on_progress=None,
) -> ReportData:
    currency = currency.lower()

    def progress(fraction: float, message: str) -> None:
        if on_progress is not None:
            on_progress(fraction, message)

    progress(0.35, "Pobieram ceny i kursy…")
    nav, _, positions = build_nav_series(accounts, use_cache=use_cache, live_prices=refresh_latest)
    progress(0.55, "Liczenie wpłat i stóp zwrotu…")
    nav = attach_deposits_to_nav(nav, accounts, use_cache=use_cache)
    positions = enrich_positions_with_sectors(positions)

    measures = compute_return_measures(accounts, nav, currency, use_cache=use_cache)
    twr_returns = twr_daily_returns(nav, currency)
    attribution = compute_fx_attribution(accounts, nav, use_cache=use_cache)

    progress(0.68, "Porównanie z benchmarkami…")
    start = twr_returns.index[0].date().isoformat() if not twr_returns.empty else nav.index[0].date().isoformat()
    end = (nav.index[-1] + pd.Timedelta(days=1)).date().isoformat()
    index_levels = fetch_benchmarks(
        list(BENCHMARK_TICKERS.values()),
        start=start,
        end=end,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )
    risk = compute_risk_stats(
        twr_returns,
        benchmarks={
            BENCHMARK_META[key][0]: index_levels.get(ticker, pd.Series(dtype=float))
            for key, ticker in BENCHMARK_TICKERS.items()
        },
    )

    benchmarks = build_benchmark_suite(
        accounts,
        nav.index,
        currency=currency,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
    )

    conversion_losses = analyze_conversion_losses(accounts)
    company_pnl = company_pnl_summary(accounts, positions, currency=currency, use_cache=use_cache)

    # Precompute custom benchmark traces for portfolio symbols from cached prices
    custom_benchmarks: dict[str, dict[str, object]] = {}
    portfolio_symbols = sorted({tx.symbol for acc in accounts for tx in acc.transactions if tx.symbol})
    if portfolio_symbols and not nav.empty:
        try:
            cached_prices = fetch_prices(
                portfolio_symbols,
                start=nav.index[0].date().isoformat(),
                end=(nav.index[-1] + pd.Timedelta(days=1)).date().isoformat(),
                use_cache=True,
                refresh_latest=False,
            )
            for sym in portfolio_symbols:
                if sym in cached_prices.columns and not cached_prices[sym].dropna().empty:
                    try:
                        payload = build_custom_benchmark_payload(
                            accounts,
                            nav,
                            sym,
                            currency=currency,
                            use_cache=True,
                            refresh_latest=False,
                            index_series=cached_prices[sym].dropna(),
                        )
                        custom_benchmarks[sym.upper()] = payload
                        custom_benchmarks[xtb_to_yahoo(sym).upper()] = payload
                    except Exception:
                        pass
        except Exception:
            pass

    progress(0.88, "Składam raport…")

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
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}".replace(",", "\u00a0").replace(".", ",")


def _fmt_pct(value: float | None, decimals: int = 2, sign: bool = True) -> str:
    if value is None or pd.isna(value):
        return "—"
    pattern = f"{{:+.{decimals}f}}%" if sign else f"{{:.{decimals}f}}%"
    return pattern.format(value * 100).replace(".", ",")


def _fig_html(fig: go.Figure) -> str:
    fig.update_layout(width=None, autosize=True)
    return fig.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_SHOW_CONFIG)


def _chart(fig: go.Figure, extra_class: str = "") -> str:
    cls = f"chart {extra_class}".strip()
    return f"<div class='{cls}'>{_fig_html(fig)}</div>"


def _table_html(frame: pd.DataFrame, float_decimals: int = 2, table_id: str = "") -> str:
    if frame.empty:
        return "<p class='muted'>Brak danych.</p>"
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


def _stat_card(label: str, value: str, sub: str = "", tone: str = "neutral", big: bool = False) -> str:
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
        _stat_card("Wartość portfela", f"{_fmt_num(measures.final_value)} {currency}", "bieżąca wycena rachunków", big=True),
        _stat_card("Suma wpłat", f"{_fmt_num(measures.invested)} {currency}", "łączny zainwestowany kapitał", big=True),
        _stat_card(
            "Zysk / strata",
            f"{_fmt_num(measures.gain)} {currency}",
            "wartość − wpłaty",
            _tone(measures.gain),
            big=True,
        ),
        _stat_card("ROI", _fmt_pct(measures.roi), "prosty zwrot: wartość ÷ wpłaty − 1", _tone(measures.roi), big=True),
        _stat_card(
            "MWR (XIRR)",
            _fmt_pct(measures.mwr),
            f"w skali roku: {_fmt_pct(measures.xirr)}",
            _tone(measures.mwr),
            big=True,
        ),
        _stat_card(
            "TWR",
            _fmt_pct(measures.twr),
            f"w skali roku: {_fmt_pct(measures.twr_annualized)}",
            _tone(measures.twr),
            big=True,
        ),
    ]
    return "<div class='stat-grid kpi'>" + "".join(cards) + "</div>"


def _risk_cards_html(risk: RiskStats) -> str:
    drawdown_period = (
        f"{risk.max_drawdown_start} → {risk.max_drawdown_end}"
        if risk.max_drawdown_start and risk.max_drawdown_end
        else "na bazie TWR"
    )
    primary_bench = next(
        (b for b in risk.benchmarks if b.beta is not None or b.alpha_annual is not None),
        risk.benchmarks[0] if risk.benchmarks else None,
    )
    alpha_val = primary_bench.alpha_annual if primary_bench else None
    beta_val = primary_bench.beta if primary_bench else None
    bench_name = primary_bench.name if primary_bench else "S&P 500 TR"

    cards = [
        _stat_card("Zmienność (roczna)", _fmt_pct(risk.volatility_annual, sign=False), "odchylenie stóp dziennych"),
        _stat_card("Wskaźnik Sharpe'a", _fmt_num(risk.sharpe), "zwrot do zmienności"),
        _stat_card("Wskaźnik Sortino", _fmt_num(risk.sortino), "zwrot do ryzyka spadku"),
        _stat_card("Alfa (roczna)", _fmt_pct(alpha_val), f"względem {bench_name}", _tone(alpha_val)),
        _stat_card("Beta", _fmt_num(beta_val), f"wrażliwość względem {bench_name}"),
        _stat_card("Maks. obsunięcie", _fmt_pct(risk.max_drawdown), drawdown_period, _tone(risk.max_drawdown)),
        _stat_card("Najlepszy miesiąc", _fmt_pct(risk.best_month), tone="pos"),
        _stat_card("Najgorszy miesiąc", _fmt_pct(risk.worst_month), tone="neg"),
    ]
    return "<div class='stat-grid'>" + "".join(cards) + "</div>"


def _conversion_summary_section(stats: dict[str, float], losses: pd.DataFrame) -> str:
    total_loss = float(stats.get("total_loss_pln", 0.0) or 0.0)
    total_converted = float(stats.get("total_pln_converted", 0.0) or 0.0)
    ops_count = len(losses) if losses is not None else 0

    cards = [
        _stat_card(
            "Łączny koszt przewalutowań (0,5%)",
            f"{_fmt_num(total_loss)} PLN",
            f"prowizja XTB · liczba przewalutowań: {ops_count}",
            "neg" if total_loss > 0 else "neutral",
            big=True,
        ),
        _stat_card(
            "Suma przewalutowanych środków",
            f"{_fmt_num(total_converted)} PLN",
            "łączny wolumen wymiany PLN → USD/EUR",
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
            "Zysk z inwestycji",
            f"{_fmt_num(attribution.investment_gain_pln)} PLN",
            f"{_fmt_pct(inv_share, 0, sign=False)} wyniku" if inv_share is not None else "",
            _tone(attribution.investment_gain_pln),
            big=True,
        ),
        _stat_card(
            "Zysk walutowy",
            f"{_fmt_num(attribution.fx_gain_pln)} PLN",
            f"{_fmt_pct(fx_share, 0, sign=False)} wyniku" if fx_share is not None else "",
            _tone(attribution.fx_gain_pln),
            big=True,
        ),
        _stat_card(
            "Wynik łączny",
            f"{_fmt_num(total)} PLN",
            "inwestycje + waluta",
            _tone(total),
            big=True,
        ),
    ]
    grid = "<div class='stat-grid attribution'>" + "".join(cards) + "</div>"

    if attribution.by_currency.empty:
        return grid

    frame = attribution.by_currency.copy()
    frame["fx_change"] = frame.apply(
        lambda row: row["current_rate"] / row["avg_deposit_rate"] - 1
        if row["avg_deposit_rate"]
        else None,
        axis=1,
    )
    display = pd.DataFrame(
        {
            "Waluta": frame["currency"],
            "Wydane PLN": frame["pln_spent"].map(_fmt_num),
            "Otrzymano": frame.apply(lambda r: f"{_fmt_num(r['units_received'])} {r['currency']}", axis=1),
            "Śr. kurs wpłat": frame["avg_deposit_rate"].map(lambda v: _fmt_num(v, 4)),
            "Kurs obecny": frame["current_rate"].map(lambda v: _fmt_num(v, 4)),
            "Zmiana kursu": frame["fx_change"].map(_fmt_pct),
            "Zysk z inwestycji": frame["investment_gain_pln"].map(lambda v: f"{_fmt_num(v)} PLN"),
            "Zysk walutowy": frame["fx_gain_pln"].map(lambda v: f"{_fmt_num(v)} PLN"),
            "Łącznie": frame["total_gain_pln"].map(lambda v: f"{_fmt_num(v)} PLN"),
        }
    )
    return grid + _table_html(display)


def _income_table(income: pd.DataFrame) -> str:
    if income.empty:
        return "<p class='muted'>Brak dywidend i odsetek w analizowanym okresie.</p>"
    frame = income.rename(
        columns={
            "currency": "Waluta",
            "dividends": "Dywidendy",
            "interest": "Odsetki",
            "taxes": "Podatki u źródła",
            "net_income": "Netto",
        }
    )
    return _table_html(frame)


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
.js-plotly-plot .plotly .modebar-btn:not([data-title*="Download"]):not([data-title*="png"]) {
  display: none !important;
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


def _now_warsaw() -> pd.Timestamp:
    """Current timestamp in Polish timezone (Europe/Warsaw, CET/CEST)."""
    try:
        return pd.Timestamp.now(tz="Europe/Warsaw")
    except Exception:
        return pd.Timestamp.now()


def is_market_open(now: pd.Timestamp | None = None) -> bool:
    """True during European (GPW/Xetra 09:00-17:30 CET) or US (NYSE/NASDAQ 09:30-16:00 ET) market hours."""
    try:
        ts = now.tz_convert("Europe/Warsaw") if now is not None else _now_warsaw()
    except Exception:
        ts = _now_warsaw()
    if ts.weekday() >= 5:
        return False
    minutes = ts.hour * 60 + ts.minute
    return 9 * 60 <= minutes <= 22 * 60


def build_live_payload(data: ReportData) -> dict[str, object]:
    """Build live HTML fragments and metadata for in-place DOM updates."""
    now_ts = _now_warsaw()
    now_str = now_ts.strftime("%H:%M:%S")
    generated_str = now_ts.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "currency": data.currency,
        "as_of": f"{data.measures.as_of} ({now_str})",
        "period_days": f"{data.measures.period_days} dni",
        "generated": generated_str,
        "kpi_html": _kpi_section(data),
        "attribution_html": _attribution_section(data.attribution),
        "conversion_html": _conversion_summary_section(data.conversion_stats, data.conversion_losses),
        "income_html": _income_table(data.income),
        "risk_html": _risk_cards_html(data.risk),
        "company_pnl_html": _table_html(format_company_pnl_table(data.company_pnl, data.currency)),
    }


_LIVE_SCRIPT = """
<script>
(function() {
  const CURRENCY = __CURRENCY_JSON__;
  const PRELOADED_BENCHMARKS = __CUSTOM_BENCHMARKS_JSON__;
  const POLL_INTERVAL_MS = 15000;
  const EXTRA_COLORS = ['#f472b6', '#a3e635', '#fb923c', '#818cf8', '#2dd4bf', '#e879f9', '#38bdf8', '#facc15'];
  let extraColorIdx = 0;
  let liveEnabled = true;
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
      else if (currentCompanyFilter === 'open') matchFilter = status.includes('otwarta');
      else if (currentCompanyFilter === 'closed') matchFilter = status.includes('zamknięta');

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
        th.title = 'Kliknij, aby posortować kolumnę';
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
              .replace(',', '.');
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
    if (liveEnabled) {
      badge.classList.add('is-on');
      badge.classList.remove('is-off');
      dot.classList.add('on');
      dot.classList.remove('off');
      text.textContent = lastTime ? 'Statystyki LIVE: WŁĄCZONE · ' + lastTime : 'Statystyki LIVE: WŁĄCZONE';
    } else {
      badge.classList.add('is-off');
      badge.classList.remove('is-on');
      dot.classList.add('off');
      dot.classList.remove('on');
      text.textContent = 'Statystyki LIVE: WYŁĄCZONE';
    }
  }

  async function fetchLivePayload() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_live_update) {
      return await window.pywebview.api.get_live_update(CURRENCY);
    }
    if (window.location.protocol.startsWith('http')) {
      const resp = await fetch('/api/live?currency=' + encodeURIComponent(CURRENCY), {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      });
      if (!resp.ok) return null;
      return await resp.json();
    }
    return null;
  }

  async function tick() {
    if (!liveEnabled || busy) return;
    busy = true;
    try {
      const payload = await fetchLivePayload();
      if (payload) {
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
      }
    } catch (e) {
      // Ignore transient network errors during live polling
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
    if (!ticker) return;

    const benchContainer = document.getElementById('benchmark-chart-box');
    const gd = benchContainer ? benchContainer.querySelector('.js-plotly-plot') : null;
    if (!gd || !window.Plotly) return;

    if (addBtn) addBtn.disabled = true;
    try {
      let data = PRELOADED_BENCHMARKS[ticker] || null;
      if (!data && window.pywebview && window.pywebview.api && window.pywebview.api.get_custom_benchmark) {
        const res = await window.pywebview.api.get_custom_benchmark(ticker, CURRENCY);
        if (!res || res.error) {
          throw new Error((res && res.error) || ('Nie udało się pobrać danych dla ' + ticker));
        }
        data = res;
      }
      if (!data && window.location.protocol.startsWith('http')) {
        const resp = await fetch(
          '/api/benchmark?ticker=' + encodeURIComponent(ticker) + '&currency=' + encodeURIComponent(CURRENCY),
          { headers: { 'Accept': 'application/json' }, cache: 'no-store' }
        );
        const json = await resp.json();
        if (!resp.ok || json.error) {
          throw new Error(json.error || ('Nie udało się pobrać danych dla ' + ticker));
        }
        data = json;
      }
      if (!data) {
        throw new Error('Brak danych dla symbolu ' + ticker);
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
        mode: 'lines+markers',
        marker: { size: 6, color: color, line: { width: 1, color: '#0f172a' } },
        line: { color: color, width: 2.5, shape: 'spline', dash: 'solid' },
        hovertemplate: '%{x|%b %Y}<br><b>%{y:.1f}%</b><extra></extra>',
        visible: true
      });

      addedCustomKeys.add(data.key);
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
      if (feedback) feedback.textContent = err.message || 'Nie znaleziono instrumentu';
    } finally {
      if (addBtn) addBtn.disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    decorateTableSemantics(document);
    enableTableSorting(document);

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
    if (['podsumowanie', 'struktura', 'benchmarki', 'koszty'].includes(hash)) {
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

    // Currency switcher buttons (works in both Web and PyWebView desktop)
    document.querySelectorAll('[data-switch-currency]').forEach(function(btn) {
      btn.addEventListener('click', async function(e) {
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
        if (window.location.protocol.startsWith('http')) {
          e.preventDefault();
          window.location.href = '/?currency=' + encodeURIComponent(targetCurr) + (window.location.hash || '');
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
  });
})();
</script>
"""


def render_html_report(data: ReportData) -> str:
    now_ts = _now_warsaw()
    currency_label = data.measures.currency
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
    portfolio_syms = [str(s) for s in data.company_pnl["symbol"].tolist()] if not data.company_pnl.empty else []

    catalog_indices = [
        ("^GDAXI", "DAX 40 (Niemcy)"),
        ("WIG20.WA", "WIG20 (GPW)"),
        ("^DJI", "Dow Jones 30 (USA)"),
        ("^RUT", "Russell 2000 (Małe spółki USA)"),
        ("^STOXX50E", "Euro Stoxx 50 (Europa)"),
        ("^FTSE", "FTSE 100 (UK)"),
        ("^N225", "Nikkei 225 (Japonia)"),
        ("^HSI", "Hang Seng (Hongkong)"),
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
        ("TLT", "Obligacje USA 20Y+ (iShares TLT)"),
        ("GLD", "Złoto ETF (SPDR Gold)"),
        ("SLV", "Srebro ETF (iShares Silver)"),
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
                f"<option value='{html_lib.escape(sym)}'>Spółka z portfela ({html_lib.escape(sym)})</option>"
            )
    for sym, desc in catalog_indices + catalog_etfs_commodities + catalog_stocks:
        if sym not in seen_tickers:
            seen_tickers.add(sym)
            datalist_options.append(f"<option value='{html_lib.escape(sym)}'>{html_lib.escape(desc)}</option>")
    datalist_html = "".join(datalist_options)

    def _optgroup_html(title: str, items: list[tuple[str, str]]) -> str:
        opts = "".join(
            f"<option value='{html_lib.escape(sym)}'>{html_lib.escape(desc)} ({html_lib.escape(sym)})</option>"
            for sym, desc in items
        )
        return f"<optgroup label='{html_lib.escape(title)}'>{opts}</optgroup>"

    portfolio_opt_items = [(sym, f"Spółka z portfela {sym}") for sym in portfolio_syms]
    preset_select_html = (
        "<select id='preset-bench-select' class='preset-select' aria-label='Wybierz instrument z listy'>"
        "<option value=''>Wybierz indeks / ETF / spółkę z listy…</option>"
        + (_optgroup_html("Twój portfel", portfolio_opt_items) if portfolio_opt_items else "")
        + _optgroup_html("Indeksy giełdowe", catalog_indices)
        + _optgroup_html("ETF-y, obligacje, surowce i krypto", catalog_etfs_commodities)
        + _optgroup_html("Popularne spółki (USA / Europa / GPW)", catalog_stocks)
        + "</select>"
    )

    curr_buttons_html = "".join(
        f"<a href='/?currency={c}' data-switch-currency='{c}' "
        f"class='currency-btn {'active' if c == data.currency.lower() else ''}'>{c.upper()}</a>"
        for c in ("pln", "usd", "eur")
    )

    # Panel 1: Podsumowanie (simplified, deduplicated, no dividends, with Alfa & Beta in Risk)
    panel_podsumowanie = (
        "<section id='podsumowanie' class='tab-panel active' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Podsumowanie portfela</h2>"
        "<p class='section-desc'>Kluczowe wskaźniki wyceny, wpłat oraz stóp zwrotu (ROI, MWR/XIRR, TWR).</p>"
        f"<div id='live-kpi'>{_kpi_section(data)}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Wartość portfela w czasie</h2>"
        "<p class='section-desc'>Wartość portfela na tle skumulowanych wpłat. Pionowe linie oznaczają dni wpłat.</p>"
        f"{_chart(plot_nav_with_deposits(data.nav, data.currency))}"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Ryzyko i miesięczne stopy zwrotu TWR</h2>"
        "<p class='section-desc'>Najważniejsze miary zmienności, wskaźniki Alfa i Beta oraz miesięczna mapa stóp zwrotu TWR.</p>"
        f"<div id='live-risk'>{_risk_cards_html(data.risk)}</div>"
        f"{_chart(plot_monthly_returns_heatmap(data.twr_returns, data.currency))}"
        "</div>"
        "</section>"
    )

    # Panel 2: Benchmarki (default 4 indices + single clean selector & custom search)
    panel_benchmarki = (
        "<section id='benchmarki' class='tab-panel' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Porównanie portfela z indeksami, ETF-ami i spółkami</h2>"
        "<p class='section-desc'>Symulacja zakupu wybranego indeksu, funduszu ETF lub spółki za każdą wpłatę w dniu wpłaty (te same kwoty i momenty wpłat).</p>"
        "<div class='interactive-toolbar'>"
        "<div class='filter-group' id='bench-toggle-group'>"
        f"{bench_buttons}"
        "</div>"
        "<div class='custom-bench-form'>"
        f"{preset_select_html}"
        "<input type='text' id='custom-bench-input' list='custom-bench-list' class='search-input' "
        "placeholder='Lub wpisz dowolny ticker (np. AAPL, SMH, XTB.WA)…'>"
        f"<datalist id='custom-bench-list'>{datalist_html}</datalist>"
        "<button type='button' id='custom-bench-add-btn' class='bench-add-btn'>+ Dodaj do wykresu</button>"
        "<span id='custom-bench-feedback' class='bench-feedback'></span>"
        "</div>"
        "</div>"
        f"<div id='benchmark-chart-box'>{_chart(benchmark_fig)}</div>"
        "</div>"
        "</section>"
    )

    # Panel 3: Struktura spółek (Company P&L chart + table + allocation charts, WITHOUT open positions table)
    panel_struktura = (
        "<section id='struktura' class='tab-panel' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Zyski i straty na spółkach (od największego zysku do największej straty)</h2>"
        "<p class='section-desc'>Ranking wszystkich spółek z historii rachunków (zarówno otwartych, jak i zamkniętych pozycji) "
        "od największego łącznego zysku do największej straty.</p>"
        f"{_chart(plot_company_pnl(data.company_pnl, data.currency))}"
        "<div class='interactive-toolbar'>"
        "<div class='filter-group'>"
        "<button type='button' class='filter-btn active' data-company-filter='all'>Wszystkie spółki</button>"
        "<button type='button' class='filter-btn' data-company-filter='gain'>Tylko zyskowne (+)</button>"
        "<button type='button' class='filter-btn' data-company-filter='loss'>Tylko stratne (−)</button>"
        "<button type='button' class='filter-btn' data-company-filter='open'>Otwarte pozycje</button>"
        "<button type='button' class='filter-btn' data-company-filter='closed'>Zamknięte pozycje</button>"
        "</div>"
        "<input type='search' id='company-search-input' class='search-input' placeholder='Szukaj spółki po symbolu (np. AMD, NVDA)…'>"
        "</div>"
        f"<div id='live-company-pnl'>{_table_html(format_company_pnl_table(data.company_pnl, data.currency))}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Alokacja portfela</h2>"
        "<p class='section-desc'>Udział poszczególnych instrumentów, walut oraz sektorów w bieżącej wartości portfela.</p>"
        f"{_chart(plot_holdings_allocation(data.positions))}"
        "<div class='chart-grid'>"
        f"{_chart(plot_currency_allocation(data.positions))}"
        f"{_chart(plot_sector_allocation(data.sector_alloc))}"
        "</div>"
        "</div>"
        "</section>"
    )

    # Panel 4: Waluty, koszty i dywidendy (FX conversion stats + FX attribution + Dividends & Interest)
    panel_koszty = (
        "<section id='koszty' class='tab-panel' role='tabpanel'>"
        "<div class='panel-block'>"
        "<h2>Koszty przewalutowań XTB</h2>"
        "<p class='section-desc'>Łączny koszt przewalutowań PLN → USD/EUR oraz prowizja pobrana przez XTB (0,5%).</p>"
        f"<div id='live-conversion'>{_conversion_summary_section(data.conversion_stats, data.conversion_losses)}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Atrybucja walutowa: inwestycje vs waluta</h2>"
        "<p class='section-desc'>Rozbicie wyniku w PLN na zysk wypracowany przez same inwestycje oraz wpływ zmian kursów walut.</p>"
        f"<div id='live-attribution'>{_attribution_section(data.attribution)}</div>"
        "</div>"
        "<div class='panel-block'>"
        "<h2>Dywidendy i odsetki</h2>"
        "<p class='section-desc'>Przychody gotówkowe portfela (dywidendy, odsetki od wolnych środków oraz podatki u źródła) w podziale na waluty rachunków.</p>"
        f"<div id='live-income'>{_income_table(data.income)}</div>"
        "</div>"
        "</section>"
    )

    account_ids = ", ".join(account.account_id for account in data.accounts)
    live_script = (
        _LIVE_SCRIPT.replace("__CURRENCY_JSON__", json.dumps(data.currency))
        .replace("__CUSTOM_BENCHMARKS_JSON__", json.dumps(data.custom_benchmarks))
    )

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raport portfela XTB – {data.measures.as_of}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
<header class="hero">
  <div class="hero-title-group">
    <h1>Raport portfela XTB</h1>
    <div class="hero-meta">
      <span>Konta: <b>{account_ids}</b></span>
      <span class="meta-sep" aria-hidden="true">·</span>
      <span>Stan na: <b id="live-as-of">{as_of_with_time}</b></span>
      <span class="meta-sep" aria-hidden="true">·</span>
      <span>Okres: <b id="live-period-days">{data.measures.period_days} dni</b></span>
    </div>
  </div>
  <div class="hero-actions">
    <div class="currency-switcher" role="group" aria-label="Waluta raportu">
      <span class="currency-switch-label">Waluta:</span>
      {curr_buttons_html}
    </div>
    <button type="button" class="live-trigger is-on" id="live-market-badge" title="Kliknij, aby włączyć lub wyłączyć odświeżanie statystyk na żywo (zielona kropka = WŁĄCZONE, czerwona kropka = WYŁĄCZONE).">
      <span class="live-dot on" id="live-dot"></span>
      <span id="live-status-text">Statystyki LIVE: WŁĄCZONE</span>
    </button>
  </div>
</header>

<div class="section-switcher-wrap">
  <div class="switcher-header">
    <span class="switcher-title">Wybierz sekcję raportu</span>
    <button type="button" class="view-mode-btn" id="btn-show-all">Pokaż wszystkie sekcje naraz</button>
  </div>
  <div class="nav-clouds" role="tablist" aria-label="Sekcje raportu">
    <button type="button" class="nav-cloud active" data-target="podsumowanie" role="tab" aria-selected="true">
      <div class="cloud-top">
        <span class="cloud-step">01</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Podsumowanie</div>
    </button>

    <button type="button" class="nav-cloud" data-target="benchmarki" role="tab" aria-selected="false">
      <div class="cloud-top">
        <span class="cloud-step">02</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Benchmarki</div>
    </button>

    <button type="button" class="nav-cloud" data-target="struktura" role="tab" aria-selected="false">
      <div class="cloud-top">
        <span class="cloud-step">03</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Struktura spółek</div>
    </button>

    <button type="button" class="nav-cloud" data-target="koszty" role="tab" aria-selected="false">
      <div class="cloud-top">
        <span class="cloud-step">04</span>
        <span class="cloud-arrow">→</span>
      </div>
      <div class="cloud-title">Waluty, koszty i dywidendy</div>
    </button>
  </div>
</div>

{panel_podsumowanie}
{panel_benchmarki}
{panel_struktura}
{panel_koszty}

<footer>
Wygenerowano <span id="live-generated">{generated}</span> przez xtb_portfolio_analyzer. Ceny: Yahoo Finance, kursy walut: NBP (tabela A),
MSCI ACWI: ETF iShares ACWI, SOX: Philadelphia Semiconductor Index (^SOX). Raport ma charakter informacyjny i nie stanowi porady inwestycyjnej.
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
    on_progress=None,
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
            f"Brak eksportów XTB w {data_dir.resolve()}.\n"
            + describe_export_discovery(data_dir)
        )

    progress(0.12, "Czytam historię kont…")
    accounts = load_accounts(csv_files)
    data = collect_report_data(
        accounts,
        currency=currency,
        use_cache=use_cache,
        refresh_latest=refresh_latest,
        on_progress=on_progress,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    report_path.write_text(render_html_report(data), encoding="utf-8")
    return report_path
