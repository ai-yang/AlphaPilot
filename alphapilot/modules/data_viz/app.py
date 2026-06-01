"""Standalone Streamlit app for stock data visualization."""

from __future__ import annotations

import streamlit as st

from alphapilot.modules.data_viz.panel import render_data_viz_panel


st.set_page_config(
    page_title="AlphaPilot 股票数据可视化",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("📈 股票数据可视化")
    render_data_viz_panel(use_sidebar=True, show_heading=False, key_prefix="standalone")


if __name__ == "__main__":
    main()
