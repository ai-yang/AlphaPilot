"""Thin delegates to the backtest system's factor evaluation pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
    SavedModelBacktestRequest,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def run_factor_backtest_from_request(
    context: Context,
    request: FactorBacktestRequest,
) -> FactorBacktestResult:
    return context.backtest().run_factor_evaluation(request)


def run_saved_model_backtest_from_request(
    context: Context,
    request: SavedModelBacktestRequest,
) -> FactorBacktestResult:
    return context.backtest().run_saved_model_evaluation(request)
