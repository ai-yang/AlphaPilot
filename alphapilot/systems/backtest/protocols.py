"""Protocols for backtest execution (decoupled from alpha_mining types)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class BacktestWorkspace(Protocol):
    workspace_path: Path

    def execute(
        self,
        qlib_config_name: str = "conf.yaml",
        run_env: dict[str, Any] | None = None,
        use_local: bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...


@runtime_checkable
class FactorSubWorkspace(Protocol):
    def execute(self, *args: Any, **kwargs: Any) -> tuple[Any, Any] | Any: ...


@runtime_checkable
class FactorBacktestCapable(Protocol):
    """Minimum experiment surface required by :class:`QlibFactorRunner`."""

    based_experiments: Sequence[Any]
    sub_tasks: Sequence[Any]
    sub_workspace_list: Sequence[FactorSubWorkspace]
    experiment_workspace: BacktestWorkspace
    qlib_config_name: str | None
    qlib_template_dir: str | None
