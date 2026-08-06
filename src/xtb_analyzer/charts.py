from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from xtb_analyzer.attribution import FxAttribution
from xtb_analyzer.returns import ReturnMeasures
from xtb_analyzer.risk import drawdown_from_returns, monthly_returns

CHART_COLORS = {
    "nav": "#34d399",
    "deposits": "#64748b",
    "benchmark": "#60a5fa",
    "benchmark_alt": "#c084fc",
    "benchmark_world": "#fbbf24",
    "gain": "#34d399",
    "loss": "#f87171",
    "grid": "rgba(148, 163, 184, 0.14)",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
}

CHART_LAYOUT = dict(
    template="plotly_dark",
    font=dict(family="Inter, 'Segoe UI', Arial, sans-serif", size=13, color=CHART_COLORS["text"]),
    paper_bgcolor="#151a23",
    plot_bgcolor="#10151d",
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
    hoverlabel=dict(bgcolor="#1e293b", bordercolor="#334155", font_size=12),
)

PLOTLY_SHOW_CONFIG = {"displayModeBar": True, "responsive": True}

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
    "sp500": ("S&P 500 TR", CHART_COLORS["benchmark"], "solid"),
    "nasdaq100": ("NASDAQ 100", CHART_COLORS["benchmark_alt"], "dot"),
    "acwi": ("MSCI ACWI", CHART_COLORS["benchmark_world"], "dash"),
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
        f"Start: {data.first_day.strftime('%Y-%m-%d')} (0%)",
        f"Portfel: {_polish_decimal(data.final_portfolio)}%",
    ]
    for key, is_visible in visible.items():
        if is_visible and key in data.final_returns and key in BENCHMARK_META:
            label = BENCHMARK_META[key][0]
            parts.append(f"{label}: {_polish_decimal(data.final_returns[key])}%")
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
            name=f"Twój portfel ({_polish_decimal(data.final_portfolio)}%)",
            mode="lines+markers",
            marker=dict(size=7, color=CHART_COLORS["nav"], line=dict(width=1, color="#0f172a")),
            line=dict(color=CHART_COLORS["nav"], width=3, shape="spline"),
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
                name=f"{label} ({_polish_decimal(data.final_returns[key])}%)",
                mode="lines+markers",
                marker=dict(size=6, color=color, line=dict(width=1, color="#0f172a")),
                line=dict(color=color, width=2.5, shape="spline", dash=dash),
                hovertemplate=HOVER_RETURN,
                visible=visible.get(key, True),
            )
        )

    fig.update_layout(
        **RETURN_CHART_LAYOUT,
        title=dict(
            text=(
                "Zwrot z kapitału – dane miesięczne<br>"
                f"<sup style='color:#94a3b8'>{_comparison_subtitle(data, visible)}</sup>"
            ),
            x=0,
            xanchor="left",
        ),
        yaxis_title="Stopa zwrotu",
        xaxis_title="",
    )
    _style_return_comparison_axes(fig, len(data.portfolio_monthly))
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
                "Zwrot z kapitału – dane miesięczne<br>"
                f"<sup>{_comparison_subtitle(data, visible)}</sup>"
            )

    for box in checkboxes.values():
        box.observe(_update_visibility, names="value")

    panel = widgets.VBox(
        [
            widgets.HTML("<b>Pokaż na wykresie</b>"),
            widgets.HTML("<i>Twój portfel (zawsze)</i>"),
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
                fill_color="#232a36",
                font=dict(color=CHART_COLORS["muted"], size=12),
                align="left",
                height=32,
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


def plot_return_measures(measures: ReturnMeasures) -> go.Figure:
    """Compare ROI, MWR and TWR over the same holding period."""
    items = [
        ("ROI", measures.roi, "prosty zwrot: wartość ÷ wpłaty − 1"),
        ("MWR (XIRR)", measures.mwr, "ważona pieniędzmi – uwzględnia momenty wpłat"),
        ("TWR", measures.twr, "ważona czasem – jakość decyzji, porównywalna z indeksami"),
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
                    f"Stopy zwrotu za cały okres – porównanie metod ({measures.currency})<br>"
                    f"<sup>Okres: {measures.period_days} dni | stan na {measures.as_of}</sup>"
                ),
                x=0,
            ),
            "yaxis_title": "Stopa zwrotu (%)",
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


def plot_drawdown(daily_returns: pd.Series, currency: str = "pln") -> go.Figure:
    drawdown = drawdown_from_returns(daily_returns) * 100
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    fig = go.Figure(
        go.Scatter(
            x=_to_datetime_list(drawdown.index),
            y=drawdown.tolist(),
            mode="lines",
            fill="tozeroy",
            line=dict(color=CHART_COLORS["loss"], width=2),
            fillcolor="rgba(239, 68, 68, 0.18)",
            name="Obsunięcie",
            hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.2f}%</b><extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=(
                    f"Obsunięcia kapitału – TWR ({_currency_label(currency)})<br>"
                    f"<sup>Maksymalne obsunięcie: <b>{_polish_decimal(max_dd)}%</b></sup>"
                ),
                x=0,
            ),
            "yaxis_title": "Obsunięcie (%)",
            "height": 420,
            "showlegend": False,
        }
    )
    _apply_axis_style(fig)
    fig.update_yaxes(ticksuffix="%")
    return fig


