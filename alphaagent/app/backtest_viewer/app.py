"""Streamlit dashboard for AlphaAgent Qlib backtest artifacts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from alphaagent.app.backtest_viewer.loader import (
    DEFAULT_WORKSPACE_ROOT,
    BacktestArtifacts,
    build_summary,
    list_workspaces,
    load_backtest,
)

st.set_page_config(
    page_title="AlphaAgent 回测详情",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _cum_series(report: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=report.index)
    df["策略(不含成本)"] = report["return"].cumsum()
    df["策略(含成本)"] = (report["return"] - report["cost"]).cumsum()
    df["基准"] = report["bench"].cumsum()
    df["超额(不含成本)"] = (report["return"] - report["bench"]).cumsum()
    df["超额(含成本)"] = (report["return"] - report["bench"] - report["cost"]).cumsum()
    return df


def _return_figure(report: pd.DataFrame, compare: BacktestArtifacts | None = None) -> go.Figure:
    cum = _cum_series(report)
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
        compare_cum = _cum_series(compare.report)
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


def _excess_figure(report: pd.DataFrame) -> go.Figure:
    cum = _cum_series(report)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cum.index, y=cum["超额(不含成本)"], name="超额(不含成本)", line=dict(color="#7c3aed")))
    fig.add_trace(go.Scatter(x=cum.index, y=cum["超额(含成本)"], name="超额(含成本)", line=dict(color="#0891b2")))
    fig.add_hline(y=0, line_dash="dot", line_color="#94a3b8")
    fig.update_layout(title="累计超额收益", xaxis_title="日期", yaxis_title="超额", height=320)
    return fig


def _turnover_cost_figure(report: pd.DataFrame) -> go.Figure:
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


def _account_figure(report: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=report.index, y=report["account"], name="总资产", line=dict(color="#2563eb", width=2)))
    fig.add_trace(go.Scatter(x=report.index, y=report["value"], name="持仓市值", line=dict(color="#16a34a", width=1.5)))
    fig.add_trace(go.Scatter(x=report.index, y=report["cash"], name="现金", line=dict(color="#94a3b8", width=1.5)))
    fig.update_layout(title="账户资产构成", xaxis_title="日期", yaxis_title="金额", height=320, hovermode="x unified")
    return fig


def _filter_by_date(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    if df.empty or "datetime" not in df.columns:
        return df
    day = pd.Timestamp(day).normalize()
    return df[df["datetime"].dt.normalize() == day]


def _format_trade_table(df: pd.DataFrame) -> pd.DataFrame:
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


def _format_holding_table(df: pd.DataFrame) -> pd.DataFrame:
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


def _workspace_label(path: Path) -> str:
    mtime = pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")
    return f"{path.name[:12]}…  ({mtime})"


def main() -> None:
    st.title("📊 AlphaAgent 回测详情")
    st.caption("读取 workspace 中的 ret.pkl / positions / indicators，展示每日交易、持仓与收益对比。")

    root = Path(st.sidebar.text_input("Workspace 根目录", value=str(DEFAULT_WORKSPACE_ROOT)))
    workspaces = list_workspaces(root)

    if not workspaces:
        st.warning(f"在 `{root}` 下未找到含 ret.pkl 的回测 workspace。请先成功运行 `alphaagent mine` 或 `alphaagent backtest`。")
        st.stop()

    labels = [_workspace_label(w) for w in workspaces]
    idx = st.sidebar.selectbox("主回测 workspace", range(len(workspaces)), format_func=lambda i: labels[i])
    workspace = workspaces[idx]

    compare_idx = st.sidebar.selectbox(
        "对比 workspace（可选 baseline）",
        options=[None, *range(len(workspaces))],
        format_func=lambda i: "不对比" if i is None else labels[i],
    )

    try:
        data = load_backtest(workspace)
    except Exception as exc:
        st.error(f"加载失败: {exc}")
        st.stop()

    compare_data = None
    if compare_idx is not None and compare_idx != idx:
        try:
            compare_data = load_backtest(workspaces[compare_idx])
        except Exception as exc:
            st.sidebar.warning(f"对比 workspace 加载失败: {exc}")

    report = data.report
    min_date, max_date = report.index.min(), report.index.max()
    date_range = st.sidebar.slider(
        "日期范围",
        min_value=min_date.to_pydatetime(),
        max_value=max_date.to_pydatetime(),
        value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
    )
    mask = (report.index >= pd.Timestamp(date_range[0])) & (report.index <= pd.Timestamp(date_range[1]))
    report_slice = report.loc[mask]

    summary = build_summary(report_slice)
    cols = st.columns(6)
    metrics = [
        ("累计收益(含成本)", f"{summary['累计收益(含成本)']:.2%}"),
        ("基准累计", f"{summary['基准累计收益']:.2%}"),
        ("累计超额", f"{summary['累计超额(不含成本)']:.2%}"),
        ("最大回撤", f"{summary['最大回撤(不含成本)']:.2%}"),
        ("平均日换手", f"{summary['平均日换手']:.2%}"),
        ("累计手续费", f"{summary['累计手续费']:.4f}"),
    ]
    for col, (label, val) in zip(cols, metrics):
        col.metric(label, val)

    st.plotly_chart(_return_figure(report_slice, compare_data), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(_excess_figure(report_slice), use_container_width=True)
    with c2:
        st.plotly_chart(_account_figure(report_slice), use_container_width=True)

    st.plotly_chart(_turnover_cost_figure(report_slice), use_container_width=True)

    st.divider()
    st.subheader("每日明细")

    available_days = sorted(report_slice.index.unique())
    selected_day = st.selectbox(
        "选择交易日",
        available_days,
        index=len(available_days) - 1,
        format_func=lambda d: pd.Timestamp(d).strftime("%Y-%m-%d"),
    )
    selected_day = pd.Timestamp(selected_day)

    day_report = report_slice.loc[selected_day] if selected_day in report_slice.index else None
    if day_report is not None:
        dcols = st.columns(5)
        day_items = [
            ("日收益", f"{day_report.get('return', 0):.4%}"),
            ("基准收益", f"{day_report.get('bench', 0):.4%}"),
            ("日换手", f"{day_report.get('turnover', 0):.4%}"),
            ("日手续费", f"{day_report.get('cost', 0):.4f}"),
            ("总资产", f"{day_report.get('account', 0):,.0f}"),
        ]
        for col, (label, val) in zip(dcols, day_items):
            col.metric(label, val)

    tab_trades, tab_holdings, tab_all_trades, tab_metrics = st.tabs(
        ["当日交易", "当日持仓", "全部交易记录", "回测指标"]
    )

    trades_slice = _filter_by_date(data.trades, selected_day)
    holdings_slice = _filter_by_date(data.holdings, selected_day)

    with tab_trades:
        buy_n = len(trades_slice[trades_slice["status"] == 1]) if not trades_slice.empty else 0
        sell_n = len(trades_slice[trades_slice["status"] == -1]) if not trades_slice.empty else 0
        st.info(f"{selected_day.strftime('%Y-%m-%d')}：买入 {buy_n} 笔，卖出 {sell_n} 笔")
        if trades_slice.empty:
            st.write("当日无调仓记录。")
        else:
            st.dataframe(_format_trade_table(trades_slice), use_container_width=True, hide_index=True)

    with tab_holdings:
        if holdings_slice.empty:
            st.write("当日无持仓数据。")
        else:
            st.dataframe(_format_holding_table(holdings_slice), use_container_width=True, hide_index=True)

    with tab_all_trades:
        if data.trades.empty:
            st.write("无交易记录。")
        else:
            filtered = data.trades[
                (data.trades["datetime"] >= pd.Timestamp(date_range[0]))
                & (data.trades["datetime"] <= pd.Timestamp(date_range[1]))
            ]
            st.dataframe(_format_trade_table(filtered), use_container_width=True, hide_index=True)

    with tab_metrics:
        if data.metrics is not None and not (isinstance(data.metrics, pd.Series) and data.metrics.empty):
            st.dataframe(data.metrics.rename("value").reset_index().rename(columns={"index": "metric"}))
        else:
            st.write("无 qlib_res.csv 指标文件。")

    with st.expander("数据路径"):
        st.code(str(data.workspace), language=None)
        st.write(f"- ret.pkl: `{(data.workspace / 'ret.pkl').exists()}`")
        st.write(f"- positions: `{len(data.positions)}` 天")
        st.write(f"- indicators: `{data.indicators is not None}`")


if __name__ == "__main__":
    main()
