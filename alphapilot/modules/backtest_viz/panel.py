"""Reusable backtest artifact viewer panel (portal tab + standalone app)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from alphapilot.modules.backtest_viz import charts
from alphapilot.systems.backtest.artifacts import (
    DEFAULT_LOG_ROOT,
    DEFAULT_WORKSPACE_ROOT,
    BacktestArtifacts,
    build_summary,
    build_workspace_log_titles,
    format_workspace_label,
    list_workspaces,
    load_backtest,
)

TranslateFn = Callable[..., str]

_DEFAULT_ZH: dict[str, str] = {
    "bt_detail_caption": "读取 workspace 中的 ret.pkl / positions / indicators，展示每日交易、持仓与收益对比。",
    "bt_workspace_root": "Workspace 根目录",
    "bt_log_root": "Log 目录（用于显示会话标题）",
    "bt_no_workspaces": "在 `{root}` 下未找到含 ret.pkl 的回测 workspace。请先成功运行 `alphapilot mine` 或 `alphapilot backtest`。",
    "bt_main_workspace": "主回测 workspace",
    "bt_compare_workspace": "对比 workspace（可选 baseline）",
    "bt_no_compare": "不对比",
    "bt_log_session": "对应 log 会话：`{title}`",
    "bt_log_session_missing": "未在 log 目录中匹配到会话标题，显示为 workspace 目录名。",
    "bt_load_failed": "加载失败: {error}",
    "bt_compare_load_failed": "对比 workspace 加载失败: {error}",
    "bt_date_range": "日期范围",
    "bt_daily_detail": "每日明细",
    "bt_select_day": "选择交易日",
    "bt_tab_trades": "当日交易",
    "bt_tab_holdings": "当日持仓",
    "bt_tab_all_trades": "全部交易记录",
    "bt_tab_metrics": "回测指标",
    "bt_trade_summary": "{day}：买入 {buy} 笔，卖出 {sell} 笔",
    "bt_no_trades_day": "当日无调仓记录。",
    "bt_no_holdings_day": "当日无持仓数据。",
    "bt_no_trades": "无交易记录。",
    "bt_no_metrics": "无 qlib_res.csv 指标文件。",
    "bt_data_paths": "数据路径",
    "bt_filters_expander": "回测筛选条件",
    "bt_sidebar_header": "回测 workspace",
    "bt_detail_title": "回测详情",
}


def _msg(translate: TranslateFn | None, key: str, **kwargs: Any) -> str:
    if translate is not None:
        try:
            return translate(key, **kwargs)
        except KeyError:
            pass
    text = _DEFAULT_ZH.get(key, key)
    return text.format(**kwargs) if kwargs else text


@st.cache_data(show_spinner=False)
def _cached_log_titles(log_root: str, workspace_root: str) -> dict[str, str]:
    return build_workspace_log_titles(Path(log_root), Path(workspace_root))


def render_backtest_panel(
    *,
    workspace_root: Path | str | None = None,
    log_root: Path | str | None = None,
    translate: TranslateFn | None = None,
    use_sidebar: bool = False,
    show_heading: bool = True,
    key_prefix: str = "bt",
    load_fn: Callable[[Path | str], BacktestArtifacts] | None = None,
) -> None:
    """Render backtest artifact viewer.

    Parameters
    ----------
    use_sidebar:
        ``True`` for standalone (controls in sidebar).
        ``False`` for portal tab (controls inside an expander).
    load_fn:
        Optional loader override (e.g. ``backtest_system.results.load``).
    """
    default_root = Path(workspace_root) if workspace_root is not None else DEFAULT_WORKSPACE_ROOT
    default_log = Path(log_root) if log_root is not None else DEFAULT_LOG_ROOT
    _load = load_fn or load_backtest

    def _text_input(label: str, value: str, **kwargs: Any) -> str:
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.text_input(label, value=value, **kwargs)

    def _selectbox(label: str, options: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.selectbox(label, options, **kwargs)

    def _slider(label: str, **kwargs: Any) -> Any:
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.slider(label, **kwargs)

    if use_sidebar:
        st.sidebar.header(_msg(translate, "bt_sidebar_header"))
        ctrl = st.sidebar
    else:
        ctrl = st.expander(_msg(translate, "bt_filters_expander"), expanded=True)

    with ctrl:
        root = Path(_text_input(_msg(translate, "bt_workspace_root"), str(default_root)))
        log_path = Path(_text_input(_msg(translate, "bt_log_root"), str(default_log)))

    log_titles = _cached_log_titles(str(log_path.resolve()), str(root.resolve()))
    workspaces = list_workspaces(root)

    if not workspaces:
        st.warning(_msg(translate, "bt_no_workspaces", root=root))
        return

    labels = [format_workspace_label(w, log_titles, workspaces) for w in workspaces]

    with ctrl:
        idx = _selectbox(
            _msg(translate, "bt_main_workspace"),
            range(len(workspaces)),
            format_func=lambda i: labels[i],
        )
        workspace = workspaces[idx]
        main_log_title = log_titles.get(workspace.name)

        compare_idx = _selectbox(
            _msg(translate, "bt_compare_workspace"),
            options=[None, *range(len(workspaces))],
            format_func=lambda i: _msg(translate, "bt_no_compare") if i is None else labels[i],
        )

        if main_log_title:
            st.markdown(_msg(translate, "bt_log_session", title=main_log_title))
        else:
            st.caption(_msg(translate, "bt_log_session_missing"))

    if show_heading:
        title_suffix = f" — {main_log_title}" if main_log_title else ""
        st.subheader(f"📊 {_msg(translate, 'bt_detail_title')}{title_suffix}")
    st.caption(
        _msg(translate, "bt_detail_caption")
        + f" (`{workspace.name}`)"
    )

    try:
        data = _load(workspace)
    except Exception as exc:
        st.error(_msg(translate, "bt_load_failed", error=exc))
        return

    compare_data: BacktestArtifacts | None = None
    if compare_idx is not None and compare_idx != idx:
        try:
            compare_data = _load(workspaces[compare_idx])
        except Exception as exc:
            st.warning(_msg(translate, "bt_compare_load_failed", error=exc))

    report = data.report
    min_date, max_date = report.index.min(), report.index.max()

    with ctrl:
        date_range = _slider(
            _msg(translate, "bt_date_range"),
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

    st.plotly_chart(charts.return_figure(report_slice, compare_data), width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.excess_figure(report_slice), width="stretch")
    with c2:
        st.plotly_chart(charts.account_figure(report_slice), width="stretch")

    st.plotly_chart(charts.turnover_cost_figure(report_slice), width="stretch")

    st.divider()
    st.subheader(_msg(translate, "bt_daily_detail"))

    available_days = sorted(report_slice.index.unique())
    selected_day = st.selectbox(
        _msg(translate, "bt_select_day"),
        available_days,
        index=len(available_days) - 1,
        format_func=lambda d: pd.Timestamp(d).strftime("%Y-%m-%d"),
        key=f"{key_prefix}_select_day",
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
        [
            _msg(translate, "bt_tab_trades"),
            _msg(translate, "bt_tab_holdings"),
            _msg(translate, "bt_tab_all_trades"),
            _msg(translate, "bt_tab_metrics"),
        ]
    )

    trades_slice = charts.filter_by_date(data.trades, selected_day)
    holdings_slice = charts.filter_by_date(data.holdings, selected_day)

    with tab_trades:
        buy_n = len(trades_slice[trades_slice["status"] == 1]) if not trades_slice.empty else 0
        sell_n = len(trades_slice[trades_slice["status"] == -1]) if not trades_slice.empty else 0
        st.info(
            _msg(
                translate,
                "bt_trade_summary",
                day=selected_day.strftime("%Y-%m-%d"),
                buy=buy_n,
                sell=sell_n,
            )
        )
        if trades_slice.empty:
            st.write(_msg(translate, "bt_no_trades_day"))
        else:
            st.dataframe(charts.format_trade_table(trades_slice), width="stretch", hide_index=True)

    with tab_holdings:
        if holdings_slice.empty:
            st.write(_msg(translate, "bt_no_holdings_day"))
        else:
            st.dataframe(charts.format_holding_table(holdings_slice), width="stretch", hide_index=True)

    with tab_all_trades:
        if data.trades.empty:
            st.write(_msg(translate, "bt_no_trades"))
        else:
            filtered = data.trades[
                (data.trades["datetime"] >= pd.Timestamp(date_range[0]))
                & (data.trades["datetime"] <= pd.Timestamp(date_range[1]))
            ]
            st.dataframe(charts.format_trade_table(filtered), width="stretch", hide_index=True)

    with tab_metrics:
        if data.metrics is not None and not (isinstance(data.metrics, pd.Series) and data.metrics.empty):
            st.dataframe(data.metrics.rename("value").reset_index().rename(columns={"index": "metric"}))
        else:
            st.write(_msg(translate, "bt_no_metrics"))

    with st.expander(_msg(translate, "bt_data_paths")):
        st.code(str(data.workspace), language=None)
        st.write(f"- ret.pkl: `{(data.workspace / 'ret.pkl').exists()}`")
        st.write(f"- positions: `{len(data.positions)}` 天")
        st.write(f"- indicators: `{data.indicators is not None}`")
