"""Portal module: unified web UI for kernel systems and plugins."""

from __future__ import annotations

import subprocess
from importlib.resources import path as rpath
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class PortalModule(BaseModule):
    """Launch and host the AlphaPilot unified web portal."""

    name = "portal"

    def setup(self, context: "Context") -> None:
        self.context = context

    def portal(self, port: int = 19901, host: str = "0.0.0.0", reload: bool = False) -> None:
        """Launch the React/FastAPI unified web portal."""
        import uvicorn

        from alphapilot.modules.portal.api import create_app

        if reload:
            uvicorn.run("alphapilot.modules.portal.api:create_app", host=host, port=port, reload=True, factory=True)
            return
        static_dir = Path(__file__).parent / "web" / "dist"
        app = create_app(static_dir=static_dir)
        uvicorn.run(app, host=host, port=port)

    def portal_legacy(self, port: int = 19901, host: str = "0.0.0.0") -> None:
        """Launch the legacy Streamlit portal."""
        with rpath("alphapilot.modules.portal", "app.py") as app_path:
            cmds = [
                "streamlit",
                "run",
                str(app_path),
                f"--server.port={port}",
                f"--server.address={host}",
            ]
            subprocess.run(cmds, check=False)

    def scheduler(self, interval: int = 30) -> None:
        """Run the daily task scheduler daemon (auto-fires saved data/mine/backtest schedules)."""
        from alphapilot.modules.portal.schedules import run_scheduler_loop

        run_scheduler_loop(interval=interval)

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "portal": self.portal,
            "portal_legacy": self.portal_legacy,
            "scheduler": self.scheduler,
        }
