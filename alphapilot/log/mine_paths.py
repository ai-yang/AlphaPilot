"""Readable path helpers for factor-mining logs and session snapshots."""

from __future__ import annotations

from pathlib import Path

# Step folder names under each mining round (log + session snapshots).
FACTOR_MINING_STEP_DIRS: dict[str, str] = {
    "factor_propose": "01_hypothesis",
    "factor_construct": "02_factor_expression",
    "factor_calculate": "03_factor_values",
    "factor_backtest": "04_backtest",
    "feedback": "05_feedback",
}

ROUNDS_ROOT = "rounds"
SESSION_SNAPSHOTS_ROOT = "session_snapshots"
SCORING_MODEL_SUBDIR = "scoring_model"
QLIB_TEMPLATE_SUBDIR = "qlib_template"


def step_dir_name(step_name: str) -> str:
    return FACTOR_MINING_STEP_DIRS.get(step_name, step_name)


def session_snapshot_path(log_root: Path, loop_idx: int, step_idx: int, step_name: str) -> Path:
    """``session_snapshots/round_01/04_backtest/workflow.snapshot.pkl``"""
    round_dir = f"round_{loop_idx + 1:02d}"
    step_dir = f"step_{step_idx + 1:02d}_{step_dir_name(step_name)}"
    return log_root / SESSION_SNAPSHOTS_ROOT / round_dir / step_dir / "workflow.snapshot.pkl"


def round_root(log_root: Path, round_no: int) -> Path:
    return log_root / ROUNDS_ROOT / f"round_{round_no:02d}"


def round_backtest_dir(log_root: Path, round_no: int) -> Path:
    return round_root(log_root, round_no) / step_dir_name("factor_backtest")


def scoring_model_log_dir(log_root: Path, round_no: int) -> Path:
    return round_backtest_dir(log_root, round_no) / SCORING_MODEL_SUBDIR


def qlib_template_log_dir(log_root: Path, round_no: int) -> Path:
    """``rounds/round_01/04_backtest/qlib_template/``"""
    return round_backtest_dir(log_root, round_no) / QLIB_TEMPLATE_SUBDIR


def mining_round_tag(round_no: int, step_name: str) -> str:
    return f"round_{round_no:02d}.{step_dir_name(step_name)}"
