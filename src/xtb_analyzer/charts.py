from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CHART_COLORS = {
    "nav": "#2563eb",
    "deposits": "#94a3b8",
    "benchmark": "#f59e0b",
    "gain": "#16a34a",
    "loss": "#dc2626",
    "grid": "#e2e8f0",
}

CHART_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Segoe UI, Arial, sans-serif", size=13, color="#1e293b"),
    paper_bgcolor="#ffffff",
    plot_bgcolor="#f8fafc",
    hovermode="x unified",
    margin=dict(l=60, r=30, t=70, b=50),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)


def _currency_label(currency: str) -> str:
    return currency.upper()


def plot_nav_with_deposits(nav: pd.DataFrame, currency: str = "pln") -> go.Figure:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"
    return_col = f"return_{currency}"

    current_nav = float(nav[nav_col].iloc[-1])
    current_dep = float(nav[dep_col].iloc[-1])
    current_return = float(nav[return_col].iloc[-1]) if return_col in nav.columns else 0.0

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=nav[dep_col],
            name="Skumulowane wpłaty",
            mode="lines",
            line=dict(color=CHART_COLORS["deposits"], width=2.5, shape="hv"),
            fill="tozeroy",
            fillcolor="rgba(148, 163, 184, 0.15)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=nav[nav_col],
            name="Wartość portfela",
            mode="lines",
            line=dict(color=CHART_COLORS["nav"], width=3),
        )
    )

    deposits = nav[dep_col].diff().fillna(nav[dep_col])
    deposit_days = nav.index[deposits > 0]
    for day in deposit_days:
        amount = float(deposits.loc[day])
        fig.add_vline(x=day, line_width=1, line_dash="dot", line_color="#64748b", opacity=0.6)
        fig.add_annotation(
            x=day,
            y=float(nav.loc[day, dep_col]),
            text=f"+{amount:,.0f}",
            showarrow=True,
            arrowhead=2,
            ax=0,
            ay=-35,
            font=dict(size=11, color="#475569"),
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#cbd5e1",
            borderwidth=1,
        )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=(
                f"Wartość portfela vs wpłaty ({_currency_label(currency)})<br>"
                f"<sup>Aktualny zwrot: <b>{current_return:+.1%}</b> | "
                f"Portfel: <b>{current_nav:,.0f}</b> | Wpłaty: <b>{current_dep:,.0f}</b></sup>"
            ),
            x=0,
        ),
        yaxis_title=f"Kwota ({_currency_label(currency)})",
        xaxis_title="Data",
    )
    fig.update_xaxes(showgrid=True, gridcolor=CHART_COLORS["grid"])
    fig.update_yaxes(showgrid=True, gridcolor=CHART_COLORS["grid"], tickformat=",.0f")
    return fig


