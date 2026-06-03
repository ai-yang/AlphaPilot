"""Strategy asset backtest module.

Run backtests directly from saved strategy assets in strategy_zoo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.strategy import StrategyBacktestRequest

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class StrategyBacktestModule(BaseModule):
    """CLI module for strategy-asset backtesting."""

    name = "strategy_backtest"

    def setup(self, context: "Context") -> None:
        self.context = context

    def strategy_backtest_list(self) -> list[dict[str, Any]]:
        strategy_system = self.context.strategy()
        out: list[dict[str, Any]] = []
        for r in strategy_system.list_strategy_records():
            out.append(
                {
                    "strategy_name": r.strategy_name,
                    "factor_count": len(r.factor_formulas),
                    "model_name": (r.model.model_name if r.model else None),
                    "has_model_artifact": bool(r.model and r.model.trained_artifact_uri),
                    "ic": (r.metrics.ic if r.metrics else None),
                    "icir": (r.metrics.icir if r.metrics else None),
                }
            )
        return out

    def strategy_backtest(
        self,
        strategy_name: str,
        qlib_data_dir: str | None = None,
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
        mode: str = "both",
        scenario: str = "factor_backtest",
        use_local: bool | None = None,
        run_tag: str | None = None,
        **options: Any,
    ) -> list[dict[str, Any]]:
        strategy_system = self.context.strategy()
        req = StrategyBacktestRequest(
            strategy_name=strategy_name,
            mode=mode,
            qlib_config_name=qlib_config_name,
            qlib_template_dir=qlib_template_dir,
            qlib_data_dir=qlib_data_dir,
            scenario=scenario,
            use_local=use_local,
            run_tag=run_tag,
            options=options,
        )
        outcomes = strategy_system.backtest_from_asset(req)
        rows: list[dict[str, Any]] = []
        for o in outcomes:
            row = {
                "strategy_name": o.strategy_name,
                "mode": o.mode,
                "IC": o.metrics.get("IC"),
                "ICIR": o.metrics.get("ICIR"),
                "Rank IC": o.metrics.get("Rank IC"),
                "Rank ICIR": o.metrics.get("Rank ICIR"),
                "workspace_path": o.workspace_path,
            }
            rows.append(row)
            print(
                f"[strategy_backtest] name={row['strategy_name']} mode={row['mode']} "
                f"IC={row['IC']} ICIR={row['ICIR']} "
                f"qlib_config={qlib_config_name} qlib_data_dir={qlib_data_dir}"
            )
        return rows

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "strategy_backtest": self.strategy_backtest,
            "strategy_backtest_list": self.strategy_backtest_list,
        }

