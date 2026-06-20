"""Backtest engines: pluggable evaluators dispatched by ``BacktestSpec.mode``."""

from __future__ import annotations

from alphapilot.systems.backtest.engines.base import BacktestEngine, EngineOutcome
from alphapilot.systems.backtest.engines.qlib_signal import (
    CLOSE_TASK_NAME,
    QlibSignalEngine,
    compute_factor_ic_table,
    make_close_task,
)
from alphapilot.systems.backtest.engines.qlib_workflow import QlibWorkflowEngine

__all__ = [
    "BacktestEngine",
    "EngineOutcome",
    "QlibWorkflowEngine",
    "QlibSignalEngine",
    "CLOSE_TASK_NAME",
    "make_close_task",
    "compute_factor_ic_table",
]
