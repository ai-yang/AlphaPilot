"""Backtest result storage / query.

Consolidates access to the per-run artifacts (``ret.pkl``,
``qlib_res.csv``, position/indicator pickles) that live under the
workspace root.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.core.path_safety import ensure_child_path
from alphapilot.systems.backtest.artifacts import (
    BacktestArtifacts,
    build_workspace_log_titles,
    list_workspaces,
    load_backtest,
    remove_workspace_label,
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

    def _resolve_workspace_path(self, workspace: str | Path) -> Path:
        candidate = Path(workspace).expanduser()
        if candidate.is_absolute() or len(candidate.parts) > 1:
            return candidate.resolve()
        return (self.workspace_root / candidate.name).resolve()

    def delete_run(self, workspace: str | Path, log_root: Path | str | None = None) -> bool:
        """Delete a backtest workspace directory that contains ``ret.pkl``."""
        ws_path = self._resolve_workspace_path(workspace)
        root = self.workspace_root.expanduser().resolve()
        ensure_child_path(root, ws_path)
        if ws_path == root:
            raise ValueError(f"Refusing to delete workspace root: {root}")
        if not ws_path.is_dir() or not (ws_path / "ret.pkl").exists():
            return False
        shutil.rmtree(ws_path)
        if log_root is not None:
            remove_workspace_label(log_root, ws_path.name)
        return True
