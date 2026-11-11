from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from xtb_analyzer.attribution import FxAttribution
from xtb_analyzer.returns import ReturnMeasures
from xtb_analyzer.risk import monthly_returns

CHART_COLORS = {
    "nav": "#34d399",
    "deposits": "#64748b",
    "benchmark": "#60a5fa",
    "benchmark_alt": "#c084fc",
    "benchmark_world": "#fbbf24",
    "benchmark_sox": "#22d3ee",
    "gain": "#34d399",
    "loss": "#f87171",
    "grid": "rgba(148, 163, 184, 0.14)",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
}

CHART_LAYOUT = dict(
    template="plotly_dark",
    font=dict(
        family="'Plus Jakarta Sans', Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        size=13,
        color=CHART_COLORS["text"],
    ),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    hovermode="x unified",
    margin=dict(l=60, r=40, t=90, b=110),
    width=1100,
    height=500,
    dragmode="pan",
    uirevision="portfolio",
    transition=dict(duration=300),
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.22,
        xanchor="center",
        x=0.5,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    ),
    hoverlabel=dict(
        bgcolor="#0f172a",
        bordercolor="#334155",
        font=dict(
            family="'Plus Jakarta Sans', Inter, -apple-system, sans-serif",
            size=12.5,
            color="#f8fafc",
        ),
    ),
)

PLOTLY_SHOW_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "sendChartToCloud", "sendDataToCloud"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}

PIE_COLORS = [
    "#34d399",
    "#60a5fa",
    "#fbbf24",
    "#f87171",
    "#c084fc",
    "#22d3ee",
    "#f472b6",
    "#a3e635",
    "#fb923c",
    "#818cf8",
    "#2dd4bf",
    "#e879f9",
]


def _currency_label(currency: str) -> str:
    return currency.upper()


def _format_decimal(value: float, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}"


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
    active = nav.get(dep_col.replace("deposits_", "gross_deposits_"), nav[dep_col]) > 0
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

    capital = view.get(f"gross_deposits_{currency}", view[dep_col]).replace(0, float("nan"))
    portfolio_return = (view[nav_col] - view[dep_col]) / capital * 100
    final_portfolio = float(portfolio_return.iloc[-1])

    rebased_columns: dict[str, pd.Series] = {
        "portfolio": portfolio_return,
    }
    final_returns: dict[str, float] = {}

    for key, benchmark in benchmarks.items():
        benchmark_aligned = benchmark.reindex(view.index, method="ffill")
        if benchmark_aligned.isna().all():
            final_returns[key] = float("nan")
            rebased_columns[key] = pd.Series(float("nan"), index=view.index)
            continue
        benchmark_return = (benchmark_aligned - view[dep_col]) / capital * 100
        final_returns[key] = float(benchmark_return.iloc[-1])
        rebased_columns[key] = benchmark_return

    rebased = pd.DataFrame(rebased_columns)
    monthly = rebased.copy()  # Keep actual observation dates, including the live endpoint.
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
    "demo_sp500": ("S&P 500 (synthetic)", CHART_COLORS["benchmark"], "solid"),
    "demo_nasdaq100": ("Nasdaq-100 (synthetic)", CHART_COLORS["benchmark_alt"], "solid"),
    "demo_sox": ("SOX (synthetic)", CHART_COLORS["benchmark_sox"], "solid"),
    "demo_wig20": ("WIG20 (synthetic)", CHART_COLORS["benchmark_world"], "solid"),
    "demo_equity": ("Synthetic equity index", CHART_COLORS["benchmark"], "solid"),
    "demo_bonds": ("Synthetic bond index", CHART_COLORS["benchmark_alt"], "solid"),
    "sp500": ("S&P 500 TR", CHART_COLORS["benchmark"], "solid"),
    "nasdaq100": ("NASDAQ 100", CHART_COLORS["benchmark_alt"], "dot"),
    "acwi": ("MSCI ACWI", CHART_COLORS["benchmark_world"], "dash"),
    "sox": ("Philadelphia Semiconductor (SOX)", CHART_COLORS["benchmark_sox"], "dashdot"),
}

