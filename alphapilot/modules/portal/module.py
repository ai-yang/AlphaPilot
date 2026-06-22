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

    def portal(self, port: int | None = None, host: str | None = None, reload: bool = False) -> None:
        """Launch the React/FastAPI unified web portal."""
        import uvicorn

        from alphapilot.modules.portal.api import create_app
        from alphapilot.modules.portal.env_config import apply_portal_env
        from alphapilot.modules.portal.runtime import (
            clear_runtime,
            current_restart_argv,
            install_restart_signal_handler,
            write_runtime,
        )
        from alphapilot.modules.portal.settings import load_portal_settings

        settings = load_portal_settings()
        host = host or settings["host"]
        port = int(port if port is not None else settings["port"])
        apply_portal_env()

        if reload:
            uvicorn.run("alphapilot.modules.portal.api:create_app", host=host, port=port, reload=True, factory=True)
            return
        static_dir = Path(__file__).parent / "web" / "dist"
        app = create_app(static_dir=static_dir, portal_host=host, portal_port=port)
        install_restart_signal_handler()
        write_runtime(host=host, port=port, argv=current_restart_argv())
        try:
            uvicorn.run(app, host=host, port=port)
        finally:
            clear_runtime()

    def portal_legacy(self, port: int | None = None, host: str | None = None) -> None:
        """Launch the legacy Streamlit portal."""
        from alphapilot.modules.portal.settings import load_portal_settings

        settings = load_portal_settings()
        host = host or settings["host"]
        port = int(port if port is not None else settings["port"])
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

    def portal_restart(self) -> dict[str, Any]:
        """Restart a running `alphapilot portal` process."""
        from alphapilot.modules.portal.runtime import request_runtime_restart

        return request_runtime_restart()

    def notify_commands(self, channel: str = "telegram", poll_interval: float | None = None) -> None:
        """Run the inbound notification command receiver."""
        from alphapilot.systems.notify.inbound import run_daemon

        run_daemon(channel=channel, poll_interval=poll_interval)

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "portal": self.portal,
            "portal_legacy": self.portal_legacy,
            "portal_restart": self.portal_restart,
            "notify_commands": self.notify_commands,
            "scheduler": self.scheduler,
        }
