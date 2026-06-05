"""Plotly charts and table formatters for backtest artifact viewer."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from alphapilot.systems.backtest.artifacts import BacktestArtifacts


def cum_series(report: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=report.index)
    df["策略(不含成本)"] = report["return"].cumsum()
    df["策略(含成本)"] = (report["return"] - report["cost"]).cumsum()
    df["基准"] = report["bench"].cumsum()
    df["超额(不含成本)"] = (report["return"] - report["bench"]).cumsum()
    df["超额(含成本)"] = (report["return"] - report["bench"] - report["cost"]).cumsum()
    return df


def return_figure(report: pd.DataFrame, compare: BacktestArtifacts | None = None) -> go.Figure:
    cum = cum_series(report)
    fig = go.Figure()
    colors = {
        "策略(不含成本)": "#2563eb",
        "策略(含成本)": "#16a34a",
        "基准": "#f97316",
        "超额(不含成本)": "#7c3aed",
    }
    for col in ["策略(不含成本)", "策略(含成本)", "基准"]:
        fig.add_trace(
            go.Scatter(
                x=cum.index,
                y=cum[col],
                mode="lines",
                name=col,
                line=dict(width=2, color=colors[col]),
            )
        )
    if compare is not None:
        compare_cum = cum_series(compare.report)
        fig.add_trace(
            go.Scatter(
                x=compare_cum.index,
                y=compare_cum["策略(含成本)"],
                mode="lines",
                name=f"对比: {compare.workspace.name[:8]}…",
                line=dict(width=2, dash="dash", color="#dc2626"),
            )
        )
    fig.update_layout(
        title="累计收益对比",
        xaxis_title="日期",
        yaxis_title="累计收益率",
        hovermode="x unified",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=40, r=20, t=60, b=40),
    )
    return fig


def excess_figure(report: pd.DataFrame) -> go.Figure:
    cum = cum_series(report)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cum.index, y=cum["超额(不含成本)"], name="超额(不含成本)", line=dict(color="#7c3aed")))
    fig.add_trace(go.Scatter(x=cum.index, y=cum["超额(含成本)"], name="超额(含成本)", line=dict(color="#0891b2")))
    fig.add_hline(y=0, line_dash="dot", line_color="#94a3b8")
    fig.update_layout(title="累计超额收益", xaxis_title="日期", yaxis_title="超额", height=320)
    return fig


def turnover_cost_figure(report: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=report.index, y=report["turnover"], name="日换手", marker_color="#60a5fa", opacity=0.7),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=report.index, y=report["cost"], name="日手续费", line=dict(color="#ef4444", width=1.5)),
        secondary_y=True,
    )
    fig.update_layout(title="换手率 & 手续费", height=320, hovermode="x unified")
    fig.update_yaxes(title_text="换手率", secondary_y=False)
    fig.update_yaxes(title_text="手续费", secondary_y=True)
    return fig


def account_figure(report: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=report.index, y=report["account"], name="总资产", line=dict(color="#2563eb", width=2)))
    fig.add_trace(go.Scatter(x=report.index, y=report["value"], name="持仓市值", line=dict(color="#16a34a", width=1.5)))
    fig.add_trace(go.Scatter(x=report.index, y=report["cash"], name="现金", line=dict(color="#94a3b8", width=1.5)))
    fig.update_layout(title="账户资产构成", xaxis_title="日期", yaxis_title="金额", height=320, hovermode="x unified")
    return fig


def filter_by_date(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    if df.empty or "datetime" not in df.columns:
        return df
    day = pd.Timestamp(day).normalize()
    return df[df["datetime"].dt.normalize() == day]


def format_trade_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["datetime", "instrument", "status_label", "amount", "price", "weight"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    rename = {
        "datetime": "日期",
        "instrument": "股票",
        "status_label": "方向",
        "amount": "数量",
        "price": "价格",
        "weight": "权重",
    }
    return out.rename(columns=rename)


def format_holding_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["datetime", "instrument", "amount", "price", "weight", "cash"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    rename = {
        "datetime": "日期",
        "instrument": "股票",
        "amount": "持仓数量",
        "price": "价格",
        "weight": "权重",
        "cash": "账户现金",
    }
    return out.rename(columns=rename)
