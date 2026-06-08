"""Log UI session state and message loading."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Callable

import streamlit as st

from alphapilot.core.scenario import Scenario
from alphapilot.log.base import Message
from alphapilot.log.storage import FileStorage
from alphapilot.log.tag_utils import canonical_ui_msg_tag, resolve_scenario_from_log, ui_round_from_tag

QLIB_SELECTED_METRICS = [
    "IC",
    "annualized_return",
    "information_ratio",
    "max_drawdown",
]


# ---- Scenario trait predicates (None-safe) ----
#
# The log UI branches on scenario *kind* via overridable traits on the
# abstract ``Scenario`` rather than importing concrete scenario classes from
# the alpha-mining module, so the infra ``log`` layer stays decoupled from
# feature modules.

def scenario_is_mining(scen: Scenario | None) -> bool:
    return scen is not None and scen.is_mining_scenario


def scenario_has_alpha158_baseline(scen: Scenario | None) -> bool:
    return scen is not None and scen.has_alpha158_baseline


def scenario_uses_qlib_metric_index(scen: Scenario | None) -> bool:
    return scen is not None and scen.uses_qlib_metric_index


class LogSession:
    """Namespaced session state for log UI (portal + standalone)."""

    _PRIVATE = frozenset({"key_prefix", "main_log_path"})

    def __init__(self, key_prefix: str, main_log_path: Path | None) -> None:
        object.__setattr__(self, "key_prefix", key_prefix)
        object.__setattr__(self, "main_log_path", main_log_path)

    def _k(self, name: str) -> str:
        return f"{self.key_prefix}_{name}"

    def __getattr__(self, name: str):
        key = self._k(name)
        if key not in st.session_state:
            raise AttributeError(name)
        return st.session_state[key]

    def __setattr__(self, name: str, value) -> None:
        if name in self._PRIVATE:
            object.__setattr__(self, name, value)
        else:
            st.session_state[self._k(name)] = value

    def ensure_defaults(self) -> None:
        if self._k("_inited") in st.session_state:
            return

        if self._k("log_path") not in st.session_state:
            if self.main_log_path is not None:
                folders = filter_log_folders(self.main_log_path)
                self.log_path = folders[0] if folders else None
            else:
                self.log_path = None

        defaults = {
            "scenario": None,
            "fs": None,
            "msgs": defaultdict(lambda: defaultdict(list)),
            "last_msg": None,
            "current_tags": [],
            "lround": 0,
            "times": defaultdict(lambda: defaultdict(list)),
            "erounds": defaultdict(int),
            "e_decisions": defaultdict(lambda: defaultdict(tuple)),
            "hypotheses": defaultdict(None),
            "h_decisions": defaultdict(bool),
            "metric_series": [],
            "alpha158_metrics": None,
            "excluded_tags": ["llm_messages"],
            "excluded_types": ["str"],
            "current_task": None,
            "api_base": "http://127.0.0.1:6701",
            "user_direction": "",
        }
        for name, val in defaults.items():
            if self._k(name) not in st.session_state:
                setattr(self, name, val)

        st.cache_data.clear()
        self._inited = True


def filter_log_folders(main_log_path: Path) -> list[Path]:
    """Return valid log session folders under *main_log_path*."""

    def _has_session_dir(folder: Path) -> bool:
        for name in ("session_snapshots", "__session__"):
            if (folder / name).is_dir():
                return True
        return False

    folders = [
        folder.relative_to(main_log_path)
        for folder in main_log_path.iterdir()
        if folder.is_dir() and _has_session_dir(folder)
    ]
    folders.sort(key=lambda f: os.path.getmtime(main_log_path / f), reverse=True)
    return folders


def should_display(sess: LogSession, msg: Message) -> bool:
    for tag in sess.excluded_tags:
        if tag in msg.tag.split("."):
            return False
    if type(msg.content).__name__ in sess.excluded_types:
        return False
    return True


def get_msgs_until(sess: LogSession, end_func: Callable[[Message], bool] | None = None) -> None:
    if end_func is None:
        end_func = lambda _: True

    if sess.fs:
        while True:
            try:
                msg = next(sess.fs)
                if should_display(sess, msg):
                    tags = msg.tag.split(".")
                    ui_round = ui_round_from_tag(msg.tag)
                    if ui_round is None:
                        if "r" not in sess.current_tags and "r" in tags:
                            sess.lround += 1
                        ui_round = sess.lround
                    else:
                        sess.lround = max(sess.lround, ui_round)

                    if "evolving code" not in sess.current_tags and "evolving code" in tags:
                        sess.erounds[ui_round] += 1

                    sess.current_tags = tags
                    sess.last_msg = msg

                    if "model runner result" in tags or "factor runner result" in tags or "runner result" in tags:
                        if scenario_has_alpha158_baseline(sess.scenario) and sess.alpha158_metrics is None:
                            sms = msg.content.based_experiments[0].result.loc[QLIB_SELECTED_METRICS]
                            sms.name = "alpha158"
                            sess.alpha158_metrics = sms

                        if (
                            ui_round == 1
                            and len(msg.content.based_experiments) > 0
                            and msg.content.based_experiments[-1].result is not None
                        ):
                            sms = msg.content.based_experiments[-1].result
                            if scenario_uses_qlib_metric_index(sess.scenario):
                                sms = sms.loc[QLIB_SELECTED_METRICS]
                            sms.name = "Baseline"
                            sess.metric_series.append(sms)

                        if msg.content.result is not None:
                            sms = msg.content.result
                            if scenario_uses_qlib_metric_index(sess.scenario):
                                sms = sms.loc[QLIB_SELECTED_METRICS]
                            sms.name = f"Round {ui_round}"
                            sess.metric_series.append(sms)
                    elif "hypothesis generation" in tags:
                        sess.hypotheses[ui_round] = msg.content
                    elif "ef" in tags and "feedback" in tags:
                        sess.h_decisions[ui_round] = msg.content.decision
                    elif "d" in tags:
                        if "evolving code" in tags:
                            msg.content = [i for i in msg.content if i]
                        if "evolving feedback" in tags:
                            total_len = len(msg.content)
                            msg.content = [i for i in msg.content if i]
                            none_num = total_len - len(msg.content)
                            code_msgs = sess.msgs[ui_round].get("d.evolving code", [])
                            if (
                                code_msgs
                                and code_msgs[-1].content is not None
                                and len(msg.content) != len(code_msgs[-1].content)
                            ):
                                st.toast(":red[**Evolving Feedback Length Error!**]", icon="‼️")
                            right_num = sum(1 for wsf in msg.content if wsf.final_decision)
                            wrong_num = len(msg.content) - right_num
                            sess.e_decisions[ui_round][sess.erounds[ui_round]] = (
                                right_num,
                                wrong_num,
                                none_num,
                            )

                    sess.msgs[ui_round][canonical_ui_msg_tag(msg.tag)].append(msg)

                    if "init" in tags:
                        sess.times[ui_round]["init"].append(msg.timestamp)
                    if "r" in tags:
                        sess.times[ui_round]["r"].append(msg.timestamp)
                    if "d" in tags:
                        sess.times[ui_round]["d"].append(msg.timestamp)
                    if "ef" in tags:
                        sess.times[ui_round]["ef"].append(msg.timestamp)

                    if end_func(msg):
                        break
            except StopIteration:
                st.toast(":red[**No More Logs to Show!**]", icon="🛑")
                break


def log_root_path(sess: LogSession) -> Path | None:
    if sess.log_path is None:
        return None
    if sess.main_log_path:
        return sess.main_log_path / sess.log_path
    return Path(sess.log_path)


def refresh(sess: LogSession, same_trace: bool = False, *, load_all_msgs: bool = True) -> None:
    if sess.log_path is None:
        st.toast(":red[**Please Set Log Path!**]", icon="⚠️")
        return

    log_root = log_root_path(sess)
    if log_root is None:
        return

    if not same_trace:
        sess.scenario = resolve_scenario_from_log(log_root)
        if sess.scenario is None:
            st.toast(":red[**No Scenario Info detected**] (check init/scenario or session_snapshots)", icon="❗")
        else:
            st.toast(f":green[**Scenario Info detected**] *{type(sess.scenario).__name__}*", icon="✅")

    sess.msgs = defaultdict(lambda: defaultdict(list))
    sess.lround = 0
    sess.erounds = defaultdict(int)
    sess.e_decisions = defaultdict(lambda: defaultdict(tuple))
    sess.hypotheses = defaultdict(None)
    sess.h_decisions = defaultdict(bool)
    sess.metric_series = []
    sess.last_msg = None
    sess.current_tags = []
    sess.alpha158_metrics = None
    sess.times = defaultdict(lambda: defaultdict(list))

    sess.fs = FileStorage(log_root).iter_msg()
    if load_all_msgs:
        get_msgs_until(sess, lambda m: False)
        sess.fs = None