RETURN_CHART_LAYOUT = {
    **CHART_LAYOUT,
    "height": 580,
    "width": 920,
    "margin": dict(l=64, r=32, t=100, b=150),
    "legend": dict(
        orientation="h",
        yanchor="top",
        y=-0.18,
        xanchor="left",
        x=0,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        entrywidth=220,
    ),
}

HOVER_RETURN = "<b>%{meta}</b>: <b>%{y:+.2f}%</b><extra></extra>"


@dataclass
class ReturnComparisonData:
    portfolio_monthly: pd.Series
    benchmarks_monthly: dict[str, pd.Series]
    final_returns: dict[str, float]
    final_portfolio: float
    first_day: pd.Timestamp


def prepare_return_comparison_data(
    nav: pd.DataFrame,
    benchmarks: dict[str, pd.Series],
    currency: str = "pln",
) -> ReturnComparisonData:
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


def _comparison_subtitle(data: ReturnComparisonData, visible: dict[str, bool]) -> str:
    parts = [
        f"From {data.first_day.strftime('%Y-%m-%d')} · report currency",
        f"Portfolio: {_format_decimal(data.final_portfolio)}%",
    ]
    for key, is_visible in visible.items():
        if is_visible and key in data.final_returns and key in BENCHMARK_META:
            label = BENCHMARK_META[key][0]
            parts.append(f"{label}: {_format_decimal(data.final_returns[key])}%")
    return " | ".join(parts)


def _style_return_comparison_axes(fig: go.Figure, point_count: int) -> None:
    fig.update_xaxes(
        type="date",
        showgrid=True,
        gridcolor="rgba(100, 116, 139, 0.25)",
        tickmode="auto",
        hoverformat="%d %b %Y",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1.2,
        spikecolor="rgba(148, 163, 184, 0.42)",
        spikedash="dot",
        tickformatstops=[
            dict(dtickrange=[None, 86400000], value="%d %b<br>%H:%M"),
            dict(dtickrange=[86400000, "M1"], value="%d %b"),
            dict(dtickrange=["M1", "M12"], value="%b %Y"),
            dict(dtickrange=["M12", None], value="%Y"),
        ],
        tickangle=0,
        nticks=min(8, max(2, point_count)),
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
    benchmarks: dict[str, pd.Series],
    currency: str = "pln",
    *,
    visible: dict[str, bool] | None = None,
    data: ReturnComparisonData | None = None,
) -> go.Figure:
    if data is None:
        data = prepare_return_comparison_data(nav, benchmarks, currency)
    if visible is None:
        visible = {key: True for key in data.benchmarks_monthly}

    x_dates = _to_datetime_list(data.portfolio_monthly.index)
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=data.portfolio_monthly.tolist(),
            name=f"Your portfolio ({_format_decimal(data.final_portfolio)}%)",
            meta="Your portfolio",
            mode="lines",
            line=dict(color=CHART_COLORS["nav"], width=3, shape="linear"),
            fill="tozeroy",
            fillcolor="rgba(52, 211, 153, 0.08)",
            hovertemplate=HOVER_RETURN,
            visible=True,
        )
    )

    for key, series in data.benchmarks_monthly.items():
        label, color, dash = BENCHMARK_META.get(key, (key, CHART_COLORS["muted"], "solid"))
        fig.add_trace(
            go.Scatter(
                x=_to_datetime_list(series.index),
                y=series.tolist(),
                name=f"{label} ({_format_decimal(data.final_returns[key])}%)",
                meta=label,
                mode="lines",
                line=dict(color=color, width=2.5, shape="linear", dash="solid"),
                hovertemplate=HOVER_RETURN,
                visible=visible.get(key, True),
            )
        )

    fig.update_layout(
        **RETURN_CHART_LAYOUT,
        title=dict(
            text=(
                "Return on contributed capital<br>"
                f"<sup>From {data.first_day.strftime('%Y-%m-%d')} · results in report currency</sup>"
            ),
            x=0.5,
            xanchor="center",
        ),
        yaxis_title="Return",
        xaxis_title="",
    )
    _style_return_comparison_axes(fig, len(data.portfolio_monthly))
    fig.update_xaxes(range=[data.portfolio_monthly.index[0], data.portfolio_monthly.index[-1]])
    return fig


def show_return_comparison_widget(
    nav: pd.DataFrame,
    benchmarks: dict[str, pd.Series],
    currency: str = "pln",
    data: ReturnComparisonData | None = None,
) -> None:
    import ipywidgets as widgets
    from IPython.display import display

    if data is None:
        data = prepare_return_comparison_data(nav, benchmarks, currency)

    keys = list(data.benchmarks_monthly)
    initial = {key: key == "sp500" for key in keys}
    fig = go.FigureWidget(
        build_return_comparison_figure(nav, benchmarks, currency, visible=initial, data=data)
    )

    checkboxes = {
        key: widgets.Checkbox(value=initial[key], description=BENCHMARK_META.get(key, (key,))[0])
        for key in keys
    }

    def _update_visibility(_=None) -> None:
        visible = {key: box.value for key, box in checkboxes.items()}
        with fig.batch_update():
            for idx, key in enumerate(keys, start=1):
                fig.data[idx].visible = visible[key]
            fig.layout.title.text = (
                f"Return on contributed capital<br><sup>{_comparison_subtitle(data, visible)}</sup>"
            )

    for box in checkboxes.values():
        box.observe(_update_visibility, names="value")

    panel = widgets.VBox(
        [
            widgets.HTML("<b>Show on chart</b>"),
            widgets.HTML("<i>Your portfolio (always visible)</i>"),
            *checkboxes.values(),
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
    key = "nasdaq100" if "nasdaq" in benchmark_name.lower() else "sp500"
    fig = build_return_comparison_figure(nav, {key: benchmark}, currency, visible={key: True})
    if benchmark_color and len(fig.data) > 1:
        fig.data[1].line.color = benchmark_color
    if len(fig.data) > 1:
        final_label = fig.data[1].name.split("(")[-1].rstrip(")")
        fig.data[1].name = f"{benchmark_name} ({final_label}"
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

    curr_lbl = _currency_label(currency)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=view.index,
            y=view[dep_col],
            name="Net contributions",
            meta="Net contributions",
            mode="lines",
            line=dict(color=CHART_COLORS["deposits"], width=2.5, shape="hv"),
            fill="tozeroy",
            fillcolor="rgba(148, 163, 184, 0.12)",
            hovertemplate=f"<b>%{{meta}}</b>: <b>%{{y:,.2f}} {curr_lbl}</b><extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=view.index,
            y=view[nav_col],
            name="Portfolio NAV",
            meta="Portfolio NAV",
            mode="lines",
            line=dict(color=CHART_COLORS["nav"], width=3),
            hovertemplate=f"<b>%{{meta}}</b>: <b>%{{y:,.2f}} {curr_lbl}</b><extra></extra>",
        )
    )

    deposits = view[dep_col].diff().fillna(view[dep_col])
    deposit_days = view.index[deposits > 0]
    # Dense funding histories would otherwise obscure the price path.
    marker_step = max(1, (len(deposit_days) + 11) // 12)
    for day in deposit_days[::marker_step]:
        fig.add_vline(x=day, line_width=1, line_dash="dot", line_color="#64748b", opacity=0.4)

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=(
                f"Portfolio NAV and contributions ({_currency_label(currency)})<br>"
                f"<sup>As of {as_of} | Return: <b>{current_return:+.1%}</b> | "
                f"Portfolio: <b>{_format_decimal(current_nav, 2)}</b> | "
                f"Contributions: <b>{_format_decimal(current_dep, 2)}</b></sup>"
            ),
            x=0.5,
            xanchor="center",
        ),
        yaxis_title=f"Amount ({_currency_label(currency)})",
        xaxis_title="",
    )
    _apply_axis_style(fig)
    fig.update_layout(height=400, margin=dict(l=68, r=28, t=90, b=70))
    fig.update_xaxes(
        hoverformat="%d %b %Y",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1.2,
        spikecolor="rgba(148, 163, 184, 0.42)",
        spikedash="dot",
    )
    fig.update_yaxes(tickformat=",.0f")
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
            title={"text": f"Return on contributed capital ({_currency_label(currency)})"},
            gauge={
                "axis": {"range": [-50, max(100, total_return * 100 + 20)]},
                "bar": {
                    "color": CHART_COLORS["gain"] if total_return >= 0 else CHART_COLORS["loss"]
                },
                "steps": [
                    {"range": [-50, 0], "color": "rgba(239, 68, 68, 0.2)"},
                    {
                        "range": [0, max(100, total_return * 100 + 20)],
                        "color": "rgba(34, 197, 94, 0.2)",
                    },
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
            name="Return %",
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
                f"Return overview (as of {as_of})<br>"
                f"<sup>Contributions: {_format_decimal(invested, 2)} | "
                f"Value: {_format_decimal(current_nav, 2)} | "
                f"Profit/loss: {_format_decimal(gain, 2)} {_currency_label(currency)}</sup>"
            ),
            x=0.5,
            xanchor="center",
        ),
        showlegend=False,
        height=420,
        margin=dict(l=60, r=40, t=100, b=80),
    )
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="Return (%)", row=1, col=2, gridcolor=CHART_COLORS["grid"])
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
                name="PLN conversion fee",
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
                name="Cumulative cost",
                mode="lines",
                line=dict(color="#fca5a5", width=2),
                yaxis="y2",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Table(
            header=dict(
                values=["Metric", "Value"],
                fill_color="#232a36",
                font=dict(color=CHART_COLORS["muted"], size=12),
                align="left",
                height=32,
            ),
            cells=dict(
                values=[
                    [
                        "Total PLN converted",
                        "XTB conversion fee (0.5%)",
                        "Total estimated FX conversion cost",
                    ],
                    [
                        f"{summary['total_pln_converted']:.2f} PLN",
                        f"{summary['total_commission_pln']:.2f} PLN",
                        f"{summary['total_loss_pln']:.2f} PLN",
                    ],
                ],
                fill_color="#10151d",
                font=dict(color=CHART_COLORS["text"], size=13),
                align="left",
                height=30,
            ),
        ),
        row=1,
        col=2,
    )

    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": "Estimated PLN conversion cost (assumed fee: 0.5%)",
            "height": 480,
            "showlegend": True,
            "legend": dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
            "yaxis2": dict(
                title="Cumulative cost",
                overlaying="y",
                side="right",
                gridcolor=CHART_COLORS["grid"],
            ),
        }
    )
    fig.update_yaxes(title_text="PLN", row=1, col=1, gridcolor=CHART_COLORS["grid"])
    fig.update_xaxes(tickangle=-45, nticks=8, row=1, col=1, gridcolor=CHART_COLORS["grid"])
    return fig


