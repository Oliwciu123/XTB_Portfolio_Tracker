"""Professional interactive HTML report for the XTB portfolio.

``generate_report()`` is the single entry point: it loads the CSV exports,
computes every metric and renders a self-contained ``report.html`` with
interactive Plotly charts (plotly.js loaded from CDN).
"""

from __future__ import annotations

import html as html_lib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from xtb_analyzer.attribution import FxAttribution, compute_fx_attribution
from xtb_analyzer.benchmark import BENCHMARK_TICKERS, build_benchmark_suite
from xtb_analyzer.cash import income_by_currency
from xtb_analyzer.charts import (
    BENCHMARK_META,
    PLOTLY_SHOW_CONFIG,
    build_return_comparison_figure,
    plot_conversion_losses,
    plot_currency_allocation,
    plot_drawdown,
    plot_holdings_allocation,
    plot_monthly_returns_heatmap,
    plot_nav_with_deposits,
    plot_return_measures,
    plot_rolling_volatility,
    plot_sector_allocation,
)
from xtb_analyzer.flows import analyze_conversion_losses, attach_deposits_to_nav, conversion_summary
from xtb_analyzer.metrics import format_positions_table
from xtb_analyzer.models import Account
from xtb_analyzer.parser import discover_export_files, load_accounts
from xtb_analyzer.portfolio import build_nav_series
from xtb_analyzer.prices import fetch_benchmarks
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


def _chart(fig: go.Figure) -> str:
    return f"<div class='chart'>{_fig_html(fig)}</div>"


def _table_html(frame: pd.DataFrame, float_decimals: int = 2) -> str:
    if frame.empty:
        return "<p class='muted'>Brak danych.</p>"
    formatted = frame.copy()
    for column in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda v: _fmt_num(v, float_decimals))
    table = formatted.to_html(index=False, classes="data", border=0, escape=True, na_rep="—")
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
        _stat_card("Wartość portfela", f"{_fmt_num(measures.final_value)} {currency}", f"stan na {measures.as_of}", big=True),
        _stat_card("Suma wpłat", f"{_fmt_num(measures.invested)} {currency}", f"okres: {measures.period_days} dni", big=True),
        _stat_card(
            "Zysk / strata",
            f"{_fmt_num(measures.gain)} {currency}",
            "wartość − wpłaty",
            _tone(measures.gain),
            big=True,
        ),
        _stat_card("ROI", _fmt_pct(measures.roi), "prosty zwrot na kapitale", _tone(measures.roi), big=True),
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
        _stat_card(
            "Maks. obsunięcie",
            _fmt_pct(data.risk.max_drawdown),
            "na bazie TWR",
            _tone(data.risk.max_drawdown),
            big=True,
        ),
        _stat_card(
            "Zysk walutowy",
            f"{_fmt_num(data.attribution.fx_gain_pln)} PLN",
            "wpływ kursów walut",
            _tone(data.attribution.fx_gain_pln),
            big=True,
        ),
    ]
    return "<div class='stat-grid kpi'>" + "".join(cards) + "</div>"


def _methods_table(measures: ReturnMeasures) -> str:
    frame = pd.DataFrame(
        [
            {
                "Metoda": "ROI",
                "Za okres": _fmt_pct(measures.roi),
                "W skali roku": "—",
                "Co mierzy": "Wartość ÷ wpłaty − 1. Najprostsza miara, nie uwzględnia momentów wpłat.",
            },
            {
                "Metoda": "MWR (XIRR)",
                "Za okres": _fmt_pct(measures.mwr),
                "W skali roku": _fmt_pct(measures.xirr),
                "Co mierzy": "Faktyczny zwrot inwestora z uwzględnieniem, kiedy pieniądze pracowały (przepływy pieniężne).",
            },
            {
                "Metoda": "TWR",
                "Za okres": _fmt_pct(measures.twr),
                "W skali roku": _fmt_pct(measures.twr_annualized),
                "Co mierzy": "Jakość decyzji inwestycyjnych – neutralizuje wpłaty, wprost porównywalna z indeksami.",
            },
        ]
    )
    return _table_html(frame)


