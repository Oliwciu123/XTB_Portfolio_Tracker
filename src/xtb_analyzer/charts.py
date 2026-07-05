from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CHART_COLORS = {
    "nav": "#22c55e",
    "deposits": "#94a3b8",
    "benchmark": "#3b82f6",
    "benchmark_alt": "#a855f7",
    "gain": "#22c55e",
    "loss": "#ef4444",
    "grid": "#404040",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
}

CHART_LAYOUT = dict(
    template="plotly_dark",
    font=dict(family="Segoe UI, Arial, sans-serif", size=13, color=CHART_COLORS["text"]),
    paper_bgcolor="#1a1a1a",
    plot_bgcolor="#2d2d2d",
    hovermode="x unified",
    margin=dict(l=60, r=40, t=90, b=110),
    width=1100,
    height=500,
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        xanchor="center",
        x=0.5,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    ),
)

PLOTLY_SHOW_CONFIG = {"displayModeBar": True, "responsive": True}

PIE_COLORS = [
    "#22c55e",
    "#3b82f6",
    "#f59e0b",
    "#ef4444",
    "#a855f7",
    "#06b6d4",
    "#ec4899",
    "#84cc16",
    "#f97316",
    "#6366f1",
]


def _currency_label(currency: str) -> str:
    return currency.upper()


def _polish_decimal(value: float, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def _to_datetime_list(index: pd.Index) -> list:
    return [pd.Timestamp(ts).to_pydatetime() for ts in pd.to_datetime(index)]


def _apply_axis_style(fig: go.Figure, max_ticks: int = 12) -> go.Figure:
    fig.update_xaxes(
        showgrid=True,
        gridcolor=CHART_COLORS["grid"],
        tickangle=-45,
        tickformat="%Y-%m-%d",
        nticks=max_ticks,
    )
    fig.update_yaxes(showgrid=True, gridcolor=CHART_COLORS["grid"])
    return fig


def _slice_from_first_deposit(nav: pd.DataFrame, dep_col: str) -> pd.DataFrame:
    active = nav[dep_col] > 0
    if not active.any():
        return nav
    return nav.loc[nav.index[active][0] :]


def _monthly_return_comparison_data(
    nav: pd.DataFrame,
    benchmarks: dict[str, pd.Series],
    currency: str,
) -> tuple[pd.Series, dict[str, pd.Series], dict[str, float], float, pd.Timestamp]:
    """Rebased monthly return series (day 1 = 0%) and final % for legend labels."""
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"

    view = _slice_from_first_deposit(nav, dep_col)
    first_day = view.index[0]

    portfolio_return = (view[nav_col] / view[dep_col].replace(0, pd.NA) - 1) * 100
    final_portfolio = float(portfolio_return.iloc[-1])

    rebased_columns: dict[str, pd.Series] = {
        "portfolio": portfolio_return - portfolio_return.iloc[0],
    }
    final_returns: dict[str, float] = {}

    for key, benchmark in benchmarks.items():
        benchmark_aligned = benchmark.reindex(view.index, method="ffill")
        if benchmark_aligned.isna().all():
            final_returns[key] = float("nan")
            rebased_columns[key] = portfolio_return * 0
            continue
        benchmark_return = (benchmark_aligned / view[dep_col].replace(0, pd.NA) - 1) * 100
        final_returns[key] = float(benchmark_return.iloc[-1])
        rebased_columns[key] = benchmark_return - benchmark_return.iloc[0]

    rebased = pd.DataFrame(rebased_columns)
    monthly = rebased.resample("ME").last()
    monthly = monthly[monthly.index > first_day]

    start_row = pd.DataFrame({col: [0.0] for col in rebased.columns}, index=[first_day])
    monthly = pd.concat([start_row, monthly]).sort_index()
    monthly = monthly[~monthly.index.duplicated(keep="first")]

    benchmarks_monthly = {key: monthly[key] for key in benchmarks}
    return monthly["portfolio"], benchmarks_monthly, final_returns, final_portfolio, first_day


def _monthly_returns_from_first_deposit(
    nav: pd.DataFrame,
    benchmark: pd.Series,
    currency: str,
) -> tuple[pd.Series, pd.Series, float, float, pd.Timestamp]:
    portfolio_monthly, benchmarks_monthly, final_returns, final_portfolio, first_day = (
        _monthly_return_comparison_data(nav, {"benchmark": benchmark}, currency)
    )
    return (
        portfolio_monthly,
        benchmarks_monthly["benchmark"],
        final_portfolio,
        final_returns["benchmark"],
        first_day,
    )


BENCHMARK_META = {
    "sp500": ("S&P 500 TR", CHART_COLORS["benchmark"]),
    "nasdaq100": ("NASDAQ 100", CHART_COLORS["benchmark_alt"]),
}

RETURN_CHART_LAYOUT = {
    **CHART_LAYOUT,
    "height": 560,
    "width": 920,
    "margin": dict(l=56, r=24, t=96, b=88),
    "legend": dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    ),
}

