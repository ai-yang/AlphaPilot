"""Backtest result storage / query.

Consolidates access to the per-run artifacts (``ret.pkl``,
``qlib_res.csv``, position/indicator pickles) that live under the
workspace root. It delegates the heavy parsing to the existing
backtest viewer loader so behavior matches the UI exactly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class BacktestResultStore:
    """Locate and load backtest artifacts under a workspace root."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root)

    def list_runs(self) -> list[Path]:
        """Return workspace directories that contain a ``ret.pkl``."""
        if not self.workspace_root.exists():
            return []
        return sorted(p.parent for p in self.workspace_root.glob("*/ret.pkl"))

    def load(self, workspace: str | Path) -> Any:
        """Load full artifacts for a single workspace via the viewer loader."""
        from alphapilot.app.backtest_viewer.loader import load_backtest

        return load_backtest(Path(workspace))

    def load_metrics(self, workspace: str | Path) -> Any:
        """Load just the metrics Series (``qlib_res.csv``) if present."""
        import pandas as pd

        csv_path = Path(workspace) / "qlib_res.csv"
        if not csv_path.exists():
            return None
        return pd.read_csv(csv_path, index_col=0).iloc[:, 0]
