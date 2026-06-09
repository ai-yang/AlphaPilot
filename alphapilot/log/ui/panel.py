"""Reusable mining log UI panel (portal tab + standalone app)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

DeleteSessionFn = Callable[[str], bool]

import requests
import streamlit as st

from alphapilot.log.ui.i18n import TranslateFn, msg
from alphapilot.log.ui.session import LogSession, scenario_is_mining, filter_log_folders, get_msgs_until, refresh
from alphapilot.log.ui.views import (
    evolving_window,
    feedback_window,
    inject_log_ui_css,
    research_window,
    summary_window,
)


def _toc(translate: TranslateFn | None) -> str:
    return f"""
## [{msg(translate, "ml_toc_summary")}📊](#_summary)
- [**{msg(translate, "ml_toc_metrics")}📈**](#_metrics)
## [{msg(translate, "ml_toc_loops")}♾️](#_loops)
- [**{msg(translate, "ml_toc_idea")}💡**](#_idea)
- [**{msg(translate, "ml_toc_factor")}⚙️**](#_factor)
- [**{msg(translate, "ml_toc_eval")}📝**](#_eval)
"""


def _render_controls(
    sess: LogSession,
    *,
    main_log_path: Path,
    key_prefix: str,
    debug: bool,
    use_sidebar: bool,
    translate: TranslateFn | None = None,
    delete_session_fn: DeleteSessionFn | None = None,
) -> bool:
    """Render control panel. Returns effective debug flag."""

    def _refresh(same_trace: bool = False, load_all_msgs: bool = True) -> None:
        refresh(sess, same_trace=same_trace, load_all_msgs=load_all_msgs)

    container = st.sidebar if use_sidebar else st.expander(
        msg(translate, "mine_log_filters"),
        expanded=True,
    )

    with container:
        if use_sidebar:
            st.markdown(f"# **{msg(translate, 'ml_brand')}**✨")
            st.subheader(f":blue[{msg(translate, 'ml_table_of_content')}]", divider="blue")
            st.markdown(_toc(translate))
            st.subheader(f":blue[{msg(translate, 'ml_control_panel')}]", divider="blue")

        with st.container(border=True):
            lc1, lc2 = st.columns([1, 2], vertical_alignment="center")
            with lc1:
                st.markdown(f":blue[**{msg(translate, 'ml_log_path')}**]")
            with lc2:
                manually = st.toggle(msg(translate, "ml_manual_input"), key=f"{key_prefix}_manual_log")
            if manually:
                manual_val = st.text_input(
                    msg(translate, "ml_log_path_input"),
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
                        f"**{msg(translate, 'ml_select_from', path=main_log_path)}**",
                        labels,
                        index=idx,
                        key=f"{key_prefix}_log_select",
                        on_change=_refresh,
                    )
                    sess.log_path = Path(picked)
                else:
                    st.warning(msg(translate, "ml_no_sessions"))

        if delete_session_fn is not None and sess.log_path is not None:
            session_name = Path(sess.log_path).name
            with st.container(border=True):
                st.markdown(f"**{msg(translate, 'delete_heading')}**")
                st.caption(session_name)
                delete_log_confirm = st.checkbox(
                    msg(translate, "delete_confirm"),
                    key=f"{key_prefix}_delete_log_confirm",
                )
                if st.button(
                    msg(translate, "delete_mine_log_btn"),
                    key=f"{key_prefix}_delete_log_btn",
                ):
                    if not delete_log_confirm:
                        st.warning(msg(translate, "delete_confirm"))
                    else:
                        try:
                            if delete_session_fn(session_name):
                                st.success(msg(translate, "mine_log_deleted", name=session_name))
                                sess.log_path = None
                                st.rerun()
                            else:
                                st.error(msg(translate, "mine_log_delete_failed", name=session_name))
                        except Exception as exc:  # noqa: BLE001
                            st.error(msg(translate, "mine_log_delete_error", error=exc))

        c1, c2 = st.columns([1, 1], vertical_alignment="center")
        with c1:
            if st.button(
                f":green[**{msg(translate, 'ml_all_loops')}**]",
                use_container_width=True,
                key=f"{key_prefix}_all_loops",
            ):
                _refresh(same_trace=True)
            if st.button(
                f"**{msg(translate, 'ml_reset')}**",
                use_container_width=True,
                key=f"{key_prefix}_reset",
            ):
                _refresh(same_trace=True)
        with c2:
            if st.button(
                f":green[{msg(translate, 'ml_next_loop')}]",
                use_container_width=True,
                key=f"{key_prefix}_next_loop",
            ):
                if sess.fs is None:
                    _refresh(same_trace=True, load_all_msgs=False)
                get_msgs_until(sess, lambda m: "ef.feedback" in m.tag)
            if st.button(
                msg(translate, "ml_next_step"),
                use_container_width=True,
                key=f"{key_prefix}_next_step",
            ):
                if sess.fs is None:
                    _refresh(same_trace=True, load_all_msgs=False)
                get_msgs_until(sess, lambda m: "d.evolving feedback" in m.tag)

        with st.popover(f":orange[**{msg(translate, 'ml_config')}⚙️**]", use_container_width=True):
            st.multiselect(
                msg(translate, "ml_excluded_tags"),
                ["llm_messages"],
                key=f"{key_prefix}_excluded_tags",
            )
            st.multiselect(
                msg(translate, "ml_excluded_types"),
                ["str", "dict", "list"],
                key=f"{key_prefix}_excluded_types",
            )

        effective_debug = debug
        if debug:
            effective_debug = st.toggle(msg(translate, "ml_debug"), value=False, key=f"{key_prefix}_debug_toggle")
            if effective_debug and st.button(
                msg(translate, "ml_single_step"),
                use_container_width=True,
                key=f"{key_prefix}_single_step",
            ):
                get_msgs_until(sess)

        st.subheader(f":blue[{msg(translate, 'ml_entrance')}]", divider="blue")
        user_hypothesis = st.text_input(
            f"🔍 **{msg(translate, 'ml_hypothesis_input')}**",
            value=sess.user_direction,
            placeholder="...",
            key=f"{key_prefix}_hypothesis",
        )

        col1, col2 = st.columns([1, 1])
        with col1:
            start_label = (
                msg(translate, "ml_mining_in_progress")
                if sess.current_task
                else msg(translate, "ml_start_mining")
            )
            start_clicked = st.button(
                f"🚀 {start_label}" if not sess.current_task else f"⏳ {start_label}",
                disabled=sess.current_task is not None,
                use_container_width=True,
                key=f"{key_prefix}_start",
            )
        with col2:
            stop_clicked = st.button(
                f"⏹ {msg(translate, 'ml_stop_mining')}",
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
                st.success(msg(translate, "ml_stop_sent"))
                sess.current_task = None
            st.rerun()

        if sess.current_task and st.button(
            f"🔄 {msg(translate, 'ml_refresh_now')}",
            use_container_width=True,
            key=f"{key_prefix}_refresh_now",
        ):
            _refresh(same_trace=True)
            st.rerun()

    return effective_debug


def _render_debug(sess: LogSession, debug: bool, translate: TranslateFn | None) -> None:
    if not debug:
        return
    with st.expander(f":red[**{msg(translate, 'ml_debug_info')}**]", expanded=True):
        dcol1, dcol2 = st.columns([1, 3])
        with dcol1:
            st.markdown(
                f"**{msg(translate, 'ml_dbg_log_path')}**: {sess.log_path}\n\n"
                f"**{msg(translate, 'ml_dbg_excluded_tags')}**: {sess.excluded_tags}\n\n"
                f"**{msg(translate, 'ml_dbg_excluded_types')}**: {sess.excluded_types}\n\n"
                f":blue[**{msg(translate, 'ml_dbg_message_id')}**]: "
                f"{sum(sum(len(tmsgs) for tmsgs in rmsgs.values()) for rmsgs in sess.msgs.values())}\n\n"
                f":blue[**{msg(translate, 'ml_dbg_round')}**]: {sess.lround}\n\n"
                f":blue[**{msg(translate, 'ml_dbg_evolving_round')}**]: {sess.erounds[sess.lround]}\n\n"
            )
        with dcol2:
            if sess.last_msg:
                st.write(sess.last_msg)
                if isinstance(sess.last_msg.content, list):
                    st.write(sess.last_msg.content[0])
                elif not isinstance(sess.last_msg.content, str):
                    st.write(sess.last_msg.content.__dict__)


def _render_main(sess: LogSession, key_prefix: str, translate: TranslateFn | None) -> None:
    if sess.scenario is None:
        return

    summary_window(sess, translate)

    if not scenario_is_mining(sess.scenario):
        st.error(msg(translate, "ml_unknown_scenario"))
        return

    st.header(f"{msg(translate, 'ml_loops_header')}♾️", divider="rainbow", anchor="_loops")
    if len(sess.msgs) > 1:
        r_options = list(sess.msgs.keys())
        if 0 in r_options:
            r_options.remove(0)
        round_no = st.radio(
            f"# **{msg(translate, 'ml_loop_radio')}**",
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
        research_window(sess, round_no, translate)
    with f_c:
        feedback_window(sess, round_no, translate)
    with d_c.container(border=True):
        evolving_window(sess, round_no, key_prefix=key_prefix, translate=translate)


def render_log_ui_panel(
    *,
    log_dir: Path | str,
    translate: TranslateFn | None = None,
    use_sidebar: bool = False,
    show_heading: bool = True,
    key_prefix: str = "log_ui",
    api_base: str = "http://127.0.0.1:6701",
    debug: bool = False,
    delete_session_fn: DeleteSessionFn | None = None,
) -> None:
    """Render factor-mining log viewer."""
    inject_log_ui_css()

    main_log_path = Path(log_dir).resolve()
    if not main_log_path.is_dir():
        st.error(msg(translate, "mine_log_missing_dir", path=main_log_path))
        return

    if show_heading:
        st.subheader(f"🎓 {msg(translate, 'tab_mine_log')}")
    st.caption(msg(translate, "mine_log_caption"))

    sess = LogSession(key_prefix, main_log_path)
    sess.ensure_defaults()
    sess.api_base = api_base

    if use_sidebar:
        st.sidebar.header(msg(translate, "mine_log_sidebar_header"))

    effective_debug = _render_controls(
        sess,
        main_log_path=main_log_path,
        key_prefix=key_prefix,
        debug=debug,
        use_sidebar=use_sidebar,
        translate=translate,
        delete_session_fn=delete_session_fn,
    )
    _render_debug(sess, effective_debug, translate)

    if sess.log_path and sess.fs is None and sess.scenario is None:
        refresh(sess)

    _render_main(sess, key_prefix, translate)

    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown(f"#### {msg(translate, 'ml_disclaimer_title')}")
    st.markdown(
        f"*{msg(translate, 'ml_disclaimer_body')}*",
        unsafe_allow_html=True,
    )
