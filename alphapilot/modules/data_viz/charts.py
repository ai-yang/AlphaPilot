"""Interactive candlestick charts (Plotly)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_candlestick_figure(df: pd.DataFrame, *, title: str = "") -> go.Figure:
    """K-line + volume chart with rich hover tooltips."""
    required = {"date", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"数据缺少 K 线字段: {sorted(missing)}")

    plot_df = df.copy()
    has_volume = "volume" in plot_df.columns and plot_df["volume"].notna().any()

    rows = 2 if has_volume else 1
    row_heights = [0.72, 0.28] if has_volume else [1.0]
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
    )

    hover_parts = [
        "日期: %{x|%Y-%m-%d}",
        "开盘: %{open:.4f}",
        "最高: %{high:.4f}",
        "最低: %{low:.4f}",
        "收盘: %{close:.4f}",
    ]
    extra_series: list[pd.Series] = []
    if "pctChg" in plot_df.columns:
        extra_series.append(plot_df["pctChg"].fillna(0))
        hover_parts.append(f"涨跌幅: %{{customdata[{len(extra_series) - 1}]:.2f}}%")
    if "amount" in plot_df.columns:
        extra_series.append(plot_df["amount"].fillna(0))
        hover_parts.append(f"成交额: %{{customdata[{len(extra_series) - 1}]:,.0f}}")
    if "turn" in plot_df.columns:
        extra_series.append(plot_df["turn"].fillna(0))
        hover_parts.append(f"换手率: %{{customdata[{len(extra_series) - 1}]:.2f}}%")

    customdata = (
        pd.concat(extra_series, axis=1).values if extra_series else None
    )

    fig.add_trace(
        go.Candlestick(
            x=plot_df["date"],
            open=plot_df["open"],
            high=plot_df["high"],
            low=plot_df["low"],
            close=plot_df["close"],
            name="K线",
            increasing_line_color="#ef4444",
            decreasing_line_color="#22c55e",
            increasing_fillcolor="#ef4444",
            decreasing_fillcolor="#22c55e",
            customdata=customdata,
            hovertemplate="<br>".join(hover_parts) + "<extra></extra>",
        ),
        row=1,
        col=1,
    )

    if has_volume:
        colors = [
            "#ef4444" if c >= o else "#22c55e"
            for o, c in zip(plot_df["open"], plot_df["close"])
        ]
        fig.add_trace(
            go.Bar(
                x=plot_df["date"],
                y=plot_df["volume"],
                name="成交量",
                marker_color=colors,
                opacity=0.75,
                hovertemplate="日期: %{x|%Y-%m-%d}<br>成交量: %{y:,.0f}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    fig.update_layout(
        title=title or "K线图",
        xaxis_rangeslider_visible=False,
        height=720 if has_volume else 560,
        margin=dict(l=50, r=30, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(type="date", row=rows, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    if has_volume:
        fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig
