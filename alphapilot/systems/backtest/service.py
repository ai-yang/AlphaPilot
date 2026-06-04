"""Default Qlib-backed backtest system.

Owns factor evaluation pipelines, experiment execution, and qlib workspace runs.
``alpha_mining`` delegates CSV/list backtests via :meth:`run_factor_evaluation`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphapilot.systems.backtest.base import BaseBacktestSystem
from alphapilot.systems.backtest.results import BacktestResultStore
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
    FactorExperimentBacktestRequest,
    ModelExperimentBacktestRequest,
    SavedModelBacktestRequest,
    WorkspaceBacktestRequest,
    WorkspaceBacktestResult,
)
from alphapilot.systems.backtest.workspace import QlibFBWorkspace

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class QlibBacktestSystem(BaseBacktestSystem):
    """Qlib ``qrun`` backtest system (factor + model)."""

    def setup(self, context: "Context") -> None:
        self.context = context
        self._results = BacktestResultStore(context.config.backtest.workspace_root)

    def _use_local(self, use_local: bool | None) -> bool:
        if use_local is not None:
            return use_local
        return self.context.config.backtest.use_local

    def run_factor_evaluation(self, request: FactorBacktestRequest) -> FactorBacktestResult:
        from alphapilot.systems.backtest.pipelines.factor_evaluation import run_factor_evaluation

        return run_factor_evaluation(self.context, request)

    def run_saved_model_evaluation(self, request: SavedModelBacktestRequest) -> FactorBacktestResult:
        from alphapilot.systems.backtest.pipelines.saved_model_evaluation import (
            run_saved_model_evaluation,
        )

        return run_saved_model_evaluation(self.context, request)

    def test_factors(
        self,
        experiment: Any | FactorExperimentBacktestRequest,
        *,
        use_local: bool | None = None,
    ) -> Any:
        if isinstance(experiment, FactorExperimentBacktestRequest):
            request = experiment
        else:
            request = FactorExperimentBacktestRequest(
                experiment=experiment,
                use_local=use_local,
            )
        return self.run_factor_experiment(request)

    def run_factor_experiment(self, request: FactorExperimentBacktestRequest) -> Any:
        from alphapilot.systems.backtest.qlib_config import resolve_qlib_config_name
        from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner

        if request.qlib_config_name:
            request.experiment.qlib_config_name = request.qlib_config_name

        scen = getattr(request.experiment, "scen", None)
        runner = QlibFactorRunner(scen)
        exp = runner.develop(
            request.experiment,
            use_local=self._use_local(request.use_local),
        )
        exp.qlib_config_name = resolve_qlib_config_name(exp)
        return exp

    def test_model(
        self,
        experiment: Any | ModelExperimentBacktestRequest,
        *,
        use_local: bool | None = None,
    ) -> Any:
        if isinstance(experiment, ModelExperimentBacktestRequest):
            request = experiment
        else:
            request = ModelExperimentBacktestRequest(
                experiment=experiment,
                use_local=use_local,
            )
        return self.run_model_experiment(request)

    def run_model_experiment(self, request: ModelExperimentBacktestRequest) -> Any:
        from alphapilot.systems.backtest.runners.model_runner import QlibModelRunner

        scen = getattr(request.experiment, "scen", None)
        runner = QlibModelRunner(scen)
        return runner.develop(
            request.experiment,
            use_local=self._use_local(request.use_local),
            run_env=request.run_env,
        )

    def run_workspace(
        self,
        workspace_path: str | WorkspaceBacktestRequest,
        *,
        config_name: str = "conf.yaml",
        run_env: dict[str, str] | None = None,
        use_local: bool | None = None,
    ) -> WorkspaceBacktestResult:
        if isinstance(workspace_path, WorkspaceBacktestRequest):
            request = workspace_path
        else:
            request = WorkspaceBacktestRequest(
                workspace_path=workspace_path,
                config_name=config_name,
                run_env=run_env or {},
                use_local=use_local,
            )

        resolved_use_local = self._use_local(request.use_local)
        workspace_root = Path(request.workspace_path).expanduser()
        workspace = QlibFBWorkspace(template_folder_path=workspace_root)
        metrics = workspace.execute(
            qlib_config_name=request.config_name,
            run_env=request.run_env,
            use_local=resolved_use_local,
        )
        return WorkspaceBacktestResult(
            metrics=metrics,
            workspace_path=workspace_root,
            raw=metrics,
        )

    @property
    def results(self) -> BacktestResultStore:
        return self._results
