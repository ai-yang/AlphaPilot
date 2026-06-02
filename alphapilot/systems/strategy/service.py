"""Default strategy management system.

Wraps the existing model task loader and the qlib model runner, and adds
a centralized strategy parameter database. Training is delegated to the
backtest system so strategy and factor share one execution backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphapilot.systems.strategy.base import (
    BaseStrategySystem,
    StrategyMetrics,
    StrategyModelSpec,
    StrategyRecord,
)
from alphapilot.systems.strategy.database import build_strategy_param_database

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class StrategySystem(BaseStrategySystem):
    """Strategy import + param database + training."""

    def setup(self, context: "Context") -> None:
        self.context = context
        cfg = context.config.strategy
        self._param_db = build_strategy_param_database(cfg.database_backend, cfg.param_dir)

    def import_strategy(self, source: Any, *, kind: str = "pdf") -> Any:
        if kind == "pdf":
            from alphapilot.components.coder.model_coder.task_loader import (
                ModelExperimentLoaderFromPDFfiles,
            )

            return ModelExperimentLoaderFromPDFfiles().load(source)
        if kind == "dict":
            from alphapilot.components.coder.model_coder.task_loader import (
                ModelExperimentLoaderFromDict,
            )

            return ModelExperimentLoaderFromDict().load(source)
        raise ValueError(f"Unsupported strategy import kind: {kind!r}")

    def train(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        from alphapilot.systems.backtest.types import ModelExperimentBacktestRequest

        return self.context.backtest().run_model_experiment(
            ModelExperimentBacktestRequest(
                experiment=experiment,
                use_local=use_local,
            )
        )

    def register_strategy(self, record: StrategyRecord) -> None:
        self._param_db.save_record(record)

    def get_strategy(self, strategy_name: str) -> StrategyRecord | None:
        return self._param_db.load_record(strategy_name)

    def list_strategy_records(self) -> list[StrategyRecord]:
        records: list[StrategyRecord] = []
        for name in self._param_db.list_strategies():
            rec = self._param_db.load_record(name)
            if rec is not None:
                records.append(rec)
        return records

    @staticmethod
    def _extract_metrics(result: Any) -> StrategyMetrics | None:
        source = getattr(result, "metrics", None)
        if source is None:
            source = getattr(result, "result", None)
        if source is None:
            return None

        # Accept pd.Series / dict-like via best-effort conversion.
        if hasattr(source, "to_dict"):
            source = source.to_dict()
        if not isinstance(source, dict):
            return None

        def _pick(*keys: str) -> float | None:
            for k in keys:
                if k in source:
                    try:
                        return float(source[k])
                    except Exception:
                        return None
            return None

        return StrategyMetrics(
            ic=_pick("IC", "ic"),
            icir=_pick("ICIR", "information_ratio", "icir"),
            rank_ic=_pick("Rank IC", "rank_ic", "rankIC"),
            rank_icir=_pick("Rank ICIR", "rank_icir", "rankICIR"),
            extra={k: v for k, v in source.items() if k not in {"IC", "ic", "ICIR", "information_ratio", "icir", "Rank IC", "rank_ic", "rankIC", "Rank ICIR", "rank_icir", "rankICIR"}},
        )

    def train_and_register(
        self,
        *,
        strategy_name: str,
        factor_formulas: list[str],
        model_name: str,
        hyper_params: dict[str, Any] | None = None,
        trained_artifact_uri: str | None = None,
        fitted_params: dict[str, Any] | None = None,
        experiment: Any,
        use_local: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyRecord:
        """
        Train strategy and persist full strategy asset in one call.
        """
        result = self.train(experiment=experiment, use_local=use_local)
        record = StrategyRecord(
            strategy_name=strategy_name,
            factor_formulas=factor_formulas,
            model=StrategyModelSpec(
                model_name=model_name,
                hyper_params=hyper_params or {},
                trained_artifact_uri=trained_artifact_uri,
                fitted_params=fitted_params or {},
            ),
            metrics=self._extract_metrics(result),
            metadata={"train_result_type": type(result).__name__, **(metadata or {})},
        )
        self.register_strategy(record)
        return record

    @property
    def param_database(self) -> Any:
        return self._param_db