HOVER_RETURN = "%{x|%b %Y}<br><b>%{y:.1f}%</b><extra></extra>"


@dataclass
class ReturnComparisonData:
    portfolio_monthly: pd.Series
    benchmarks_monthly: dict[str, pd.Series]
    final_returns: dict[str, float]
    final_portfolio: float
    first_day: pd.Timestamp


def prepare_return_comparison_data(
    nav: pd.DataFrame,
    sp500_benchmark: pd.Series,
    nasdaq100_benchmark: pd.Series,
    currency: str = "pln",
) -> ReturnComparisonData:
    benchmarks = {"sp500": sp500_benchmark, "nasdaq100": nasdaq100_benchmark}
    portfolio_monthly, benchmarks_monthly, final_returns, final_portfolio, first_day = (
        _monthly_return_comparison_data(nav, benchmarks, currency)
    )
    return ReturnComparisonData(
        portfolio_monthly=portfolio_monthly,
        benchmarks_monthly=benchmarks_monthly,
        final_returns=final_returns,
        final_portfolio=final_portfolio,
        first_day=first_day,
    )


def _comparison_subtitle(data: ReturnComparisonData, show_sp500: bool, show_nasdaq: bool) -> str:
    parts = [
        f"Start: {data.first_day.strftime('%Y-%m-%d')} (0%)",
        f"Portfel: {_polish_decimal(data.final_portfolio)}%",
    ]
    if show_sp500:
        parts.append(f"S&P 500: {_polish_decimal(data.final_returns['sp500'])}%")
    if show_nasdaq:
        parts.append(f"NASDAQ 100: {_polish_decimal(data.final_returns['nasdaq100'])}%")
    return " | ".join(parts)


def _style_return_comparison_axes(fig: go.Figure, point_count: int) -> None:
    fig.update_xaxes(
        type="date",
        showgrid=True,
        gridcolor="rgba(100, 116, 139, 0.25)",
        tickformat="%b %Y",
        tickangle=0,
        dtick="M1",
        nticks=min(12, max(4, point_count)),
        linecolor="rgba(148, 163, 184, 0.4)",
        mirror=False,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(100, 116, 139, 0.25)",
        ticksuffix="%",
        tickformat=".0f",
        zeroline=True,
        zerolinecolor="rgba(148, 163, 184, 0.55)",
        zerolinewidth=1.5,
        linecolor="rgba(148, 163, 184, 0.4)",
        mirror=False,
    )


