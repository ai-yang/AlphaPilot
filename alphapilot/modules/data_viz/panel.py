"""Reusable stock K-line panel (portal tab + standalone app)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pandas as pd
import streamlit as st

from alphapilot.modules.data_viz.charts import build_candlestick_figure
from alphapilot.modules.data_viz.loader import (
    available_date_range,
    format_symbol_label,
    list_data_sources,
    list_symbols,
    load_bars,
)

TranslateFn = Callable[..., str]

_DEFAULT_ZH: dict[str, str] = {
    "tab_data_viz": "股票 K 线",
    "dv_caption": "查看 `prepare_data` 下载的本地 CSV 行情，支持时间段筛选与 K 线悬停详情。",
    "dv_no_sources": "未找到本地行情 CSV 目录。请先执行：`alphapilot prepare_data --action download ...`",
    "dv_sidebar_header": "数据与标的",
    "dv_source": "复权类型 / 数据目录",
    "dv_no_csv": "目录 `{path}` 下没有 CSV 文件。",
    "dv_symbol_search": "快速筛选代码",
    "dv_symbol": "股票代码",
    "dv_no_match": "无匹配股票，显示全部列表。",
    "dv_load_failed": "加载失败：{error}",
    "dv_no_bars": "该股票暂无行情数据。",
    "dv_time_range": "时间区间",
    "dv_preset_custom": "自定义",
    "dv_preset_1m": "近1月",
    "dv_preset_3m": "近3月",
    "dv_preset_6m": "近6月",
    "dv_preset_1y": "近1年",
    "dv_preset_all": "全部",
    "dv_date_range": "日期范围",
    "dv_date_invalid": "开始日期不能晚于结束日期。",
    "dv_range_empty": "所选时间段内无数据。",
    "dv_metric_days": "交易日数",
    "dv_metric_return": "区间涨跌",
    "dv_metric_high": "最高价",
    "dv_metric_low": "最低价",
    "dv_hover_help_title": "悬停说明",
    "dv_hover_help": (
        "将鼠标移到 K 线上可查看当日 **开/高/低/收**；若 CSV 含扩展字段，还会显示 "
        "**涨跌幅、成交额、换手率**。下方表格为当前区间明细，可排序与导出。"
    ),
    "dv_export_csv": "导出当前区间 CSV",
    "dv_filters_expander": "K 线筛选条件",
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
def _cached_sources():
    return list_data_sources()


@st.cache_data(show_spinner=False)
def _cached_symbols(data_dir: str) -> list[str]:
    return list_symbols(data_dir)


def render_data_viz_panel(
    *,
    translate: TranslateFn | None = None,
    use_sidebar: bool = False,
    show_heading: bool = True,
    key_prefix: str = "dv",
) -> None:
    """Render stock K-line viewer.

    Parameters
    ----------
    use_sidebar:
        ``True`` for standalone ``alphapilot data_viz`` (controls in sidebar).
        ``False`` for portal tab (controls inside an expander).
    """
    if show_heading:
        st.subheader(f"📈 {_msg(translate, 'tab_data_viz')}")
    st.caption(_msg(translate, "dv_caption"))

    sources = _cached_sources()
    if not sources:
        st.warning(_msg(translate, "dv_no_sources"))
        return

    def _selectbox(label, options, **kwargs):
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.selectbox(label, options, **kwargs)

    def _text_input(label, **kwargs):
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.text_input(label, **kwargs)

    def _radio(label, options, **kwargs):
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.radio(label, options, **kwargs)

    def _date_input(label, **kwargs):
        kwargs.setdefault("key", f"{key_prefix}_{label}")
        return st.date_input(label, **kwargs)

    if use_sidebar:
        st.sidebar.header(_msg(translate, "dv_sidebar_header"))
        ctrl = st.sidebar
    else:
        ctrl = st.expander(_msg(translate, "dv_filters_expander"), expanded=True)

    with ctrl:
        source_labels = [s.label for s in sources]
        source_idx = _selectbox(
            _msg(translate, "dv_source"),
            range(len(sources)),
            format_func=lambda i: source_labels[i],
        )
        source = sources[source_idx]
        st.code(str(source.path), language=None)

        symbols = _cached_symbols(str(source.path))
        if not symbols:
            st.warning(_msg(translate, "dv_no_csv", path=source.path))
            return

        symbol_labels = {s: format_symbol_label(s) for s in symbols}
        search = _text_input(_msg(translate, "dv_symbol_search"), value="")
        symbol_choices = symbols
        if search.strip():
            key = search.strip().lower().replace(".", "")
            symbol_choices = [
                s for s in symbols if key in s or key in symbol_labels[s].replace(".", "")
            ]
            if not symbol_choices:
                st.warning(_msg(translate, "dv_no_match"))
                symbol_choices = symbols

        symbol = _selectbox(
            _msg(translate, "dv_symbol"),
            symbol_choices,
            format_func=lambda s: symbol_labels[s],
        )

        try:
            full_df = load_bars(symbol, source.path)
        except Exception as exc:  # noqa: BLE001
            st.error(_msg(translate, "dv_load_failed", error=exc))
            return

        if full_df.empty:
            st.warning(_msg(translate, "dv_no_bars"))
            return

        dmin, dmax = available_date_range(full_df)
        preset_labels = [
            _msg(translate, "dv_preset_custom"),
            _msg(translate, "dv_preset_1m"),
            _msg(translate, "dv_preset_3m"),
            _msg(translate, "dv_preset_6m"),
            _msg(translate, "dv_preset_1y"),
            _msg(translate, "dv_preset_all"),
        ]
        preset = _radio(_msg(translate, "dv_time_range"), preset_labels, horizontal=True)
        today = dmax
        preset_map = {
            preset_labels[1]: today - timedelta(days=31),
            preset_labels[2]: today - timedelta(days=93),
            preset_labels[3]: today - timedelta(days=186),
            preset_labels[4]: today - timedelta(days=365),
            preset_labels[5]: dmin,
        }
        if preset != preset_labels[0]:
            start_date, end_date = preset_map[preset], today
        else:
            start_date, end_date = _date_input(
                _msg(translate, "dv_date_range"),
                value=(max(dmin, today - timedelta(days=93)), today),
                min_value=dmin,
                max_value=dmax,
            )

    if start_date > end_date:
        st.error(_msg(translate, "dv_date_invalid"))
        return

    df = full_df[
        (full_df["date"] >= pd.Timestamp(start_date))
        & (full_df["date"] <= pd.Timestamp(end_date))
    ].reset_index(drop=True)

    if df.empty:
        st.warning(_msg(translate, "dv_range_empty"))
        return

    label = symbol_labels[symbol]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(_msg(translate, "dv_metric_days"), len(df))
    c2.metric(
        _msg(translate, "dv_metric_return"),
        f"{(df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100:.2f}%",
    )
    c3.metric(_msg(translate, "dv_metric_high"), f"{df['high'].max():.4f}")
    c4.metric(_msg(translate, "dv_metric_low"), f"{df['low'].min():.4f}")

    title = f"{label} | {start_date} ~ {end_date} | {source.label}"
    st.plotly_chart(build_candlestick_figure(df, title=title), use_container_width=True)

    st.markdown(f"**{_msg(translate, 'dv_hover_help_title')}**")
    st.markdown(_msg(translate, "dv_hover_help"))

    display_cols = [
        c
        for c in [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turn",
            "pctChg",
            "tradestatus",
        ]
        if c in df.columns
    ]
    table = df[display_cols].copy()
    table["date"] = table["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.download_button(
        _msg(translate, "dv_export_csv"),
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{symbol}_{start_date}_{end_date}.csv",
        mime="text/csv",
        key=f"{key_prefix}_download",
    )
