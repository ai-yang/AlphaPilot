"""Portal module: unified web UI for kernel systems and plugins."""

from __future__ import annotations

import os
import uuid
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
        from alphapilot.modules.portal.settings import (
            load_portal_settings,
            resolve_operator_auth,
        )

        settings = load_portal_settings()
        host = host or settings["host"]
        port = int(port if port is not None else settings["port"])
        apply_portal_env()

        if reload:
            if not bool(resolve_operator_auth()["required"]):
                print(
                    "[portal] WARNING: operator authentication is OPTIONAL; "
                    f"unauthenticated trading writes are accepted on {host}:{port}"
                )
            # The reloader creates the app in a child process, so carry the
            # actual listener boundary into the factory through the environment.
            os.environ["ALPHAPILOT_PORTAL_BIND_HOST"] = str(host)
            uvicorn.run("alphapilot.modules.portal.api:create_app", host=host, port=port, reload=True, factory=True)
            return
        static_dir = Path(__file__).parent / "web" / "dist"
        app = create_app(static_dir=static_dir, portal_host=host, portal_port=port)
        install_restart_signal_handler()
        operator_auth_required = bool(app.state.operator_auth_required)
        write_runtime(
            host=host,
            port=port,
            argv=current_restart_argv(),
            operator_auth_required=operator_auth_required,
        )
        if not operator_auth_required:
            print(
                "[portal] WARNING: operator authentication is OPTIONAL; "
                f"unauthenticated trading writes are accepted on {host}:{port}"
            )
        self._autostart_scheduler()
        try:
            uvicorn.run(app, host=host, port=port)
        finally:
            clear_runtime()

    @staticmethod
    def _autostart_scheduler() -> None:
        """Recover durable jobs and schedules independently of the HTTP process."""
        try:
            from alphapilot.research.runtime import ensure_running
            from alphapilot.research.store import Store
            if os.getenv("ALPHAPILOT_RESEARCH_AUTOSTART", "1") != "0":
                ensure_running(Store())
        except Exception as exc:  # noqa: BLE001 - never let the daemon block the portal
            print(f"[portal] scheduler daemon auto-start skipped: {type(exc).__name__}: {exc}")

    def scheduler(self, interval: int = 30) -> None:
        """Run the unified research queue and schedule dispatcher in the foreground."""
        from alphapilot.research.runtime import main
        main([])

    def research_migrate(self, execute: bool = False):
        """Inspect or perform the stopped-workspace research v1 migration."""
        from alphapilot.research.migration import migrate
        from alphapilot.research.store import Store
        from alphapilot.kernel import build_engine
        return migrate(Store(), build_engine(discover=True), execute=execute)

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

    def portal_operator_auth(
        self,
        required: bool | None = None,
        operator_id: str = "",
        reason: str = "",
        acknowledge_network_risk: bool = False,
        restart: bool = False,
    ) -> dict[str, Any]:
        """Show or change Portal operator authentication.

        Disabling authentication accepts unauthenticated trading writes,
        including LIVE orders and Kill Switch changes, from every reachable
        client. Changes are persisted locally and take effect after restart.
        """
        from alphapilot.modules.portal.runtime import (
            load_runtime,
            pid_running,
            request_runtime_restart,
        )
        from alphapilot.modules.portal.settings import (
            coerce_bool,
            load_file_portal_settings,
            operator_auth_environment_override,
            resolve_operator_auth,
            set_operator_auth_required,
        )
        from alphapilot.systems.trading.contracts import OperatorContext

        def status() -> dict[str, Any]:
            resolved = resolve_operator_auth()
            saved = load_file_portal_settings()
            runtime = load_runtime()
            running = pid_running(runtime.get("pid"))
            running_required = (
                bool(runtime.get("operator_auth_required", True))
                if running
                else None
            )
            effective = bool(resolved["required"])
            bind_host = str(
                runtime.get("host")
                or saved.get("host")
                or "127.0.0.1"
            )
            bind_port = int(
                runtime.get("port")
                or saved.get("port")
                or 19901
            )
            network_exposed = bind_host.strip().lower() not in {
                "127.0.0.1", "localhost", "::1",
            }
            return {
                **resolved,
                "running": running,
                "running_required": running_required,
                "running_mode": (
                    "required" if running_required else "optional"
                ) if running_required is not None else "unknown",
                "restart_required": bool(
                    running
                    and running_required is not None
                    and running_required != effective
                ),
                "bind_host": bind_host,
                "bind_port": bind_port,
                "bind_address": f"{bind_host}:{bind_port}",
                "network_exposed": network_exposed,
                "warning": (
                    "Unauthenticated trading writes are accepted from every "
                    "reachable client; wildcard CORS remains enabled."
                    if not effective else ""
                ),
            }

        before = status()
        if required is None:
            return before

        desired = coerce_bool(required, name="required")
        risk_acknowledged = coerce_bool(
            acknowledge_network_risk,
            name="acknowledge_network_risk",
        )
        restart_requested = coerce_bool(restart, name="restart")
        operator = str(operator_id).strip()
        why = str(reason).strip()
        if not operator:
            raise ValueError("operator_id is required when changing authentication")
        if not why:
            raise ValueError("reason is required when changing authentication")
        if not desired and not risk_acknowledged:
            raise ValueError(
                "disabling authentication requires "
                "acknowledge_network_risk=true"
            )
        override = operator_auth_environment_override()
        if override is not None and bool(override) != desired:
            raise ValueError(
                "ALPHAPILOT_OPERATOR_AUTH_REQUIRED overrides the CLI setting; "
                "remove or change the environment override first"
            )

        context = OperatorContext(
            operator_id=operator,
            request_id=uuid.uuid4().hex,
            reason=why,
            auth_source="local-cli",
        )
        trading = self.context.system("trading")
        details = {
            "old_required": bool(before["saved_required"]),
            "new_required": desired,
            "acknowledge_network_risk": risk_acknowledged,
            "bind_host": before["bind_host"],
            "bind_port": before["bind_port"],
            "bind_address": before["bind_address"],
            "network_exposed": before["network_exposed"],
            "restart_requested": restart_requested,
        }
        trading.operator_auth.audit(
            context,
            action="portal_operator_auth_change",
            result="requested",
            details=details,
        )
        try:
            saved_to = set_operator_auth_required(desired)
        except Exception as exc:
            trading.operator_auth.audit(
                context,
                action="portal_operator_auth_change",
                result="failed",
                details={**details, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise

        restart_result: dict[str, Any] | None = None
        if restart_requested:
            try:
                restart_result = request_runtime_restart()
            except Exception as exc:  # setting remains saved for the next start
                restart_result = {
                    "accepted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        after = status()
        result = {
            **after,
            "changed": bool(before["saved_required"]) != desired,
            "saved_to": str(saved_to),
            "restart": restart_result,
        }
        trading.operator_auth.audit(
            context,
            action="portal_operator_auth_change",
            result="ok",
            details={**details, "restart": restart_result},
        )
        return result

    def notify_commands(self, channel: str = "telegram", poll_interval: float | None = None) -> None:
        """Run the inbound notification command receiver."""
        from alphapilot.modules.portal.settings import apply_timezone
        from alphapilot.systems.notify.inbound import run_daemon

        apply_timezone()
        run_daemon(channel=channel, poll_interval=poll_interval)

    def commands(self) -> dict[str, Callable[..., Any]]:
        from alphapilot.research.cli import research_token, task_runtime
        return {
            "research_token": research_token,
            "task_runtime": task_runtime,
            "research_migrate": self.research_migrate,
            "portal": self.portal,
            "portal_operator_auth": self.portal_operator_auth,
            "portal_restart": self.portal_restart,
            "notify_commands": self.notify_commands,
            "scheduler": self.scheduler,
            "timezone": self.timezone,
        }
