"""Timing system service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from alphapilot.kernel.base import BaseSystem
from alphapilot.systems.timing.base import TimingBacktestRequest, TimingBacktestResult, TimingContext
from alphapilot.systems.timing.data import load_bars
from alphapilot.systems.timing.engine import TimingBacktestEngine
from alphapilot.systems.timing.strategies import create_strategy, list_strategy_specs

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class TimingSystem(BaseSystem):
    """Rule-based timing strategies over local AlphaPilot market data."""

    name = "timing"

    def setup(self, context: "Context") -> None:
        self.context = context
        self._engine = TimingBacktestEngine()

    def list_strategies(self) -> list[dict[str, Any]]:
        return list_strategy_specs()

    def load_bars(self, **options: Any) -> pd.DataFrame:
        return load_bars(self.context, **options)

    def generate_signals(self, request: TimingBacktestRequest) -> pd.DataFrame:
        bars = self.load_bars(
            symbols=request.symbols,
            stock_csv=request.stock_csv,
            code_column=request.code_column,
            start_date=request.start_date,
            end_date=request.end_date,
            freq=request.freq,
            data_dir=request.data_dir,
            adjust_mode=request.adjust_mode,
        )
        params = dict(request.strategy_params)
        params["target_percent"] = request.target_percent
        strategy = create_strategy(request.strategy_name, params)
        return strategy.generate_signals(
            bars,
            TimingContext(
                params=params,
                freq=request.freq,
                metadata={"strategy_name": request.strategy_name},
            ),
        )

    def run_backtest(self, request: TimingBacktestRequest) -> TimingBacktestResult:
        bars = self.load_bars(
            symbols=request.symbols,
            stock_csv=request.stock_csv,
            code_column=request.code_column,
            start_date=request.start_date,
            end_date=request.end_date,
            freq=request.freq,
            data_dir=request.data_dir,
            adjust_mode=request.adjust_mode,
        )
        params = dict(request.strategy_params)
        params["target_percent"] = request.target_percent
        strategy = create_strategy(request.strategy_name, params)
        signals = strategy.generate_signals(
            bars,
            TimingContext(
                params=params,
                freq=request.freq,
                metadata={"strategy_name": request.strategy_name},
            ),
        )
        return self._engine.run(bars=bars, signals=signals, request=request)