def plot_return_measures(measures: ReturnMeasures) -> go.Figure:
    """Compare ROI, MWR and TWR over the same holding period."""
    items = [
        ("ROI", measures.roi, "profit divided by gross contributions"),
        ("MWR (XIRR)", measures.mwr, "money weighted: includes cash-flow timing"),
        ("TWR", measures.twr, "time weighted: neutralizes external cash flows"),
    ]
    items = [(label, value, desc) for label, value, desc in items if value is not None]

    labels = [label for label, _, _ in items]
    values = [value * 100 for _, value, _ in items]
    descriptions = [desc for _, _, desc in items]
    colors = [CHART_COLORS["gain"] if value >= 0 else CHART_COLORS["loss"] for value in values]

    # Pad the y-axis so outside bar labels never get clipped.
    top = max(values + [0.0])
    bottom = min(values + [0.0])
    span = max(top - bottom, 1.0)
    y_range = [bottom - span * 0.18 if bottom < 0 else 0, top + span * 0.28]

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            width=0.55,
            marker=dict(color=colors, line=dict(width=0), cornerradius=6),
            text=[f"{value:+.2f}%" for value in values],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=15, color=CHART_COLORS["text"]),
            customdata=descriptions,
            hovertemplate="<b>%{x}</b><br>%{y:+.2f}%<br><i>%{customdata}</i><extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=(
                    f"Holding-period returns: comparison of methods ({measures.currency})<br>"
                    f"<sup>Period: {measures.period_days} days | as of {measures.as_of}</sup>"
                ),
                x=0.5,
                xanchor="center",
            ),
            "yaxis_title": "Return (%)",
            "height": 430,
            "margin": dict(l=60, r=40, t=90, b=50),
            "showlegend": False,
        }
    )
    fig.update_yaxes(
        range=y_range,
        zeroline=True,
        zerolinecolor="rgba(148, 163, 184, 0.5)",
        gridcolor=CHART_COLORS["grid"],
        ticksuffix="%",
    )
    fig.update_xaxes(tickfont=dict(size=14))
    return fig


MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def plot_monthly_returns_heatmap(daily_returns: pd.Series, currency: str = "pln") -> go.Figure:
    monthly = monthly_returns(daily_returns) * 100
    if monthly.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Monthly returns: no data")
        return fig

    frame = monthly.to_frame("value")
    frame["year"] = frame.index.year
    frame["month"] = frame.index.month
    pivot = frame.pivot_table(index="year", columns="month", values="value", aggfunc="last")
    pivot = pivot.reindex(columns=range(1, 13))

    z = pivot.to_numpy()
    text = [[("" if pd.isna(v) else f"{v:+.1f}%") for v in row] for row in z]
    max_abs = max(abs(float(monthly.min())), abs(float(monthly.max())), 1.0)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=MONTH_LABELS,
            y=[str(year) for year in pivot.index],
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=12),
            zmin=-max_abs,
            zmax=max_abs,
            colorscale=[
                [0.0, "#7f1d1d"],
                [0.45, "#3f1d1d"],
                [0.5, "#2d2d2d"],
                [0.55, "#14351f"],
                [1.0, "#15803d"],
            ],
            hovertemplate="%{y} %{x}<br><b>%{z:+.2f}%</b><extra></extra>",
            colorbar=dict(ticksuffix="%"),
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=f"Monthly TWR returns ({_currency_label(currency)})", x=0.5, xanchor="center"
            ),
            "height": 200 + 60 * len(pivot),
            "margin": dict(l=60, r=40, t=80, b=40),
        }
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def plot_fx_attribution_waterfall(attribution: FxAttribution) -> go.Figure:
    labels = ["Investment gain", "FX gain", "Total gain"]
    fig = go.Figure(
        go.Waterfall(
            x=labels,
            y=[
                attribution.investment_gain_pln,
                attribution.fx_gain_pln,
                attribution.total_gain_pln,
            ],
            measure=["relative", "relative", "total"],
            text=[
                f"{attribution.investment_gain_pln:+,.0f}",
                f"{attribution.fx_gain_pln:+,.0f}",
                f"{attribution.total_gain_pln:+,.0f}",
            ],
            textposition="outside",
            textfont=dict(size=13),
            connector=dict(line=dict(color=CHART_COLORS["muted"], width=1)),
            increasing=dict(marker=dict(color=CHART_COLORS["gain"])),
            decreasing=dict(marker=dict(color=CHART_COLORS["loss"])),
            totals=dict(marker=dict(color=CHART_COLORS["benchmark"])),
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} PLN<extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text="Return decomposition: investment + FX (PLN)", x=0.5, xanchor="center"
            ),
            "yaxis_title": "PLN",
            "height": 440,
            "showlegend": False,
        }
    )
    fig.update_yaxes(gridcolor=CHART_COLORS["grid"], tickformat=",.0f")
    return fig


def _group_top_n(frame: pd.DataFrame, label_col: str, value_col: str, top_n: int) -> pd.DataFrame:
    frame = frame.sort_values(value_col, ascending=False)
    if len(frame) <= top_n:
        return frame
    head = frame.iloc[:top_n]
    rest = pd.DataFrame([{label_col: "Other", value_col: frame.iloc[top_n:][value_col].sum()}])
    return pd.concat([head, rest], ignore_index=True)


