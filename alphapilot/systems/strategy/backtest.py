"""Strategy-asset backtest orchestration.

Delegates to the backtest system's evaluation pipeline. Lives in the
strategy system (its sole consumer) rather than the alpha-mining module
so that the strategy system never has to reach "up" into a module — the
dependency only flows strategy-system -> backtest-system via the context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

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
    market: str | None = None,
    yaml_params: Any = None,
) -> StrategyAssetBacktestRun:
    backtest = context.backtest()

    # The factor h5 context (incl. global-folder fallback) is prepared inside the evaluation
    # pipeline (_build_experiment); binding ``market`` here keeps the strategy retest on the same
    # instrument universe it was trained on.
    if mode == "retrain":
        result = backtest.run_factor_evaluation(
            FactorBacktestRequest(
                factors=factors,
                scenario=scenario,
                qlib_config_name=qlib_config_name,
                qlib_template_dir=qlib_template_dir,
                use_local=use_local,
                market=market,
                yaml_params=yaml_params,
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
                market=market,
                yaml_params=yaml_params,
            )
        )
    else:
        raise ValueError(f"Unsupported strategy backtest mode: {mode!r}")

    return StrategyAssetBacktestRun(
        mode=mode,
        result=result,
        workspace_path=_workspace_path_from_result(result),
    )
