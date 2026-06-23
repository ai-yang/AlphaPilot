"""Factor leaderboard viewer for ``single_ic`` / ``multi_sequential`` runs.

Scans the workspace root for ``*_leaderboard.csv`` (written by ``QlibSignalEngine`` and the
``multi_sequential`` pipeline) and renders a sortable table + bar chart. Independent of the
portfolio panel, which only recognises ``ret.pkl`` workspaces.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from alphapilot.systems.backtest.artifacts import (
    DEFAULT_WORKSPACE_ROOT,
    LEADERBOARD_GLOB,
    find_leaderboards,
)


def render_factor_leaderboard(
    *,
    workspace_root: Path | str | None = None,
    key_prefix: str = "lb",
) -> None:
    root = Path(workspace_root) if workspace_root is not None else DEFAULT_WORKSPACE_ROOT
    files = find_leaderboards(root)
    if not files:
        st.info(
            f"在 `{root}` 下未找到因子排行榜（{LEADERBOARD_GLOB}）。"
            "先运行 single_ic 或 multi_sequential 回测。"
        )
        return

    labels = [f"{p.parent.name}/{p.name}" for p in files]
    choice = st.selectbox("排行榜文件", labels, key=f"{key_prefix}_file")
    path = files[labels.index(choice)]

    try:
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取失败: {exc}")
        return
    if df.empty:
        st.info("排行榜为空。")
        return

    numeric_cols = [
        c for c in df.columns if c != "factor_name" and pd.api.types.is_numeric_dtype(df[c])
    ]
    sort_col = (
        st.selectbox("排序指标（按绝对值降序）", numeric_cols, key=f"{key_prefix}_sort")
        if numeric_cols
        else None
    )
    if sort_col:
        df = df.reindex(df[sort_col].abs().sort_values(ascending=False).index).reset_index(drop=True)

    st.dataframe(df, width="stretch", hide_index=True, key=f"{key_prefix}_table")

    if sort_col and "factor_name" in df.columns:
        st.bar_chart(df.set_index("factor_name")[sort_col])