def plot_allocation_donut(
    labels: list[str],
    values: list[float],
    title: str,
    *,
    color_offset: int = 0,
) -> go.Figure:
    """Donut that never collapses in narrow cards.

    The pie uses a fixed domain on the left; the legend sits on the right.
    Percentages only appear inside large enough slices.
    """
    colors = [PIE_COLORS[(color_offset + i) % len(PIE_COLORS)] for i in range(len(labels))]
    total = sum(values) or 1.0
    # Show percent text only for slices big enough to hold it (~8%+).
    text = [f"{value / total * 100:.1f}%" if value / total >= 0.08 else "" for value in values]

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.42,
            sort=False,
            direction="clockwise",
            text=text,
            textinfo="text",
            textposition="inside",
            insidetextorientation="horizontal",
            textfont=dict(size=14, color="#0b0e14", family="Inter, 'Segoe UI', Arial, sans-serif"),
            marker=dict(colors=colors, line=dict(color="#151a23", width=2.5)),
            domain=dict(x=[0.0, 0.58], y=[0.05, 0.95]),
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} PLN (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(text=title, x=0.5, xanchor="center", font=dict(size=16)),
            "height": 360,
            "showlegend": True,
            "legend": dict(
                orientation="v",
                yanchor="middle",
                y=0.5,
                xanchor="left",
                x=0.62,
                font=dict(size=13, color=CHART_COLORS["text"]),
                bgcolor="rgba(0,0,0,0)",
                itemclick=False,
                itemdoubleclick=False,
                traceorder="normal",
            ),
            "margin": dict(l=16, r=16, t=56, b=16),
        }
    )
    return fig


def plot_holdings_allocation(positions: pd.DataFrame, top_n: int = 10) -> go.Figure:
    """Horizontal bar chart of position weights — readable with any number of holdings."""
    if positions.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Portfolio allocation – no data")
        return fig

    by_symbol = positions.groupby("symbol", as_index=False)["market_value_pln"].sum()
    by_symbol = _group_top_n(by_symbol, "symbol", "market_value_pln", top_n)
    by_symbol = by_symbol.sort_values("market_value_pln", ascending=True)
    total = float(by_symbol["market_value_pln"].sum()) or 1.0
    weights = by_symbol["market_value_pln"] / total * 100
    colors = [PIE_COLORS[i % len(PIE_COLORS)] for i in range(len(by_symbol))][::-1]

    fig = go.Figure(
        go.Bar(
            x=weights.tolist(),
            y=by_symbol["symbol"].tolist(),
            orientation="h",
            marker=dict(color=colors, line=dict(width=0), cornerradius=4),
            text=[
                f"{w:.1f}%  ·  {_format_decimal(v, 0)} PLN"
                for w, v in zip(weights, by_symbol["market_value_pln"], strict=False)
            ],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=12, color=CHART_COLORS["text"]),
            hovertemplate="<b>%{y}</b><br>%{x:.1f}% · %{customdata:,.0f} PLN<extra></extra>",
            customdata=by_symbol["market_value_pln"].tolist(),
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=f"Allocation by holding<br><sup style='color:#94a3b8'>Total {_format_decimal(total, 0)} PLN</sup>",
                x=0.5,
                xanchor="center",
            ),
            "height": max(320, 56 + 36 * len(by_symbol)),
            "showlegend": False,
            "margin": dict(l=90, r=140, t=70, b=40),
            "xaxis": dict(
                title="Share of invested assets (%)",
                range=[0, max(weights.max() * 1.35, 10)],
                gridcolor=CHART_COLORS["grid"],
                ticksuffix="%",
                zeroline=False,
            ),
            "yaxis": dict(title="", automargin=True, tickfont=dict(size=13)),
        }
    )
    return fig


def plot_currency_allocation(positions: pd.DataFrame) -> go.Figure:
    """Donut: allocation by account currency."""
    if positions.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Currency allocation – no data")
        return fig
    by_currency = (
        positions.groupby("currency", as_index=False)["market_value_pln"]
        .sum()
        .sort_values("market_value_pln", ascending=False)
    )
    return plot_allocation_donut(
        by_currency["currency"].tolist(),
        by_currency["market_value_pln"].tolist(),
        "Allocation by account currency",
        color_offset=4,
    )


def plot_rolling_volatility(
    daily_returns: pd.Series, window: int = 21, currency: str = "pln"
) -> go.Figure:
    rolling = daily_returns.rolling(window).std() * (252**0.5) * 100
    rolling = rolling.dropna()

    fig = go.Figure(
        go.Scatter(
            x=_to_datetime_list(rolling.index),
            y=rolling.tolist(),
            mode="lines",
            line=dict(color=CHART_COLORS["benchmark_alt"], width=2),
            fill="tozeroy",
            fillcolor="rgba(168, 85, 247, 0.12)",
            name="Volatility",
            hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.1f}%</b><extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=f"Rolling volatility ({window} days, annualized, {_currency_label(currency)})",
                x=0.5,
                xanchor="center",
            ),
            "yaxis_title": "Annualized volatility (%)",
            "height": 400,
            "showlegend": False,
        }
    )
    _apply_axis_style(fig)
    fig.update_yaxes(ticksuffix="%")
    return fig


