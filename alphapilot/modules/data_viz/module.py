"""Data visualization module: launch K-line viewer for downloaded CSV data."""

from __future__ import annotations

import subprocess
from importlib.resources import path as rpath
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class DataVizModule(BaseModule):
    """Interactive stock data viewer (local CSV from data downloads)."""

    name = "data_viz"

    def setup(self, context: "Context") -> None:
        self.context = context

    def data_viz(self, port: int = 19902, host: str = "0.0.0.0") -> None:
        """Launch Streamlit K-line viewer for downloaded stock CSV data."""
        with rpath("alphapilot.modules.data_viz", "app.py") as app_path:
            cmds = [
                "streamlit",
                "run",
                str(app_path),
                f"--server.port={port}",
                f"--server.address={host}",
            ]
            subprocess.run(cmds, check=False)

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {"data_viz": self.data_viz}
