"""CLI module for the timing system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.timing import TimingBacktestRequest

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _parse_symbols(value: Any) -> list[str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_params(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("strategy_params must be a JSON object")
        return parsed
    raise ValueError("strategy_params must be a JSON object string or mapping")


class TimingModule(BaseModule):
    """CLI commands for rule-based timing strategies."""

    name = "timing"

    def setup(self, context: "Context") -> None:
        self.context = context

    def _system(self):
        return self.context.system("timing")

    def timing_strategies(self) -> list[dict[str, Any]]:
        """List built-in timing strategies and default parameters."""
        rows = self._system().list_strategies()
        for row in rows:
            print(f"{row['name']}: {row['description']} defaults={row['defaults']}")
        return rows

    def timing_signal(
        self,
        strategy_name: str,
        symbols: Any = None,
        stock_csv: str | None = None,
        code_column: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        freq: str = "day",
        data_dir: str | None = None,
        adjust_mode: str = "backward",
        target_percent: float = 1.0,
        strategy_params: Any = None,
        output: str | None = None,
    ) -> dict[str, Any]:
        """Generate timing signals from local CSV bars."""
        req = TimingBacktestRequest(
            strategy_name=strategy_name,
            symbols=_parse_symbols(symbols),
            stock_csv=stock_csv,
            code_column=code_column,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
            data_dir=data_dir,
            adjust_mode=adjust_mode,
            target_percent=float(target_percent),
            strategy_params=_parse_params(strategy_params),
        )
        signals = self._system().generate_signals(req)
        output_path = Path(output).expanduser() if output else None
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            signals.to_csv(output_path, index=False)
        summary = {
            "strategy_name": strategy_name,
            "rows": int(len(signals)),
            "instruments": sorted(signals["instrument"].dropna().unique().tolist()),
            "output": str(output_path) if output_path else None,
        }
        print(json.dumps(summary, ensure_ascii=False, default=str))
        return summary

    def timing_backtest(
        self,
        strategy_name: str,
        symbols: Any = None,
        stock_csv: str | None = None,
        code_column: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        freq: str = "day",
        data_dir: str | None = None,
        adjust_mode: str = "backward",
        cash: float = 100000.0,
        target_percent: float = 1.0,
        open_cost: float = 0.0002,
        close_cost: float = 0.0008,
        min_cost: float = 5.0,
        slippage: float = 0.0,
        trade_unit: int = 100,
        strategy_params: Any = None,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        """Run a long-only timing backtest and write artifacts."""
        req = TimingBacktestRequest(
            strategy_name=strategy_name,
            symbols=_parse_symbols(symbols),
            stock_csv=stock_csv,
            code_column=code_column,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
            data_dir=data_dir,
            adjust_mode=adjust_mode,
            cash=float(cash),
            target_percent=float(target_percent),
            open_cost=float(open_cost),
            close_cost=float(close_cost),
            min_cost=float(min_cost),
            slippage=float(slippage),
            trade_unit=int(trade_unit),
            strategy_params=_parse_params(strategy_params),
            output_dir=output_dir,
        )
        result = self._system().run_backtest(req)
        print(json.dumps(result.summary, ensure_ascii=False, default=str))
        return result.summary

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "timing_strategies": self.timing_strategies,
            "timing_signal": self.timing_signal,
            "timing_backtest": self.timing_backtest,
        }