def plot_sector_allocation(alloc: pd.DataFrame) -> go.Figure:
    if alloc.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Sector allocation – no data")
        return fig

    frame = alloc.copy()
    unknown = frame["sector"] == "Unknown"
    frame = pd.concat([frame[~unknown], frame[unknown]], ignore_index=True)
    frame = frame.sort_values("market_value_pln", ascending=False)

    return plot_allocation_donut(
        frame["sector"].tolist(),
        frame["market_value_pln"].tolist(),
        "Sector allocation",
        color_offset=2,
    )


def plot_company_pnl(company_pnl: pd.DataFrame, currency: str = "pln") -> go.Figure:
    """Horizontal bar chart of total P&L per company from largest profit (top) to largest loss (bottom)."""
    curr_label = _currency_label(currency)
    if company_pnl.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title=f"Company profit and loss ({curr_label}) – no data")
        return fig

    # Sort ascending so the highest profit appears at the top of the horizontal bar chart
    ordered = company_pnl.sort_values("total_pnl", ascending=True).reset_index(drop=True)
    values = ordered["total_pnl"].astype(float).tolist()
    symbols = ordered["symbol"].astype(str).tolist()
    returns_pct = (ordered["return_pct"].astype(float) * 100).tolist()
    statuses = ordered["status"].astype(str).tolist()
    local_pnls = ordered["total_pnl_local"].astype(float).tolist()
    local_currs = ordered["currency"].astype(str).tolist()

    colors = [CHART_COLORS["gain"] if v >= 0 else CHART_COLORS["loss"] for v in values]
    labels = [
        f"{'+' if v >= 0 else ''}{_format_decimal(v, 2)} {curr_label} ({r:+.1f}%)"
        for v, r in zip(values, returns_pct, strict=False)
    ]
    customdata = [
        [
            status,
            f"{'+' if lp >= 0 else ''}{_format_decimal(lp, 2)} {lc}",
            f"{r:+.2f}%",
        ]
        for status, lp, lc, r in zip(statuses, local_pnls, local_currs, returns_pct, strict=False)
    ]

    min_val = min(values + [0.0])
    max_val = max(values + [0.0])
    span = max(max_val - min_val, 1.0)
    left_pad = min_val - span * 0.36 if min_val < 0 else -span * 0.05
    right_pad = max_val + span * 0.38 if max_val > 0 else span * 0.05

    total_profit = sum(v for v in values if v > 0)
    total_loss = sum(v for v in values if v < 0)
    net_total = sum(values)

    fig = go.Figure(
        go.Bar(
            x=values,
            y=symbols,
            orientation="h",
            marker=dict(color=colors, line=dict(width=0), cornerradius=5),
            text=labels,
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=12, color=CHART_COLORS["text"]),
            customdata=customdata,
            hovertemplate=(
                "<b>%{y}</b> (%{customdata[0]})<br>"
                f"P&L ({curr_label}): <b>%{{x:+,.2f}} {curr_label}</b><br>"
                "P&L (account currency): <b>%{customdata[1]}</b><br>"
                "Return: <b>%{customdata[2]}</b><extra></extra>"
            ),
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=(
                    f"Company performance ({curr_label})<br>"
                    f"<sup style='color:#94a3b8'>Gains: <b style='color:#34d399'>+{_format_decimal(total_profit, 2)} {curr_label}</b> | "
                    f"Losses: <b style='color:#f87171'>{_format_decimal(total_loss, 2)} {curr_label}</b> | "
                    f"Net company P&L: <b>{'+' if net_total >= 0 else ''}{_format_decimal(net_total, 2)} {curr_label}</b></sup>"
                ),
                x=0.5,
                xanchor="center",
            ),
            "height": max(380, 90 + 38 * len(ordered)),
            "showlegend": False,
            "margin": dict(l=95, r=155, t=88, b=48),
            "xaxis": dict(
                title=f"Total profit / loss ({curr_label}) – realized + unrealized",
                range=[left_pad, right_pad],
                gridcolor=CHART_COLORS["grid"],
                zeroline=True,
                zerolinecolor="rgba(148, 163, 184, 0.55)",
                zerolinewidth=1.5,
            ),
            "yaxis": dict(title="", automargin=True, tickfont=dict(size=13)),
        }
    )
    return fig


