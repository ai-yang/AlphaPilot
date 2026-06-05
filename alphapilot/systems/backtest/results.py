"""Backtest result storage / query.

Consolidates access to the per-run artifacts (``ret.pkl``,
``qlib_res.csv``, position/indicator pickles) that live under the
workspace root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.systems.backtest.artifacts import (
    BacktestArtifacts,
    build_workspace_log_titles,
    list_workspaces,
    load_backtest,
)


class BacktestResultStore:
    """Locate and load backtest artifacts under a workspace root."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root)

    def list_runs(self) -> list[Path]:
        """Return workspace directories that contain a ``ret.pkl`` (newest first)."""
        return list_workspaces(self.workspace_root)

    def load(self, workspace: str | Path) -> BacktestArtifacts:
        """Load full artifacts for a single workspace."""
        return load_backtest(Path(workspace))

    def load_metrics(self, workspace: str | Path) -> Any:
        """Load just the metrics Series (``qlib_res.csv``) if present."""
        csv_path = Path(workspace) / "qlib_res.csv"
        if not csv_path.exists():
            return None
        return pd.read_csv(csv_path, index_col=0).iloc[:, 0]

    def workspace_log_titles(self, log_root: Path | str) -> dict[str, str]:
        """Map workspace id -> log session folder name for display."""
        return build_workspace_log_titles(log_root, self.workspace_root)