def _risk_section(risk: RiskStats) -> str:
    drawdown_period = (
        f"{risk.max_drawdown_start} → {risk.max_drawdown_end}"
        if risk.max_drawdown_start and risk.max_drawdown_end
        else ""
    )
    cards = [
        _stat_card("Zmienność (roczna)", _fmt_pct(risk.volatility_annual, sign=False)),
        _stat_card("Sharpe", _fmt_num(risk.sharpe)),
        _stat_card("Sortino", _fmt_num(risk.sortino)),
        _stat_card("Calmar", _fmt_num(risk.calmar)),
        _stat_card("Maks. obsunięcie", _fmt_pct(risk.max_drawdown), drawdown_period, _tone(risk.max_drawdown)),
        _stat_card("VaR 95% (dzienny)", _fmt_pct(risk.var_95_daily), "strata przekraczana w 5% dni", "neg"),
        _stat_card("Najlepszy dzień", _fmt_pct(risk.best_day), tone="pos"),
        _stat_card("Najgorszy dzień", _fmt_pct(risk.worst_day), tone="neg"),
        _stat_card("Najlepszy miesiąc", _fmt_pct(risk.best_month), tone="pos"),
        _stat_card("Najgorszy miesiąc", _fmt_pct(risk.worst_month), tone="neg"),
        _stat_card("Miesiące na plusie", _fmt_pct(risk.positive_months_pct, 0, sign=False), "odsetek miesięcy z dodatnim wynikiem"),
    ]
    grid = "<div class='stat-grid'>" + "".join(cards) + "</div>"

    rows = [
        {
            "Benchmark": relation.name,
            "Zwrot w okresie": _fmt_pct(relation.benchmark_return),
            "Beta": _fmt_num(relation.beta),
            "Alfa (roczna)": _fmt_pct(relation.alpha_annual),
            "Korelacja": _fmt_num(relation.correlation),
        }
        for relation in risk.benchmarks
    ]
    bench_table = _table_html(pd.DataFrame(rows)) if rows else ""
    bench_header = "<h3>Portfel na tle indeksów</h3>" if rows else ""
    return grid + bench_header + bench_table


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


def _section(anchor: str, title: str, body: str, description: str = "") -> str:
    desc_html = f"<p class='section-desc'>{description}</p>" if description else ""
    return (
        f"<section id='{anchor}'>"
        f"<h2>{html_lib.escape(title)}</h2>"
        f"{desc_html}"
        f"{body}"
        f"</section>"
    )


_CSS = """
:root {
  --bg: #0b0e14; --card: #151a23; --card-inner: #10151d; --border: #232a36;
  --text: #e2e8f0; --muted: #8b98ab;
  --pos: #34d399; --neg: #f87171; --accent: #60a5fa;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 64px; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: 'Inter', 'Segoe UI', Arial, sans-serif; line-height: 1.6;
  font-feature-settings: 'tnum';
}
.container { max-width: 1180px; margin: 0 auto; padding: 0 28px 72px; }
header.hero { padding: 52px 0 20px; }
header.hero h1 {
  margin: 0 0 10px; font-size: 34px; font-weight: 700; letter-spacing: -0.5px;
  background: linear-gradient(90deg, #e2e8f0 0%, #94a3b8 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.badges { display: flex; flex-wrap: wrap; gap: 8px; }
.badge {
  background: var(--card); border: 1px solid var(--border); color: var(--muted);
  border-radius: 999px; padding: 4px 14px; font-size: 13px;
}
.badge b { color: var(--text); font-weight: 600; }
nav.toc {
  position: sticky; top: 0; z-index: 10;
  background: rgba(11, 14, 20, 0.85); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border); padding: 12px 0; margin: 20px 0 8px;
  display: flex; flex-wrap: wrap; gap: 4px 22px; font-size: 14px;
}
nav.toc a { color: var(--muted); text-decoration: none; transition: color 0.15s; }
nav.toc a:hover { color: var(--accent); }
section { margin: 52px 0; }
h2 { font-size: 22px; font-weight: 650; margin: 0 0 6px; letter-spacing: -0.3px; }
h3 { font-size: 16px; font-weight: 600; margin: 26px 0 4px; color: var(--muted); }
.section-desc { color: var(--muted); font-size: 14px; margin: 0 0 18px; max-width: 860px; }
.muted { color: var(--muted); font-size: 14px; }

.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px; margin: 18px 0;
}
.stat-grid.kpi, .stat-grid.attribution { grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); }
.stat {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 16px 18px;
  transition: transform 0.15s, border-color 0.15s;
}
.stat:hover { transform: translateY(-2px); border-color: #334155; }
.stat-label {
  color: var(--muted); font-size: 12px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.6px;
}
.stat-value { font-size: 21px; font-weight: 650; margin: 6px 0 2px; letter-spacing: -0.3px; }
.stat-big .stat-value { font-size: 26px; }
.stat-sub { color: var(--muted); font-size: 12.5px; }
.stat-pos .stat-value { color: var(--pos); }
.stat-neg .stat-value { color: var(--neg); }

.chart {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 12px 10px; margin: 18px 0; overflow: visible;
}
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.chart-grid .chart { margin: 0; }
@media (max-width: 800px) {
  .chart-grid { grid-template-columns: 1fr; }
}

.table-wrap {
  border: 1px solid var(--border); border-radius: 14px;
  overflow: auto; margin: 18px 0; background: var(--card);
}
table.data { width: 100%; border-collapse: collapse; font-size: 14px; }
table.data th, table.data td { padding: 11px 16px; text-align: left; white-space: nowrap; }
table.data td:last-child, table.data th:last-child { white-space: normal; }
table.data th {
  background: var(--card-inner); color: var(--muted); font-weight: 600;
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border);
}
table.data td { border-bottom: 1px solid var(--border); }
table.data tr:last-child td { border-bottom: none; }
table.data tbody tr { transition: background 0.1s; }
table.data tbody tr:hover { background: rgba(96, 165, 250, 0.05); }

footer {
  color: var(--muted); font-size: 13px; border-top: 1px solid var(--border);
  padding-top: 20px; margin-top: 56px;
}
@media (max-width: 640px) {
  header.hero h1 { font-size: 26px; }
  .stat-big .stat-value { font-size: 22px; }
}
"""