MONTH_LABELS = ["Sty", "Lut", "Mar", "Kwi", "Maj", "Cze", "Lip", "Sie", "Wrz", "Paź", "Lis", "Gru"]


def plot_monthly_returns_heatmap(daily_returns: pd.Series, currency: str = "pln") -> go.Figure:
    monthly = monthly_returns(daily_returns) * 100
    if monthly.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Miesięczne stopy zwrotu – brak danych")
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
            colorscale=[[0.0, "#7f1d1d"], [0.45, "#3f1d1d"], [0.5, "#2d2d2d"], [0.55, "#14351f"], [1.0, "#15803d"]],
            hovertemplate="%{y} %{x}<br><b>%{z:+.2f}%</b><extra></extra>",
            colorbar=dict(ticksuffix="%"),
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(text=f"Miesięczne stopy zwrotu TWR ({_currency_label(currency)})", x=0),
            "height": 200 + 60 * len(pivot),
            "margin": dict(l=60, r=40, t=80, b=40),
        }
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def plot_fx_attribution_series(attribution: FxAttribution) -> go.Figure:
    series = attribution.series
    x_dates = _to_datetime_list(series.index)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=series["investment_gain_pln"].tolist(),
            name="Zysk z inwestycji",
            mode="lines",
            stackgroup="gain",
            line=dict(color=CHART_COLORS["nav"], width=1.5),
            hovertemplate="%{x|%Y-%m-%d}<br>Inwestycje: <b>%{y:,.0f} PLN</b><extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=series["fx_gain_pln"].tolist(),
            name="Zysk walutowy",
            mode="lines",
            stackgroup="gain",
            line=dict(color=CHART_COLORS["benchmark"], width=1.5),
            hovertemplate="%{x|%Y-%m-%d}<br>Waluta: <b>%{y:,.0f} PLN</b><extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=series["total_gain_pln"].tolist(),
            name="Zysk łącznie",
            mode="lines",
            line=dict(color=CHART_COLORS["text"], width=2, dash="dot"),
            hovertemplate="%{x|%Y-%m-%d}<br>Łącznie: <b>%{y:,.0f} PLN</b><extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=(
                    "Skąd pochodzi wynik? Inwestycje vs waluta (PLN)<br>"
                    f"<sup>Inwestycje: <b>{_polish_decimal(attribution.investment_gain_pln)}</b> | "
                    f"Waluta: <b>{_polish_decimal(attribution.fx_gain_pln)}</b> | "
                    f"Łącznie: <b>{_polish_decimal(attribution.total_gain_pln)}</b> PLN</sup>"
                ),
                x=0,
            ),
            "yaxis_title": "Zysk / strata (PLN)",
            "height": 480,
        }
    )
    _apply_axis_style(fig)
    return fig


def plot_fx_attribution_waterfall(attribution: FxAttribution) -> go.Figure:
    labels = ["Zysk z inwestycji", "Zysk walutowy", "Wynik łączny"]
    fig = go.Figure(
        go.Waterfall(
            x=labels,
            y=[attribution.investment_gain_pln, attribution.fx_gain_pln, attribution.total_gain_pln],
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
            "title": dict(text="Dekompozycja wyniku: inwestycje + waluta = całość (PLN)", x=0),
            "yaxis_title": "PLN",
            "height": 440,
            "showlegend": False,
        }
    )
    fig.update_yaxes(gridcolor=CHART_COLORS["grid"], tickformat=",.0f")
    return fig


