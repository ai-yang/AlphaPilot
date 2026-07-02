"""CLI module for the live-trading subsystem.

Thin surface for now (status / modes) — the guarded actions (connect, submit
target, kill-switch) run inside the long-lived ``LiveEngine`` process and will be
exposed here + on the portal in a later phase. Paper/dry-run is the default mode.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class LiveModule(BaseModule):
    """CLI commands for inspecting the live-trading configuration."""

    name = "live"

    def setup(self, context: "Context") -> None:
        self.context = context

    def _system(self):
        return self.context.system("live")

    def live_status(self) -> dict[str, Any]:
        """Show the resolved live config (mode, broker, risk limits) — no secrets."""
        snapshot = self._system().snapshot()
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return snapshot

    def live_modes(self) -> list[str]:
        """List the run-mode ladder (dry_run -> paper -> live)."""
        modes = self._system().modes()
        print(json.dumps(modes, ensure_ascii=False))
        return modes

    def live_brokers(self) -> list[dict[str, Any]]:
        """List registered brokers: gateway, env fields for credentials, availability."""
        from alphapilot.systems.live.brokers.registry import (
            ENV_PREFIX,
            gateway_importable,
            list_brokers,
            missing_setting_fields,
        )

        rows = []
        for spec in list_brokers():
            prefix = f"{ENV_PREFIX}{spec.name.upper()}_"
            rows.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "gateway": spec.gateway_path,
                    "gateway_importable": gateway_importable(spec.name),
                    "env_fields": [prefix + f.env_suffix for f in spec.setting_fields],
                    "missing_env": missing_setting_fields(spec.name),
                }
            )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return rows

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "live_status": self.live_status,
            "live_modes": self.live_modes,
            "live_brokers": self.live_brokers,
        }