def plot_benchmark_comparison(
    nav: pd.DataFrame,
    benchmark: pd.Series,
    currency: str = "pln",
) -> go.Figure:
    currency = currency.lower()
    nav_col = f"nav_{currency}"
    dep_col = f"deposits_{currency}"

    portfolio_return = float(nav[nav_col].iloc[-1] / nav[dep_col].iloc[-1] - 1)
    benchmark_return = float(benchmark.iloc[-1] / nav[dep_col].iloc[-1] - 1)
    alpha = portfolio_return - benchmark_return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=nav[nav_col],
            name="Twój portfel",
            mode="lines",
            line=dict(color=CHART_COLORS["nav"], width=3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=benchmark.index,
            y=benchmark,
            name="S&P 500 (wpłaty w te same dni)",
            mode="lines",
            line=dict(color=CHART_COLORS["benchmark"], width=3, dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=nav[dep_col],
            name="Skumulowane wpłaty",
            mode="lines",
            line=dict(color=CHART_COLORS["deposits"], width=2, shape="hv"),
            opacity=0.7,
        )
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=(
                f"Portfel vs S&P 500 przy tych samych wpłatach ({_currency_label(currency)})<br>"
                f"<sup>Twój zwrot: <b>{portfolio_return:+.1%}</b> | "
                f"S&P 500: <b>{benchmark_return:+.1%}</b> | "
                f"Różnica: <b>{alpha:+.1%}</b></sup>"
            ),
            x=0,
        ),
        yaxis_title=f"Wartość ({_currency_label(currency)})",
        xaxis_title="Data",
    )
    fig.update_xaxes(showgrid=True, gridcolor=CHART_COLORS["grid"])
    fig.update_yaxes(showgrid=True, gridcolor=CHART_COLORS["grid"], tickformat=",.0f")
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

    return_series = nav[return_col] * 100

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.35, 0.65],
        specs=[[{"type": "indicator"}, {"type": "scatter"}]],
        subplot_titles=("Aktualna stopa zwrotu", "Zwrot w czasie (%)"),
    )

    fig.add_trace(
        go.Indicator(
            mode="gauge+number+delta",
            value=total_return * 100,
            number={"suffix": "%", "valueformat": "+.2f"},
            delta={"reference": 0, "valueformat": "+.2f"},
            title={"text": f"Zwrot na wpłaconym kapitale ({_currency_label(currency)})"},
            gauge={
                "axis": {"range": [-50, 100]},
                "bar": {"color": CHART_COLORS["gain"] if total_return >= 0 else CHART_COLORS["loss"]},
                "steps": [
                    {"range": [-50, 0], "color": "#fee2e2"},
                    {"range": [0, 100], "color": "#dcfce7"},
                ],
                "threshold": {
                    "line": {"color": "#334155", "width": 2},
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
    fig.add_trace(
        go.Scatter(
            x=[return_series.index[0], return_series.index[-1]],
            y=[0, 0],
            mode="lines",
            line=dict(dash="dash", color="#94a3b8", width=1),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=2,
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(
            text=(
                f"Podsumowanie zwrotu<br>"
                f"<sup>Zainwestowano: {invested:,.0f} | Wartość: {current_nav:,.0f} | "
                f"Zysk/strata: {gain:+,.0f} {_currency_label(currency)}</sup>"
            ),
            x=0,
        ),
        showlegend=False,
        height=420,
    )
    fig.update_yaxes(title_text="Zwrot (%)", row=1, col=2)
    return fig


def plot_conversion_losses(losses: pd.DataFrame, summary: dict[str, float]) -> go.Figure:
    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.55, 0.45],
        specs=[[{"type": "bar"}, {"type": "table"}]],
        subplot_titles=("Strata per przewalutowanie (PLN)", "Podsumowanie kosztów FX"),
    )

    if not losses.empty:
        fig.add_trace(
            go.Bar(
                x=losses["timestamp"],
                y=losses["total_loss_pln"],
                name="Strata PLN",
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
                name="Strata skumulowana",
                mode="lines+markers",
                line=dict(color="#7f1d1d", width=2),
                yaxis="y2",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Table(
            header=dict(
                values=["Metryka", "Wartość"],
                fill_color="#e2e8f0",
                align="left",
            ),
            cells=dict(
                values=[
                    [
                        "Suma przewalutowanych PLN",
                        "Prowizja 0,5%",
                        "Strata na spreadzie",
                        "Łączna strata FX",
                        "Średni koszt FX",
                    ],
                    [
                        f"{summary['total_pln_converted']:,.2f} PLN",
                        f"{summary['total_commission_pln']:,.2f} PLN",
                        f"{summary['total_spread_pln']:,.2f} PLN",
                        f"{summary['total_loss_pln']:,.2f} PLN",
                        f"{summary['avg_loss_pct']:.2%}",
                    ],
                ],
                align="left",
            ),
        ),
        row=1,
        col=2,
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title="Koszt przewalutowań PLN → USD/EUR (XTB 0,5% + spread vs NBP)",
        height=480,
        yaxis2=dict(title="Skumulowana strata", overlaying="y", side="right"),
    )
    fig.update_yaxes(title_text="PLN", row=1, col=1)
    return fig
