"""Reusable mining log UI panel (portal tab + standalone app)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from alphapilot.log.ui.session import LogSession, SIMILAR_SCENARIOS, filter_log_folders, get_msgs_until, refresh
from alphapilot.log.ui.views import (
    evolving_window,
    feedback_window,
    inject_log_ui_css,
    research_window,
    summary_window,
)

TranslateFn = Callable[..., str]

_DEFAULT_ZH: dict[str, str] = {
    "mine_log_caption": "查看因子挖掘运行日志：假说、因子代码、回测反馈与 Qlib 报告图。",
    "mine_log_filters": "日志筛选与控制",
    "mine_log_sidebar_header": "日志控制",
    "mine_log_missing_dir": "Log 目录 `{path}` 不存在。",
    "tab_mine_log": "挖掘日志",
}


def _msg(translate: TranslateFn | None, key: str, **kwargs: Any) -> str:
    if translate is not None:
        try:
            return translate(key, **kwargs)
        except KeyError:
            pass
    text = _DEFAULT_ZH.get(key, key)
    return text.format(**kwargs) if kwargs else text


TOC = """
## [Summary📊](#_summary)
- [**Metrics📈**](#_metrics)
## [AlphaPilot Loops♾️](#_loops)
- [**Idea Agent💡**](#_idea)
- [**Factor Agent⚙️**](#_factor)
- [**Eval Agent📝**](#_eval)
"""


def _render_controls(
    sess: LogSession,
    *,
    main_log_path: Path,
    key_prefix: str,
    debug: bool,
    use_sidebar: bool,
) -> bool:
    """Render control panel. Returns effective debug flag."""

    def _refresh(same_trace: bool = False, load_all_msgs: bool = True) -> None:
        refresh(sess, same_trace=same_trace, load_all_msgs=load_all_msgs)

    container = st.sidebar if use_sidebar else st.expander(
        _msg(None, "mine_log_filters"),
        expanded=True,
    )

    with container:
        if use_sidebar:
            st.markdown("# **AlphaPilot**✨")
            st.subheader(":blue[Table of Content]", divider="blue")
            st.markdown(TOC)
            st.subheader(":blue[Control Panel]", divider="blue")

        with st.container(border=True):
            lc1, lc2 = st.columns([1, 2], vertical_alignment="center")
            with lc1:
                st.markdown(":blue[**Log Path**]")
            with lc2:
                manually = st.toggle("Manual Input", key=f"{key_prefix}_manual_log")
            if manually:
                manual_val = st.text_input(
                    "log path",
                    value=str(sess.log_path) if sess.log_path is not None else "",
                    key=f"{key_prefix}_log_path_input",
                    on_change=_refresh,
                    label_visibility="collapsed",
                )
                sess.log_path = Path(manual_val) if manual_val else None
            else:
                folders = filter_log_folders(main_log_path)
                if folders:
                    labels = [str(f) for f in folders]
                    current = str(sess.log_path) if sess.log_path is not None else labels[0]
                    if current not in labels:
                        current = labels[0]
                    idx = labels.index(current)
                    picked = st.selectbox(
                        f"**Select from `{main_log_path}`**",
                        labels,
                        index=idx,
                        key=f"{key_prefix}_log_select",
                        on_change=_refresh,
                    )
                    sess.log_path = Path(picked)
                else:
                    st.warning("No valid log sessions found.")

        c1, c2 = st.columns([1, 1], vertical_alignment="center")
        with c1:
            if st.button(":green[**All Loops**]", use_container_width=True, key=f"{key_prefix}_all_loops"):
                _refresh(same_trace=True)
            if st.button("**Reset**", use_container_width=True, key=f"{key_prefix}_reset"):
                _refresh(same_trace=True)
        with c2:
            if st.button(":green[Next Loop]", use_container_width=True, key=f"{key_prefix}_next_loop"):
                if sess.fs is None:
                    _refresh(same_trace=True, load_all_msgs=False)
                get_msgs_until(sess, lambda m: "ef.feedback" in m.tag)
            if st.button("Next Step", use_container_width=True, key=f"{key_prefix}_next_step"):
                if sess.fs is None:
                    _refresh(same_trace=True, load_all_msgs=False)
                get_msgs_until(sess, lambda m: "d.evolving feedback" in m.tag)

        with st.popover(":orange[**Config⚙️**]", use_container_width=True):
            # Widget key == sess._k("excluded_*"); do not assign after widget (Streamlit conflict).
            st.multiselect(
                "excluded log tags",
                ["llm_messages"],
                key=f"{key_prefix}_excluded_tags",
            )
            st.multiselect(
                "excluded log types",
                ["str", "dict", "list"],
                key=f"{key_prefix}_excluded_types",
            )

        effective_debug = debug
        if debug:
            effective_debug = st.toggle("debug", value=False, key=f"{key_prefix}_debug_toggle")
            if effective_debug and st.button(
                "Single Step Run",
                use_container_width=True,
                key=f"{key_prefix}_single_step",
            ):
                get_msgs_until(sess)

        st.subheader(":blue[Entrance]", divider="blue")
        user_hypothesis = st.text_input(
            "🔍 **Enter an hypothesis you want to verify**",
            value=sess.user_direction,
            placeholder="...",
            key=f"{key_prefix}_hypothesis",
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            start_clicked = st.button(
                "🚀 Start Mining" if not sess.current_task else "⏳ Mining...",
                disabled=sess.current_task is not None,
                use_container_width=True,
                key=f"{key_prefix}_start",
            )
        with col2:
            stop_clicked = st.button(
                "⏹ Stop Mining",
                disabled=sess.current_task is None,
                use_container_width=True,
                key=f"{key_prefix}_stop",
            )

        if start_clicked and user_hypothesis:
            response = requests.post(
                f"{sess.api_base}/api/tasks",
                json={"direction": user_hypothesis},
                timeout=30,
            )
            if response.status_code == 200:
                sess.current_task = response.json()["task_id"]
                sess.user_direction = user_hypothesis
            _refresh(same_trace=True)
            st.rerun()

        if stop_clicked and sess.current_task:
            response = requests.post(
                f"{sess.api_base}/api/tasks/{sess.current_task}/stop",
                timeout=30,
            )
            if response.status_code == 200:
                st.success("Stop signal sent")
                sess.current_task = None
            st.rerun()

        if sess.current_task and st.button(
            "🔄 Refresh Now",
            use_container_width=True,
            key=f"{key_prefix}_refresh_now",
        ):
            _refresh(same_trace=True)
            st.rerun()

    return effective_debug


def _render_debug(sess: LogSession, debug: bool) -> None:
    if not debug:
        return
    with st.expander(":red[**Debug Info**]", expanded=True):
        dcol1, dcol2 = st.columns([1, 3])
        with dcol1:
            st.markdown(
                f"**log path**: {sess.log_path}\n\n"
                f"**excluded tags**: {sess.excluded_tags}\n\n"
                f"**excluded types**: {sess.excluded_types}\n\n"
                f":blue[**message id**]: {sum(sum(len(tmsgs) for tmsgs in rmsgs.values()) for rmsgs in sess.msgs.values())}\n\n"
                f":blue[**round**]: {sess.lround}\n\n"
                f":blue[**evolving round**]: {sess.erounds[sess.lround]}\n\n"
            )
        with dcol2:
            if sess.last_msg:
                st.write(sess.last_msg)
                if isinstance(sess.last_msg.content, list):
                    st.write(sess.last_msg.content[0])
                elif not isinstance(sess.last_msg.content, str):
                    st.write(sess.last_msg.content.__dict__)


def _render_main(sess: LogSession, key_prefix: str) -> None:
    if sess.scenario is None:
        return

    summary_window(sess)

    if not isinstance(sess.scenario, SIMILAR_SCENARIOS):
        st.error("Unknown Scenario!")
        return

    st.header("AlphaPilot Loops♾️", divider="rainbow", anchor="_loops")
    if len(sess.msgs) > 1:
        r_options = list(sess.msgs.keys())
        if 0 in r_options:
            r_options.remove(0)
        round_no = st.radio(
            "# **Loop**",
            horizontal=True,
            options=r_options,
            index=sess.lround - 1 if sess.lround in r_options else 0,
            key=f"{key_prefix}_round_radio",
        )
    else:
        round_no = 1

    r_c = st.container()
    d_c = st.container()
    f_c = st.container()

    with r_c:
        research_window(sess, round_no)
    with f_c:
        feedback_window(sess, round_no)
    with d_c.container(border=True):
        evolving_window(sess, round_no, key_prefix=key_prefix)


def render_log_ui_panel(
    *,
    log_dir: Path | str,
    translate: TranslateFn | None = None,
    use_sidebar: bool = False,
    show_heading: bool = True,
    key_prefix: str = "log_ui",
    api_base: str = "http://127.0.0.1:6701",
    debug: bool = False,
) -> None:
    """Render factor-mining log viewer."""
    inject_log_ui_css()

    main_log_path = Path(log_dir).resolve()
    if not main_log_path.is_dir():
        st.error(_msg(translate, "mine_log_missing_dir", path=main_log_path))
        return

    if show_heading:
        st.subheader(f"🎓 {_msg(translate, 'tab_mine_log')}")
    st.caption(_msg(translate, "mine_log_caption"))

    sess = LogSession(key_prefix, main_log_path)
    sess.ensure_defaults()
    sess.api_base = api_base

    if use_sidebar:
        st.sidebar.header(_msg(translate, "mine_log_sidebar_header"))

    effective_debug = _render_controls(
        sess,
        main_log_path=main_log_path,
        key_prefix=key_prefix,
        debug=debug,
        use_sidebar=use_sidebar,
    )
    _render_debug(sess, effective_debug)

    if sess.log_path and sess.fs is None and sess.scenario is None:
        refresh(sess)

    _render_main(sess, key_prefix)

    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("#### Disclaimer")
    st.markdown(
        "*This content is AI-generated and may not be fully accurate or up-to-date; "
        "please verify with a professional for critical matters.*",
        unsafe_allow_html=True,
    )
