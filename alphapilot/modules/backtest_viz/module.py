"""Backtest visualization module: launch backtest artifact viewer."""

from __future__ import annotations

import subprocess
from importlib.resources import path as rpath
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class BacktestVizModule(BaseModule):
    """Interactive viewer for Qlib backtest workspace artifacts."""

    name = "backtest_viz"

    def setup(self, context: "Context") -> None:
        self.context = context

    def backtest_viz(self, port: int = 19903, host: str = "0.0.0.0") -> None:
        """Launch Streamlit backtest artifact viewer."""
        with rpath("alphapilot.modules.backtest_viz", "app.py") as app_path:
            cmds = [
                "streamlit",
                "run",
                str(app_path),
                f"--server.port={port}",
                f"--server.address={host}",
            ]
            subprocess.run(cmds, check=False)

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {"backtest_viz": self.backtest_viz}
