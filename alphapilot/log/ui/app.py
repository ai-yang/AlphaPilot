"""Standalone Streamlit app for AlphaPilot mining log visualization."""

from __future__ import annotations

import argparse
from pathlib import Path

import streamlit as st

from alphapilot.log.ui.panel import render_log_ui_panel


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AlphaPilot Streamlit App")
    parser.add_argument("--log_dir", required=True, type=str, help="Path to the log directory")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    return parser.parse_args()


st.set_page_config(
    layout="wide",
    page_title="AlphaPilot",
    page_icon="🎓",
    initial_sidebar_state="expanded",
)


def main() -> None:
    args = _parse_args()
    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        st.error(f"Log dir `{log_dir}` does not exist!")
        st.stop()

    render_log_ui_panel(
        log_dir=log_dir,
        use_sidebar=True,
        show_heading=False,
        key_prefix="standalone",
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
