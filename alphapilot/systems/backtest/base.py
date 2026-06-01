"""Backtest system interface.

A backtest system runs factor / model experiments and persists their
results. The default implementation wraps Qlib's ``qrun`` workspace, but
any engine can be plugged in by subclassing this and registering it under
the ``backtest`` system name (in-tree or via entry points).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from alphapilot.kernel.base import BaseSystem
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorExperimentBacktestRequest,
    FactorBacktestResult,
    ModelExperimentBacktestRequest,
    WorkspaceBacktestRequest,
)


class BaseBacktestSystem(BaseSystem):
    """Run factor/model backtests and manage their artifacts."""

    name = "backtest"

    @abstractmethod
    def run_factor_backtest(self, request: FactorBacktestRequest) -> FactorBacktestResult:
        """High-level factor backtest API (csv/list input)."""

    @abstractmethod
    def test_factors(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        """Run a factor backtest for *experiment*; return it with results."""

    @abstractmethod
    def test_model(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        """Run a model backtest for *experiment*; return it with results."""

    @abstractmethod
    def run_workspace(
        self,
        workspace_path: str,
        *,
        config_name: str = "conf.yaml",
        run_env: dict[str, str] | None = None,
        use_local: bool | None = None,
    ) -> Any:
        """Low-level: execute a ready backtest workspace via the engine."""

    @property
    @abstractmethod
    def results(self) -> Any:
        """Return the :class:`BacktestResultStore` for saved artifacts."""

    # ---- Typed request wrappers (preferred in new code) ----

    def run_factor_experiment(self, request: FactorExperimentBacktestRequest) -> Any:
        """Preferred typed wrapper for factor experiment backtests."""
        return self.test_factors(request.experiment, use_local=request.use_local)

    def run_model_experiment(self, request: ModelExperimentBacktestRequest) -> Any:
        """Preferred typed wrapper for model experiment backtests."""
        return self.test_model(request.experiment, use_local=request.use_local)

    def execute_workspace(self, request: WorkspaceBacktestRequest) -> Any:
        """Preferred typed wrapper for low-level workspace execution."""
        return self.run_workspace(
            workspace_path=str(request.workspace_path),
            config_name=request.config_name,
            run_env=request.run_env,
            use_local=request.use_local,
        )
