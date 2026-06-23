"""Saved-model factor evaluation (delegates to factor evaluation + env hints)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alphapilot.systems.backtest.pipelines.factor_evaluation import run_factor_evaluation
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
    SavedModelBacktestRequest,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def run_saved_model_evaluation(
    context: Context,
    request: SavedModelBacktestRequest,
) -> FactorBacktestResult:
    run_env: dict[str, str] = {}
    if request.qlib_data_dir:
        run_env["ALPHAPILOT_QLIB_DATA_DIR"] = str(request.qlib_data_dir)
    run_env["ALPHAPILOT_PRETRAINED_MODEL_PKL"] = str(Path(request.model_pickle_path).expanduser())

    return run_factor_evaluation(
        context,
        FactorBacktestRequest(
            factors=request.factors,
            factor_path=None,
            scenario=request.scenario,
            qlib_config_name=request.qlib_config_name,
            qlib_template_dir=request.qlib_template_dir,
            use_local=request.use_local,
            run_env=run_env,
            market=request.market,
            yaml_params=request.yaml_params,
        ),
    )
