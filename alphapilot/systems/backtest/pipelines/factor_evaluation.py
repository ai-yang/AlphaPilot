"""Factor evaluation pipeline owned by the backtest system (CSV → calculate → qlib)."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from alphapilot.components.coder.factor_coder import FactorCoder
from alphapilot.core.pickle_cache import pickle_cache_scope
from alphapilot.components.coder.factor_coder.data import ensure_factor_data
from alphapilot.systems.backtest.pipelines.factor_source import build_factor_experiment_from_csv
from alphapilot.systems.backtest.qlib.scenario import QlibFactorEvaluationScenario
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _resolve_use_local(context: Context, use_local: bool | None) -> bool:
    if use_local is not None:
        return use_local
    return context.config.backtest.use_local


def prepare_factor_csv(request: FactorBacktestRequest) -> tuple[Path, bool]:
    """Return ``(csv path, is_temporary)``."""
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


class FactorEvaluationPipeline:
    """End-to-end evaluation for user-supplied factor expressions (no mining loop)."""

    def run(self, context: Context, request: FactorBacktestRequest) -> FactorBacktestResult:
        factor_csv, is_temp = prepare_factor_csv(request)
        use_local = _resolve_use_local(context, request.use_local)
        try:
            ensure_factor_data(use_local=use_local)
            scenario = QlibFactorEvaluationScenario(
                use_local=use_local,
                qlib_template_dir=request.qlib_template_dir,
            )
            experiment = build_factor_experiment_from_csv(
                factor_csv,
                qlib_template_dir=request.qlib_template_dir,
            )
            if request.qlib_config_name:
                experiment.qlib_config_name = request.qlib_config_name
            experiment.run_env = dict(request.run_env)

            with pickle_cache_scope("backtest"):
                coder = FactorCoder(
                    scenario,
                    with_feedback=False,
                    with_knowledge=False,
                    knowledge_self_gen=False,
                )
                experiment = coder.develop(experiment)

                from alphapilot.systems.backtest.qlib_config import resolve_qlib_config_name
                from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner

                if request.qlib_config_name:
                    experiment.qlib_config_name = request.qlib_config_name
                runner = QlibFactorRunner(None)
                experiment = runner.develop(
                    experiment,
                    use_local=use_local,
                    run_env=experiment.run_env,
                )
            experiment.qlib_config_name = resolve_qlib_config_name(experiment)
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


def run_factor_evaluation(context: Context, request: FactorBacktestRequest) -> FactorBacktestResult:
    """Module-level entry for :meth:`QlibBacktestSystem.run_factor_evaluation`."""
    return FactorEvaluationPipeline().run(context, request)