def plot_monthly_deposits(
    deposit_ops: pd.DataFrame,
    currency: str = "pln",
    *,
    years: list[int] | set[int] | None = None,
    by_calendar_month: bool = False,
) -> go.Figure:
    """Interactive monthly bar histogram of inbound deposited capital."""
    from xtb_analyzer.flows import aggregate_deposits_monthly

    curr_label = _currency_label(currency)
    agg = aggregate_deposits_monthly(deposit_ops, years=years, by_calendar_month=by_calendar_month)
    if agg.empty or float(agg["total_amount"].sum()) <= 0:
        fig = go.Figure()
        fig.update_layout(
            **CHART_LAYOUT,
            title=dict(
                text=f"Monthly deposit histogram ({curr_label}) – no deposits",
                x=0.5,
                xanchor="center",
            ),
            height=380,
        )
        return fig

    total_deposited = float(agg["total_amount"].sum())
    total_ops = int(agg["deposit_count"].sum())
    active_months = int((agg["total_amount"] > 0).sum())
    avg_monthly = total_deposited / active_months if active_months > 0 else 0.0

    if by_calendar_month:
        x_vals = agg["month_label"].tolist()
        customdata = [
            [int(r["month"]), str(r["month_label"]), int(r["deposit_count"]), "calendar"]
            for _, r in agg.iterrows()
        ]
        hover = (
            "<b>%{x}</b><br>"
            f"Deposited: <b>%{{y:,.2f}} {curr_label}</b><br>"
            "Operations: <b>%{customdata[2]}</b><extra></extra>"
        )
        scope_label = "Calendar months summed across selected years"
    else:
        x_vals = agg["year_month"].tolist()
        customdata = [
            [str(r["year_month"]), str(r["label"]), int(r["deposit_count"]), int(r["month"])]
            for _, r in agg.iterrows()
        ]
        hover = (
            "<b>%{customdata[1]}</b> (%{x})<br>"
            f"Deposited: <b>%{{y:,.2f}} {curr_label}</b><br>"
            "Operations: <b>%{customdata[2]}</b><extra></extra>"
        )
        scope_label = "Chronological monthly deposits · click any bar to inspect"

    fig = go.Figure(
        go.Bar(
            x=x_vals,
            y=agg["total_amount"].astype(float).tolist(),
            name=f"Deposits ({curr_label})",
            marker=dict(color="#38bdf8", line=dict(width=0), cornerradius=4),
            customdata=customdata,
            hovertemplate=hover,
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "hovermode": "closest",
            "title": dict(
                text=(
                    f"Monthly deposited capital ({curr_label})<br>"
                    f"<sup style='color:#94a3b8'>{scope_label} | "
                    f"Total: <b>{_format_decimal(total_deposited, 2)} {curr_label}</b> | "
                    f"Avg active month: <b>{_format_decimal(avg_monthly, 2)} {curr_label}</b> | "
                    f"Deposits: <b>{total_ops}</b></sup>"
                ),
                x=0.5,
                xanchor="center",
            ),
            "height": 410,
            "showlegend": False,
            "margin": dict(l=68, r=32, t=88, b=68),
            "yaxis": dict(
                title=f"Deposited ({curr_label})",
                gridcolor=CHART_COLORS["grid"],
                tickformat=",.0f",
                zeroline=True,
                zerolinecolor="rgba(148, 163, 184, 0.45)",
            ),
            "xaxis": dict(
                title="",
                type="category",
                tickangle=-35 if not by_calendar_month and len(x_vals) > 18 else 0,
                nticks=14 if not by_calendar_month else 12,
                gridcolor="rgba(148, 163, 184, 0.08)",
            ),
        }
    )
    return fig
