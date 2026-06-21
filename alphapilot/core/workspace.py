"""Per-run workspace-root override.

`FBWorkspace` roots every factor / experiment workspace under a single directory. By default
that is the global `RD_AGENT_SETTINGS.workspace_path`; a task entry (mine/backtest) can override
it for the duration of one run via the contextvar here so all of a run's workspaces land under a
named per-task directory (see `alphapilot.systems.run_workspace`).

A contextvar (not a mutated global) is used so the override is scoped to the calling
task/thread/async context and is restored automatically — workspaces are created in the parent
process, so this covers them even when execution later fans out to multiprocessing.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path

_workspace_root_override: ContextVar[Path | None] = ContextVar(
    "workspace_root_override", default=None
)


def set_workspace_root_override(path: str | Path) -> Token:
    """Override the workspace root; returns a token for `reset_workspace_root_override`."""
    return _workspace_root_override.set(Path(path))


def reset_workspace_root_override(token: Token) -> None:
    _workspace_root_override.reset(token)


def resolve_workspace_root() -> Path:
    """Active workspace root: the contextvar override if set, else the global setting."""
    override = _workspace_root_override.get()
    if override is not None:
        return override
    from alphapilot.core.conf import RD_AGENT_SETTINGS

    return Path(RD_AGENT_SETTINGS.workspace_path)