def plot_allocation_donut(
    labels: list[str],
    values: list[float],
    title: str,
    *,
    center_label: str | None = None,
    color_offset: int = 0,
) -> go.Figure:
    """Single donut: percentages inside slices, legend below, optional center total.

    Inside labels + a legend are used instead of outside labels, because outside
    labels with ``automargin`` collapse the chart in narrow containers.
    """
    colors = [PIE_COLORS[(color_offset + i) % len(PIE_COLORS)] for i in range(len(labels))]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            sort=True,
            direction="clockwise",
            textinfo="percent",
            textposition="inside",
            insidetextorientation="horizontal",
            textfont=dict(size=13, color="#0b0e14", family="Inter, 'Segoe UI', Arial, sans-serif"),
            marker=dict(colors=colors, line=dict(color="#151a23", width=2)),
            hovertemplate="<b>%{label}</b><br>%{value:,.0f} PLN (%{percent})<extra></extra>",
        )
    )
    annotations = []
    if center_label:
        annotations.append(
            dict(
                text=center_label,
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color=CHART_COLORS["muted"]),
            )
        )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(text=title, x=0, font=dict(size=16)),
            "height": 460,
            "showlegend": True,
            "legend": dict(
                orientation="h",
                yanchor="top",
                y=-0.02,
                xanchor="center",
                x=0.5,
                font=dict(size=12),
                bgcolor="rgba(0,0,0,0)",
            ),
            "margin": dict(l=20, r=20, t=64, b=100),
            "annotations": annotations,
            "uniformtext": dict(minsize=11, mode="hide"),
        }
    )
    return fig


def _group_top_n(frame: pd.DataFrame, label_col: str, value_col: str, top_n: int) -> pd.DataFrame:
    frame = frame.sort_values(value_col, ascending=False)
    if len(frame) <= top_n:
        return frame
    head = frame.iloc[:top_n]
    rest = pd.DataFrame([{label_col: "Pozostałe", value_col: frame.iloc[top_n:][value_col].sum()}])
    return pd.concat([head, rest], ignore_index=True)


def plot_holdings_allocation(positions: pd.DataFrame, top_n: int = 8) -> go.Figure:
    """Donut: allocation by position (top N + rest)."""
    if positions.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Struktura portfela – brak danych")
        return fig

    by_symbol = positions.groupby("symbol", as_index=False)["market_value_pln"].sum()
    by_symbol = _group_top_n(by_symbol, "symbol", "market_value_pln", top_n)
    total = float(by_symbol["market_value_pln"].sum())
    return plot_allocation_donut(
        by_symbol["symbol"].tolist(),
        by_symbol["market_value_pln"].tolist(),
        "Alokacja wg pozycji",
        center_label=f"{_polish_decimal(total, 0)}<br>PLN",
    )


def plot_currency_allocation(positions: pd.DataFrame) -> go.Figure:
    """Donut: allocation by account currency."""
    if positions.empty:
        fig = go.Figure()
        fig.update_layout(**CHART_LAYOUT, title="Alokacja walutowa – brak danych")
        return fig
    by_currency = positions.groupby("currency", as_index=False)["market_value_pln"].sum()
    return plot_allocation_donut(
        by_currency["currency"].tolist(),
        by_currency["market_value_pln"].tolist(),
        "Alokacja wg waluty rachunku",
        color_offset=4,
    )


def plot_rolling_volatility(daily_returns: pd.Series, window: int = 21, currency: str = "pln") -> go.Figure:
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
            name="Zmienność",
            hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.1f}%</b><extra></extra>",
        )
    )
    fig.update_layout(
        {
            **CHART_LAYOUT,
            "title": dict(
                text=f"Zmienność krocząca ({window} dni, w ujęciu rocznym, {_currency_label(currency)})",
                x=0,
            ),
            "yaxis_title": "Zmienność roczna (%)",
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
        fig.update_layout(**CHART_LAYOUT, title="Alokacja sektorowa portfela – brak danych")
        return fig

    frame = alloc.copy()
    unknown = frame["sector"] == "Unknown"
    frame = pd.concat([frame[~unknown], frame[unknown]], ignore_index=True)
    frame.loc[frame["sector"] == "Unknown", "sector"] = "Nieznany"

    return plot_allocation_donut(
        frame["sector"].tolist(),
        frame["market_value_pln"].tolist(),
        "Alokacja wg sektora",
        color_offset=2,
    )
