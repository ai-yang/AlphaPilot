"""Run-mode FSM + global kill-switch.

Two orthogonal pieces of safety state:

* **mode ladder** ``DRY_RUN <-> PAPER <-> LIVE`` — you cannot jump straight from
  ``DRY_RUN`` to ``LIVE`` (must pass through ``PAPER``); this is enforced so a
  fat-fingered mode change can't put real money at risk in one step.
* **halted** — the kill-switch. Any component may ``halt(reason)``; while halted,
  :meth:`can_submit_orders` is ``False`` regardless of mode. ``resume`` clears it.

The risk gate checks this machine on every order.
"""

from __future__ import annotations

from alphapilot.systems.live.config import RunMode
from alphapilot.systems.live.fsm.base import check_transition

# Adjacent modes on the ladder (self included for idempotence).
ALLOWED: dict[str, set[str]] = {
    RunMode.DRY_RUN: {RunMode.DRY_RUN, RunMode.PAPER},
    RunMode.PAPER: {RunMode.PAPER, RunMode.DRY_RUN, RunMode.LIVE},
    RunMode.LIVE: {RunMode.LIVE, RunMode.PAPER},
}


class RunModeMachine:
    """Run mode + kill-switch, guarding order submission."""

    def __init__(self, mode: str = RunMode.DRY_RUN) -> None:
        if mode not in ALLOWED:
            raise ValueError(f"unknown run mode: {mode!r}")
        self.mode = mode
        self.halted = False
        self.halt_reason = ""

    def set_mode(self, target: str) -> str:
        if target not in ALLOWED:
            raise ValueError(f"unknown run mode: {target!r}")
        check_transition(ALLOWED, self.mode, target, label="run-mode")
        self.mode = target
        return self.mode

    def halt(self, reason: str = "") -> None:
        """Engage the kill-switch (idempotent)."""
        self.halted = True
        self.halt_reason = reason or self.halt_reason or "halted"

    def resume(self) -> None:
        self.halted = False
        self.halt_reason = ""

    def can_submit_orders(self) -> bool:
        """Orders may be routed only when not halted and not in dry-run."""
        return not self.halted and self.mode in (RunMode.PAPER, RunMode.LIVE)

    def is_dry_run(self) -> bool:
        return self.mode == RunMode.DRY_RUN
