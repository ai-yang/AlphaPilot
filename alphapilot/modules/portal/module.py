"""Portal module: unified web UI for kernel systems and plugins."""

from __future__ import annotations

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
        self._autostart_scheduler()
        try:
            uvicorn.run(app, host=host, port=port)
        finally:
            clear_runtime()

    @staticmethod
    def _autostart_scheduler() -> None:
        """Start the scheduler daemon on portal launch so saved schedules fire.

        Without this the daemon only ran when a user manually pressed *Start*, so
        schedules silently never triggered after a restart. Best-effort and only
        when at least one schedule is enabled; ``start_daemon`` itself no-ops if a
        healthy daemon is already running.
        """
        try:
            from alphapilot.modules.portal.schedules import list_schedules, start_daemon

            if any(s.get("enabled", True) for s in list_schedules()):
                status = start_daemon()
                state = "running" if status.get("running") else "not running"
                print(f"[portal] scheduler daemon auto-start: {state} (pid={status.get('pid')})")
        except Exception as exc:  # noqa: BLE001 - never let the daemon block the portal
            print(f"[portal] scheduler daemon auto-start skipped: {type(exc).__name__}: {exc}")

    def scheduler(self, interval: int = 30) -> None:
        """Run the daily task scheduler daemon (auto-fires saved data/mine/backtest schedules)."""
        from alphapilot.modules.portal.schedules import run_scheduler_loop
        from alphapilot.modules.portal.settings import apply_timezone

        apply_timezone()  # daily firing depends on local time
        run_scheduler_loop(interval=interval)

    def timezone(self, tz: str | None = None) -> dict[str, Any]:
        """Show or set the AlphaPilot timezone (default Asia/Shanghai).

        Examples:
          ``alphapilot timezone``                 show the current timezone
          ``alphapilot timezone Asia/Shanghai``   set the timezone
        Affects scheduler firing and recorded/displayed timestamps. Accepts any
        IANA name (e.g. ``UTC``, ``America/New_York``).
        """
        from alphapilot.modules.portal.settings import apply_timezone, resolve_timezone, set_timezone

        if tz is None or str(tz).strip() == "":
            return {"timezone": resolve_timezone(), "applied": apply_timezone()}
        path = set_timezone(tz)
        return {"timezone": resolve_timezone(), "applied": apply_timezone(), "saved_to": str(path)}

    def portal_restart(self) -> dict[str, Any]:
        """Restart a running `alphapilot portal` process."""
        from alphapilot.modules.portal.runtime import request_runtime_restart

        return request_runtime_restart()

    def notify_commands(self, channel: str = "telegram", poll_interval: float | None = None) -> None:
        """Run the inbound notification command receiver."""
        from alphapilot.modules.portal.settings import apply_timezone
        from alphapilot.systems.notify.inbound import run_daemon

        apply_timezone()
        run_daemon(channel=channel, poll_interval=poll_interval)

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "portal": self.portal,
            "portal_restart": self.portal_restart,
            "notify_commands": self.notify_commands,
            "scheduler": self.scheduler,
            "timezone": self.timezone,
        }
