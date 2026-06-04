"""Strategy-asset backtest orchestration (delegates to backtest evaluation pipeline)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from alphapilot.components.coder.factor_coder.data import ensure_factor_data
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
    FactorDefinition,
    SavedModelBacktestRequest,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context

StrategyBacktestMode = Literal["retrain", "reuse_model"]


@dataclass
class StrategyAssetBacktestRun:
    mode: StrategyBacktestMode
    result: FactorBacktestResult
    workspace_path: str | None


def _workspace_path_from_result(result: FactorBacktestResult) -> str | None:
    exp = result.experiment
    ws = getattr(exp, "experiment_workspace", None)
    path = getattr(ws, "workspace_path", None)
    return str(path) if path else None


def run_strategy_asset_backtest(
    context: Context,
    *,
    mode: StrategyBacktestMode,
    factors: list[FactorDefinition],
    scenario: str = "factor_backtest",
    qlib_config_name: str | None = None,
    qlib_template_dir: str | None = None,
    qlib_data_dir: str | None = None,
    use_local: bool | None = None,
    model_pickle_path: str | None = None,
) -> StrategyAssetBacktestRun:
    backtest = context.backtest()
    use_local_resolved = (
        use_local if use_local is not None else context.config.backtest.use_local
    )

    if mode == "retrain":
        ensure_factor_data(use_local=use_local_resolved)
        result = backtest.run_factor_evaluation(
            FactorBacktestRequest(
                factors=factors,
                scenario=scenario,
                qlib_config_name=qlib_config_name,
                qlib_template_dir=qlib_template_dir,
                use_local=use_local,
            )
        )
    elif mode == "reuse_model":
        if not model_pickle_path:
            raise ValueError("reuse_model requires model_pickle_path.")
        result = backtest.run_saved_model_evaluation(
            SavedModelBacktestRequest(
                model_pickle_path=model_pickle_path,
                factors=factors,
                scenario=scenario,
                qlib_config_name=qlib_config_name,
                qlib_template_dir=qlib_template_dir,
                qlib_data_dir=qlib_data_dir,
                use_local=use_local,
            )
        )
    else:
        raise ValueError(f"Unsupported strategy backtest mode: {mode!r}")

    return StrategyAssetBacktestRun(
        mode=mode,
        result=result,
        workspace_path=_workspace_path_from_result(result),
    )
