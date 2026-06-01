"""Built-in backtest engine adapter that wraps Qlib's ``qrun`` workspace.

The legacy :class:`QlibFBWorkspace` already orchestrates ``qrun`` in
either a local or Docker environment. This adapter exposes that flow
through :class:`BaseBacktestEngine` so additional engines (vectorbt,
backtrader, custom runner, ...) can be plugged in without changing the
calling code.
"""

from __future__ import annotations

from pathlib import Path

from alphapilot.adapters.base import (
    BacktestRequest,
    BacktestResult,
    BaseBacktestEngine,
)
from alphapilot.adapters.registry import BACKTEST_REGISTRY


@BACKTEST_REGISTRY.register("qlib", is_default=True)
class QlibBacktestEngine(BaseBacktestEngine):
    """Run a Qlib factor backtest via ``qrun`` on an existing workspace."""

    def run(self, request: BacktestRequest) -> BacktestResult:
        from alphapilot.systems.backtest.workspace import QlibFBWorkspace

        workspace_path = Path(request.workspace_path).expanduser()
        # The legacy workspace ingests its template folder via constructor;
        # we accept a ready workspace directory and reuse it directly.
        workspace = QlibFBWorkspace(template_folder_path=workspace_path)
        metrics = workspace.execute(
            qlib_config_name=request.config_name,
            run_env=request.run_env,
            use_local=request.use_local,
        )
        return BacktestResult(
            metrics=metrics,
            workspace_path=workspace_path,
            raw=metrics,
        )