def render_html_report(data: ReportData) -> str:
    currency_label = data.measures.currency
    generated = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    benchmark_fig = build_return_comparison_figure(data.nav, data.benchmarks, data.currency)

    structure_body = (
        _chart(plot_holdings_allocation(data.positions))
        + "<div class='chart-grid'>"
        + _chart(plot_currency_allocation(data.positions))
        + _chart(plot_sector_allocation(data.sector_alloc))
        + "</div>"
        + _table_html(format_positions_table(data.positions))
    )

    sections = [
        _section("podsumowanie", "Podsumowanie", _kpi_section(data)),
        _section(
            "wartosc",
            "Wartość portfela w czasie",
            _chart(plot_nav_with_deposits(data.nav, data.currency)),
            "Wartość portfela na tle skumulowanych wpłat. Pionowe linie oznaczają dni wpłat.",
        ),
        _section(
            "stopy-zwrotu",
            "Stopy zwrotu: ROI, MWR i TWR",
            _chart(plot_return_measures(data.measures)) + _methods_table(data.measures),
            "Trzy standardowe metody liczenia zwrotu za ten sam okres – różnice wynikają wyłącznie "
            "z odmiennego traktowania momentów wpłat.",
        ),
        _section(
            "benchmarki",
            "Portfel vs S&P 500, NASDAQ 100 i MSCI ACWI",
            _chart(benchmark_fig),
            "Benchmark symuluje zakup indeksu za każdą wpłatę w dniu wpłaty (te same kwoty, te same momenty). "
            "Kliknij pozycję legendy, aby ukryć lub pokazać linię.",
        ),
        _section(
            "atrybucja",
            "Atrybucja walutowa: inwestycje vs waluta",
            _attribution_section(data.attribution),
            "Rozbicie łącznego wyniku w PLN: ile wypracowały same inwestycje, a ile wynika ze zmian kursów walut "
            "(łącznie z kosztem przewalutowania XTB względem kursu rynkowego).",
        ),
        _section(
            "ryzyko",
            "Ryzyko",
            _risk_section(data.risk)
            + _chart(plot_drawdown(data.twr_returns, data.currency))
            + _chart(plot_monthly_returns_heatmap(data.twr_returns, data.currency))
            + _chart(plot_rolling_volatility(data.twr_returns, currency=data.currency)),
            "Statystyki liczone na dziennych stopach TWR (neutralizują wpłaty), dzięki czemu są porównywalne z indeksami.",
        ),
        _section(
            "struktura",
            "Struktura portfela",
            structure_body,
        ),
        _section(
            "dochody",
            "Dywidendy i odsetki",
            _income_table(data.income),
            "Przychody gotówkowe portfela w podziale na waluty rachunków.",
        ),
        _section(
            "koszty",
            "Koszty przewalutowań",
            _chart(plot_conversion_losses(data.conversion_losses, data.conversion_stats)),
        ),
    ]

    toc_items = [
        ("podsumowanie", "Podsumowanie"),
        ("wartosc", "Wartość portfela"),
        ("stopy-zwrotu", "Stopy zwrotu"),
        ("benchmarki", "Benchmarki"),
        ("atrybucja", "Atrybucja walutowa"),
        ("ryzyko", "Ryzyko"),
        ("struktura", "Struktura"),
        ("dochody", "Dywidendy"),
        ("koszty", "Koszty FX"),
    ]
    toc = "".join(f"<a href='#{anchor}'>{label}</a>" for anchor, label in toc_items)

    account_ids = ", ".join(account.account_id for account in data.accounts)
    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raport portfela XTB – {data.measures.as_of}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
<header class="hero">
<h1>Raport portfela XTB</h1>
<div class="badges">
<span class="badge">Konta: <b>{account_ids}</b></span>
<span class="badge">Waluta raportu: <b>{currency_label}</b></span>
<span class="badge">Stan na: <b>{data.measures.as_of}</b></span>
<span class="badge">Okres: <b>{data.measures.period_days} dni</b></span>
</div>
</header>
<nav class="toc">{toc}</nav>
{"".join(sections)}
<footer>
Wygenerowano {generated} przez xtb_portfolio_analyzer. Ceny: Yahoo Finance, kursy walut: NBP (tabela A),
MSCI ACWI: ETF iShares ACWI. Raport ma charakter informacyjny i nie stanowi porady inwestycyjnej.
</footer>
</div>
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