def build_return_comparison_figure(
    nav: pd.DataFrame,
    sp500_benchmark: pd.Series,
    nasdaq100_benchmark: pd.Series,
    currency: str = "pln",
    *,
    show_sp500: bool = False,
    show_nasdaq: bool = False,
    data: ReturnComparisonData | None = None,
) -> go.Figure:
    if data is None:
        data = prepare_return_comparison_data(nav, sp500_benchmark, nasdaq100_benchmark, currency)

    x_dates = _to_datetime_list(data.portfolio_monthly.index)
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=data.portfolio_monthly.tolist(),
            name=f"Twój portfel ({_polish_decimal(data.final_portfolio)}%)",
            mode="lines+markers",
            marker=dict(size=7, color=CHART_COLORS["nav"], line=dict(width=1, color="#0f172a")),
            line=dict(color=CHART_COLORS["nav"], width=3, shape="spline"),
            fill="tozeroy",
            fillcolor="rgba(34, 197, 94, 0.08)",
            hovertemplate=HOVER_RETURN,
            visible=True,
        )
    )

    visibility = {"sp500": show_sp500, "nasdaq100": show_nasdaq}
    for key, (label, color) in BENCHMARK_META.items():
        series = data.benchmarks_monthly[key]
        fig.add_trace(
            go.Scatter(
                x=_to_datetime_list(series.index),
                y=series.tolist(),
                name=f"{label} ({_polish_decimal(data.final_returns[key])}%)",
                mode="lines+markers",
                marker=dict(size=6, color=color, line=dict(width=1, color="#0f172a")),
                line=dict(color=color, width=2.5, shape="spline", dash="dot" if key == "nasdaq100" else "solid"),
                hovertemplate=HOVER_RETURN,
                visible=visibility[key],
            )
        )

    fig.update_layout(
        **RETURN_CHART_LAYOUT,
        title=dict(
            text=(
                "Zwrot z kapitału – dane miesięczne<br>"
                f"<sup style='color:#94a3b8'>{_comparison_subtitle(data, show_sp500, show_nasdaq)}</sup>"
            ),
            x=0,
            xanchor="left",
        ),
        yaxis_title="Stopa zwrotu",
        xaxis_title="",
        hoverlabel=dict(bgcolor="#1e293b", font_size=12),
    )
    _style_return_comparison_axes(fig, len(data.portfolio_monthly))
    return fig


def show_return_comparison_widget(
    nav: pd.DataFrame,
    sp500_benchmark: pd.Series,
    nasdaq100_benchmark: pd.Series,
    currency: str = "pln",
    data: ReturnComparisonData | None = None,
) -> None:
    import ipywidgets as widgets
    from IPython.display import display

    if data is None:
        data = prepare_return_comparison_data(nav, sp500_benchmark, nasdaq100_benchmark, currency)

    fig = go.FigureWidget(
        build_return_comparison_figure(
            nav,
            sp500_benchmark,
            nasdaq100_benchmark,
            currency,
            show_sp500=True,
            show_nasdaq=False,
            data=data,
        )
    )

    chk_sp500 = widgets.Checkbox(value=True, description="S&P 500 TR")
    chk_nasdaq = widgets.Checkbox(value=False, description="NASDAQ 100")

    def _update_visibility(_=None) -> None:
        show_sp500 = chk_sp500.value
        show_nasdaq = chk_nasdaq.value
        with fig.batch_update():
            fig.data[1].visible = show_sp500
            fig.data[2].visible = show_nasdaq
            fig.layout.title.text = (
                "Zwrot z kapitału – dane miesięczne<br>"
                f"<sup>{_comparison_subtitle(data, show_sp500, show_nasdaq)}</sup>"
            )

    for widget in (chk_sp500, chk_nasdaq):
        widget.observe(_update_visibility, names="value")

    panel = widgets.VBox(
        [
            widgets.HTML("<b>Pokaż na wykresie</b>"),
            widgets.HTML("<i>Twój portfel (zawsze)</i>"),
            chk_sp500,
            chk_nasdaq,
        ],
        layout=widgets.Layout(min_width="180px"),
    )
    display(
        widgets.HBox(
            [panel, fig],
            layout=widgets.Layout(align_items="flex-start", gap="16px"),
        )
    )


def plot_benchmark_comparison(
    nav: pd.DataFrame,
    benchmark: pd.Series,
    currency: str = "pln",
    *,
    benchmark_name: str = "S&P 500 TR",
    benchmark_color: str | None = None,
) -> go.Figure:
    """Backward-compatible wrapper for a single benchmark line."""
    is_nasdaq = "nasdaq" in benchmark_name.lower()
    fig = build_return_comparison_figure(
        nav,
        sp500_benchmark=benchmark,
        nasdaq100_benchmark=benchmark,
        currency=currency,
        show_sp500=not is_nasdaq,
        show_nasdaq=is_nasdaq,
    )
    trace_idx = 2 if is_nasdaq else 1
    if benchmark_color and len(fig.data) > trace_idx:
        fig.data[trace_idx].line.color = benchmark_color
    if len(fig.data) > trace_idx:
        final_label = fig.data[trace_idx].name.split("(")[-1].rstrip(")")
        fig.data[trace_idx].name = f"{benchmark_name} ({final_label}"
    return fig


