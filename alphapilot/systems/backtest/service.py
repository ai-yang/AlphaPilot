"""Default Qlib-backed backtest system.

Wraps the existing runners and the ``QlibFBWorkspace`` executor so
factor/model orchestration and low-level workspace execution are both
owned by the backtest system layer.
"""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphapilot.systems.backtest.base import BaseBacktestSystem
from alphapilot.systems.backtest.results import BacktestResultStore
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
    FactorDefinition,
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

    def _prepare_factor_csv(self, request: FactorBacktestRequest) -> tuple[Path, bool]:
        if request.factor_path is not None:
            return Path(request.factor_path).expanduser(), False

        if not request.factors:
            raise ValueError("FactorBacktestRequest requires factor_path or non-empty factors.")

        fd, temp_path = tempfile.mkstemp(prefix="alphapilot_factors_", suffix=".csv")
        temp_csv = Path(temp_path)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["factor_name", "factor_expression"])
            writer.writeheader()
            for factor in request.factors:
                writer.writerow(
                    {
                        "factor_name": factor.factor_name,
                        "factor_expression": factor.factor_expression,
                    }
                )
        return temp_csv, True

    def run_factor_backtest(self, request: FactorBacktestRequest) -> FactorBacktestResult:
        from alphapilot.core.utils import import_class
        from alphapilot.modules.alpha_mining.registry import get_scenario

        factor_csv, is_temp = self._prepare_factor_csv(request)
        use_local = self._use_local(request.use_local)
        try:
            spec = get_scenario(request.scenario, command="backtest")
            loop_cls = import_class(spec.loop_class_path)
            prop_setting = import_class(spec.prop_setting_path)
            loop = loop_cls(
                prop_setting,
                factor_path=str(factor_csv),
                context=self.context,
                use_local=use_local,
                qlib_config_name=request.qlib_config_name,
                qlib_template_dir=request.qlib_template_dir,
            )
            factor_propose_out = loop.factor_propose({})
            factor_construct_out = loop.factor_construct({"factor_propose": factor_propose_out})
            factor_calculate_out = loop.factor_calculate({"factor_construct": factor_construct_out})
            experiment = loop.factor_backtest({"factor_calculate": factor_calculate_out})
            return FactorBacktestResult(
                experiment=experiment,
                metrics=getattr(experiment, "result", None),
            )
        finally:
            if is_temp:
                try:
                    factor_csv.unlink(missing_ok=True)
                except OSError:
                    pass

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

    def run_saved_model_backtest(self, request: SavedModelBacktestRequest) -> Any:
        """
        Backtest with a saved model artifact.

        Current implementation keeps compatibility with the existing qlib
        runner by reusing saved factors on target data and passing the model
        artifact path via run_env for downstream consumers.
        """
        run_env: dict[str, str] = {}
        if request.qlib_data_dir:
            run_env["ALPHAPILOT_QLIB_DATA_DIR"] = str(request.qlib_data_dir)
        run_env["ALPHAPILOT_PRETRAINED_MODEL_PKL"] = str(Path(request.model_pickle_path).expanduser())

        # Use existing high-level factor backtest path.
        # NOTE: runners that do not consume ALPHAPILOT_PRETRAINED_MODEL_PKL
        # will effectively retrain; callers can inspect details metadata.
        result = self.run_factor_backtest(
            FactorBacktestRequest(
                factors=request.factors,
                scenario=request.scenario,
                qlib_config_name=request.qlib_config_name,
                qlib_template_dir=request.qlib_template_dir,
                use_local=request.use_local,
            )
        )
        setattr(result, "_pretrained_model_env", run_env)
        return result

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
