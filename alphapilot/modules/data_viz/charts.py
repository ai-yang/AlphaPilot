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

    hover_text = []
    for row in plot_df.itertuples(index=False):
        row_data = row._asdict()
        date_text = pd.to_datetime(row_data["date"]).strftime("%Y-%m-%d")
        parts = [
            f"日期: {date_text}",
            f"开盘: {row_data['open']:.4f}",
            f"最高: {row_data['high']:.4f}",
            f"最低: {row_data['low']:.4f}",
            f"收盘: {row_data['close']:.4f}",
        ]
        if "pctChg" in plot_df.columns:
            value = row_data.get("pctChg", 0)
            parts.append(f"涨跌幅: {0 if pd.isna(value) else value:.2f}%")
        if "amount" in plot_df.columns:
            value = row_data.get("amount", 0)
            parts.append(f"成交额: {0 if pd.isna(value) else value:,.0f}")
        if "turn" in plot_df.columns:
            value = row_data.get("turn", 0)
            parts.append(f"换手率: {0 if pd.isna(value) else value:.2f}%")
        hover_text.append("<br>".join(parts))

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
            text=hover_text,
            hoverinfo="text",
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
        title=dict(
            text=title or "K线图",
            x=0.01,
            y=0.99,
            xanchor="left",
            yanchor="top",
            font=dict(size=14),
        ),
        xaxis_rangeslider_visible=False,
        height=720 if has_volume else 560,
        margin=dict(l=50, r=30, t=82, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.04,
            xanchor="right",
            x=1,
        ),
        hovermode="x",
        hoverlabel=dict(
            align="left",
            bgcolor="rgba(17, 24, 39, 0.92)",
            bordercolor="rgba(148, 163, 184, 0.75)",
            font=dict(color="white", size=12),
        ),
    )
    fig.update_xaxes(type="date")
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="#94a3b8",
        spikethickness=1,
    )
    fig.update_yaxes(
        title_text="价格",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="#94a3b8",
        spikethickness=1,
        row=1,
        col=1,
    )
    if has_volume:
        fig.update_yaxes(title_text="成交量", row=2, col=1)

    return fig