def plot_nav_with_deposits(nav: pd.DataFrame, currency: str = "pln") -> go.Figure:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    return_col = f"return_{currency}"

    view = _slice_from_first_deposit(nav, dep_col)
    current_nav = float(nav[nav_col].iloc[-1])
    current_dep = float(nav[dep_col].iloc[-1])
    current_return = float(nav[return_col].iloc[-1]) if return_col in nav.columns else 0.0
    as_of = nav.index[-1].strftime("%Y-%m-%d")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=view.index,
            y=view[dep_col],
            name="Skumulowane wpłaty",
            mode="lines",
            line=dict(color=CHART_COLORS["deposits"], width=2.5, shape="hv"),
            fill="tozeroy",
            fillcolor="rgba(148, 163, 184, 0.12)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=view.index,
            y=view[nav_col],
            name="Wartość portfela",
            mode="lines",
            line=dict(color=CHART_COLORS["nav"], width=3),
        )
    )

    deposits = view[dep_col].diff().fillna(view[dep_col])
    deposit_days = view.index[deposits > 0]
    for day in deposit_days:
        fig.add_vline(x=day, line_width=1, line_dash="dot", line_color="#64748b", opacity=0.4)

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=(
                f"Wartość portfela vs wpłaty ({_currency_label(currency)})<br>"
                f"<sup>Stan na {as_of} | Zwrot: <b>{current_return:+.1%}</b> | "
                f"Portfel: <b>{_polish_decimal(current_nav, 2)}</b> | "
                f"Wpłaty: <b>{_polish_decimal(current_dep, 2)}</b></sup>"
            ),
            x=0,
        ),
        yaxis_title=f"Kwota ({_currency_label(currency)})",
        xaxis_title="",
    )
    _apply_axis_style(fig)
    fig.update_yaxes(tickformat=",.2f")
    return fig


def plot_return_dashboard(nav: pd.DataFrame, currency: str = "pln") -> go.Figure:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    gain_col = f"gain_{currency}"
    return_col = f"return_{currency}"

    total_return = float(nav[return_col].iloc[-1])
    gain = float(nav[gain_col].iloc[-1])
    invested = float(nav[dep_col].iloc[-1])
    current_nav = float(nav[nav_col].iloc[-1])
    as_of = nav.index[-1].strftime("%Y-%m-%d")

    view = _slice_from_first_deposit(nav, dep_col)
    return_series = view[return_col] * 100

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.35, 0.65],
        specs=[[{"type": "indicator"}, {"type": "scatter"}]],
        subplot_titles=("", ""),
    )

    fig.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=total_return * 100,
            number={"suffix": "%", "valueformat": "+.2f"},
            title={"text": f"Zwrot na wpłaconym kapitale ({_currency_label(currency)})"},
            gauge={
                "axis": {"range": [-50, max(100, total_return * 100 + 20)]},
                "bar": {"color": CHART_COLORS["gain"] if total_return >= 0 else CHART_COLORS["loss"]},
                "steps": [
                    {"range": [-50, 0], "color": "rgba(239, 68, 68, 0.2)"},
                    {"range": [0, max(100, total_return * 100 + 20)], "color": "rgba(34, 197, 94, 0.2)"},
                ],
                "threshold": {
                    "line": {"color": CHART_COLORS["text"], "width": 2},
                    "thickness": 0.8,
                    "value": 0,
                },
            },
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=return_series.index,
            y=return_series,
            mode="lines",
            fill="tozeroy",
            line=dict(color=CHART_COLORS["nav"], width=2.5),
            name="Zwrot %",
        ),
        row=1,
        col=2,
    )
    # H1: add_hline breaks on indicator+scatter subplots; use Scatter zero-line instead.
    fig.add_trace(
        go.Scatter(
            x=[return_series.index[0], return_series.index[-1]],
            y=[0, 0],
            mode="lines",
            line=dict(dash="dash", color=CHART_COLORS["muted"], width=1),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=2,
    )

    layout = dict(CHART_LAYOUT)
    layout.update(
        title=dict(
            text=(
                f"Podsumowanie zwrotu (stan na {as_of})<br>"
                f"<sup>Wpłaty: {_polish_decimal(invested, 2)} | "
                f"Wartość: {_polish_decimal(current_nav, 2)} | "
                f"Zysk/strata: {_polish_decimal(gain, 2)} {_currency_label(currency)}</sup>"
            ),
            x=0,
        ),
        showlegend=False,
        height=420,
        margin=dict(l=60, r=40, t=100, b=80),
    )
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="Zwrot (%)", row=1, col=2, gridcolor=CHART_COLORS["grid"])
    fig.update_xaxes(tickangle=-45, nticks=10, row=1, col=2, gridcolor=CHART_COLORS["grid"])
    return fig


def plot_conversion_losses(losses: pd.DataFrame, summary: dict[str, float]) -> go.Figure:
    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.55, 0.45],
        specs=[[{"type": "bar"}, {"type": "table"}]],
    )

    if not losses.empty:
        fig.add_trace(
            go.Bar(
                x=losses["timestamp"],
                y=losses["total_loss_pln"],
                name="Prowizja PLN",
                marker_color=CHART_COLORS["loss"],
                text=[f"{value:.2f}" for value in losses["total_loss_pln"]],
                textposition="outside",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=losses["timestamp"],
                y=losses["cumulative_loss_pln"],
                name="Koszt skumulowany",
                mode="lines+markers",
                line=dict(color="#fca5a5", width=2),
                yaxis="y2",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Table(
            header=dict(
                values=["Metryka", "Wartość"],
                fill_color="#404040",
                font=dict(color=CHART_COLORS["text"]),
                align="left",
            ),
            cells=dict(
                values=[
                    [
                        "Suma przewalutowanych PLN",
                        "Prowizja XTB (0,5%)",
                        "Łączny koszt przewalutowań",
                    ],
                    [
                        f"{summary['total_pln_converted']:.2f} PLN",
                        f"{summary['total_commission_pln']:.2f} PLN",
                        f"{summary['total_loss_pln']:.2f} PLN",
                    ],
                ],
                fill_color="#2d2d2d",
                font=dict(color=CHART_COLORS["text"]),
                align="left",
            ),
        ),
        row=1,
        col=2,
    )

    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": "Koszt przewalutowań PLN → USD/EUR (prowizja XTB 0,5%)",
            "height": 480,
            "showlegend": True,
            "legend": dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
            "yaxis2": dict(
                title="Skumulowany koszt",
                overlaying="y",
                side="right",
                gridcolor=CHART_COLORS["grid"],
            ),
        }
    )
    fig.update_yaxes(title_text="PLN", row=1, col=1, gridcolor=CHART_COLORS["grid"])
    fig.update_xaxes(tickangle=-45, nticks=8, row=1, col=1, gridcolor=CHART_COLORS["grid"])
    return fig


def plot_sector_allocation(alloc: pd.DataFrame) -> go.Figure:
    if alloc.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Alokacja sektorowa portfela – brak danych")
        return fig

    frame = alloc.copy()
    unknown = frame["sector"] == "Unknown"
    frame = pd.concat([frame[~unknown], frame[unknown]], ignore_index=True)

    labels = [f"{row.sector} ({row.weight * 100:.1f}%)" for row in frame.itertuples()]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=frame["market_value_pln"],
                textinfo="percent",
                textposition="inside",
                insidetextorientation="horizontal",
                textfont=dict(size=11),
                marker=dict(colors=PIE_COLORS[: len(frame)]),
                hole=0,
            )
        ]
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": "Alokacja sektorowa portfela",
            "showlegend": True,
            "legend": dict(orientation="v", yanchor="middle", y=0.5, x=1.02, xanchor="left", font=dict(size=11)),
            "height": 520,
            "margin": dict(l=20, r=160, t=70, b=40),
        }
    )
    return fig
