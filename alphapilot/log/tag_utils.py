"""Normalize log message tags for the Streamlit UI (legacy keys vs factor-mining layout)."""

from __future__ import annotations

import pickle
import re
from pathlib import Path

_ROUND_TAG_RE = re.compile(r"(?:^|\.)round_(\d+)(?:\.|$)")

# Longest suffix first so ``ef.feedback`` wins over ``ef``.
_LEGACY_UI_TAG_SUFFIXES: tuple[str, ...] = (
    "r.extract_factors_and_implement.load_pdf_screenshot",
    "r.hypothesis generation",
    "r.experiment generation",
    "ef.Quantitative Backtesting Chart",
    "ef.runner result",
    "ef.feedback",
    "d.evolving feedback",
    "d.evolving code",
    "d.coder result",
    "init.scenario",
    "init.hypothesis generator",
    "init.experiment generation",
    "init.coder",
    "init.runner",
    "init.summarizer",
)


def canonical_ui_msg_tag(tag: str) -> str:
    """
    Map tags like ``round_01.03_factor_values.d.evolving code.1792268``
    to legacy UI bucket keys such as ``d.evolving code``.
    """
    if tag in _LEGACY_UI_TAG_SUFFIXES:
        return tag
    for suffix in _LEGACY_UI_TAG_SUFFIXES:
        if tag.endswith(f".{suffix}") or f".{suffix}." in f".{tag}.":
            return suffix
    return tag


def ui_round_from_tag(tag: str) -> int | None:
    """Mining log tag prefix ``round_01`` -> UI loop index ``1``."""
    m = _ROUND_TAG_RE.search(f".{tag}.")
    return int(m.group(1)) if m else None


def resolve_scenario_from_log(log_root: Path):
    """
    Find a Scenario for the UI: ``init.scenario`` pickle, else workflow snapshot.
    """
    from alphapilot.core.scenario import Scenario
    from alphapilot.log.storage import FileStorage

    root = Path(log_root)
    for file in sorted(root.glob("**/init/scenario/**/*.pkl")):
        try:
            with file.open("rb") as f:
                obj = pickle.load(f)
            if isinstance(obj, Scenario):
                return obj
        except Exception:
            continue

    for file in root.glob("**/*.pkl"):
        if not FileStorage._is_ui_object_pickle(file, root):
            continue
        if "scenario" not in file.as_posix().lower():
            continue
        try:
            with file.open("rb") as f:
                obj = pickle.load(f)
            if isinstance(obj, Scenario):
                return obj
        except Exception:
            continue

    for snap in sorted(root.glob("session_snapshots/**/workflow.snapshot.pkl")):
        try:
            with snap.open("rb") as f:
                loop = pickle.load(f)
            trace = getattr(loop, "trace", None)
            scen = getattr(trace, "scen", None) if trace is not None else None
            if isinstance(scen, Scenario):
                return scen
        except Exception:
            continue
    return None
