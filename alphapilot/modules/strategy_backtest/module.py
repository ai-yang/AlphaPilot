"""Strategy asset backtest module.

Run backtests directly from saved strategy assets in strategy_zoo.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.strategy import StrategyBacktestRequest

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _parse_factor_names(value: Any) -> list[str]:
    """Normalize a CLI ``--factor_names`` value (``"a,b"`` or a list) to a list."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def _parse_yaml_params(value: Any) -> dict[str, Any] | None:
    """Normalize a CLI ``--yaml_params`` value (JSON object string or mapping)."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("yaml_params must be a JSON object")
        return parsed
    raise ValueError("yaml_params must be a JSON object string or mapping")


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

    def strategy_create(
        self,
        strategy_name: str,
        factor_names: Any,
        model_name: str | None = None,
        market: str | None = None,
        yaml_params: Any = None,
    ) -> dict[str, Any]:
        """Create a strategy asset from factor-zoo factors.

        ``--factor_names`` accepts ``"a,b,c"`` or a list; ``--model_name`` is the model
        label (e.g. ``LGBModel``; ``none`` / empty = no model); ``--market`` sets the stock
        pool; ``--yaml_params`` accepts a JSON object string for rebalance / cost / date
        overrides. The strategy is saved (not backtested) and can later be run via
        ``strategy_backtest``.
        """
        names = _parse_factor_names(factor_names)
        params = _parse_yaml_params(yaml_params)
        record = self.context.strategy().create_strategy_from_factors(
            strategy_name=strategy_name,
            factor_names=names,
            model_name=model_name,
            market=market,
            yaml_params=params,
        )
        summary = {
            "strategy_name": record.strategy_name,
            "factor_count": len(record.factor_formulas),
            "model_name": record.model.model_name if record.model else None,
            "market": (record.metadata or {}).get("market"),
        }
        print(
            f"[strategy_create] name={summary['strategy_name']} "
            f"factors={summary['factor_count']} model={summary['model_name']} "
            f"market={summary['market']}"
        )
        return summary

    def strategy_backtest(
        self,
        strategy_name: str,
        qlib_data_dir: str | None = None,
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
        mode: str = "retrain",
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
            "strategy_create": self.strategy_create,
            "strategy_backtest": self.strategy_backtest,
            "strategy_backtest_list": self.strategy_backtest_list,
        }

