"""Platform module commands (web/UI/data utilities)."""

from __future__ import annotations

import subprocess
from importlib.resources import path as rpath
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class PlatformModule(BaseModule):
    """Operational module that contributes platform-level CLI commands."""

    name = "platform"

    def setup(self, context: "Context") -> None:
        self.context = context

    def prepare_data(
        self,
        action: str = "pipeline",
        start_date: str = "2005-01-01",
        end_date: str | None = None,
        stock_csv: str | None = None,
        adjust_mode: str = "backward",
        market: str | None = None,
        qlib_dir: str | None = None,
        output_dir: str | None = None,
        **options: Any,
    ) -> Any:
        """Run prepare-data actions through the data system entrypoint."""
        from alphapilot.systems.data.types import DataActionCommand

        data = self.context.data()
        command = DataActionCommand(
            action=action,
            start_date=start_date,
            end_date=end_date,
            stock_csv=stock_csv,
            adjust_mode=adjust_mode,
            market=market,
            qlib_dir=qlib_dir,
            output_dir=output_dir,
            options=dict(options),
        )
        return data.dispatch_action(command)

    def ui(self, port: int = 19899, log_dir: str = "./log", debug: bool = False) -> None:
        """Launch the existing Streamlit log UI."""
        with rpath("alphapilot.log.ui", "app.py") as app_path:
            cmds = ["streamlit", "run", str(app_path), f"--server.port={port}"]
            if log_dir or debug:
                cmds.append("--")
            if log_dir:
                cmds.append(f"--log_dir={log_dir}")
            if debug:
                cmds.append("--debug")
            subprocess.run(cmds, check=False)

    def backtest_ui(
        self,
        port: int = 19900,
        workspace_root: str | None = None,
        log_dir: str = "./log",
    ) -> None:
        """Launch backtest artifacts viewer UI."""
        with rpath("alphapilot.app.backtest_viewer", "app.py") as app_path:
            cmds = ["streamlit", "run", str(app_path), f"--server.port={port}"]
            import os

            if workspace_root:
                os.environ["ALPHAPILOT_BACKTEST_ROOT"] = workspace_root
            if log_dir:
                os.environ["ALPHAPILOT_LOG_DIR"] = log_dir
            subprocess.run(cmds, check=False)

    def portal(self, port: int = 19901, host: str = "0.0.0.0") -> None:
        """Launch unified web portal (systems + modules)."""
        with rpath("alphapilot.app.portal", "app.py") as app_path:
            cmds = [
                "streamlit",
                "run",
                str(app_path),
                f"--server.port={port}",
                f"--server.address={host}",
            ]
            subprocess.run(cmds, check=False)

    def modules(self) -> dict[str, Any]:
        """List loaded modules with their command names."""
        info: dict[str, Any] = {}
        for module_name, module in self.context.engine.modules.items():
            info[module_name] = sorted(module.commands().keys())
        return info

    def commands(self) -> dict[str, Callable[..., Any] | Any]:
        return {
            "prepare_data": self.prepare_data,
            "ui": self.ui,
            "backtest_ui": self.backtest_ui,
            "portal": self.portal,
            "modules": self.modules,
        }
