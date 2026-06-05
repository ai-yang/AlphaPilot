"""Standalone Streamlit app for AlphaPilot Qlib backtest artifacts."""

from __future__ import annotations

import streamlit as st

from alphapilot.modules.backtest_viz.panel import render_backtest_panel


st.set_page_config(
    page_title="AlphaPilot 回测详情",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("📊 AlphaPilot 回测详情")
    render_backtest_panel(use_sidebar=True, show_heading=False, key_prefix="standalone")


if __name__ == "__main__":
    main()
