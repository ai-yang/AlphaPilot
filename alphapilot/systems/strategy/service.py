"""Default strategy management system.

Wraps the existing model task loader and the qlib model runner, and adds
a centralized strategy parameter database. Training is delegated to the
backtest system so strategy and factor share one execution backend.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphapilot.systems.backtest.types import FactorBacktestRequest, FactorDefinition, SavedModelBacktestRequest
from alphapilot.systems.strategy.base import (
    BaseStrategySystem,
    StrategyBacktestOutcome,
    StrategyBacktestRequest,
    StrategyMetrics,
    StrategyModelSpec,
    StrategyRecord,
)
from alphapilot.components.coder.factor_coder.config import resolve_factor_python_bin
from alphapilot.log import logger
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
    def _metrics_to_dict(metrics: StrategyMetrics | None) -> dict[str, Any]:
        if metrics is None:
            return {}
        return {
            "IC": metrics.ic,
            "ICIR": metrics.icir,
            "Rank IC": metrics.rank_ic,
            "Rank ICIR": metrics.rank_icir,
            **(metrics.extra or {}),
        }

    @staticmethod
    def _factors_to_defs(factor_formulas: list[str]) -> list[FactorDefinition]:
        return [
            FactorDefinition(factor_name=f"factor_{i+1:03d}", factor_expression=expr)
            for i, expr in enumerate(factor_formulas)
        ]

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

    def backtest_from_asset(self, request: StrategyBacktestRequest) -> list[StrategyBacktestOutcome]:
        record = self.get_strategy(request.strategy_name)
        if record is None:
            raise ValueError(f"Strategy asset not found: {request.strategy_name}")

        mode = request.mode.lower()
        if mode not in {"retrain", "reuse_model", "both"}:
            raise ValueError(f"Unsupported mode: {request.mode}")
        modes = ["retrain", "reuse_model"] if mode == "both" else [mode]

        factors = self._factors_to_defs(record.factor_formulas)
        qlib_config_name = request.qlib_config_name or (record.metadata or {}).get("qlib_config_name")
        qlib_template_dir = request.qlib_template_dir or (record.metadata or {}).get("qlib_template_dir")
        use_local = (
            request.use_local
            if request.use_local is not None
            else self.context.config.backtest.use_local
        )
        outcomes: list[StrategyBacktestOutcome] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        old_qlib_data_dir = os.environ.get("ALPHAPILOT_QLIB_DATA_DIR")
        if request.qlib_data_dir:
            os.environ["ALPHAPILOT_QLIB_DATA_DIR"] = str(request.qlib_data_dir)
        for m in modes:
            try:
                if m == "retrain":
                    from alphapilot.modules.alpha_mining.qlib.experiment.utils import get_data_folder_intro

                    logger.info(
                        f"[strategy_backtest] retrain strategy={record.strategy_name} "
                        f"factors={len(factors)} python={resolve_factor_python_bin()} "
                        f"qlib_config={qlib_config_name} qlib_template_dir={qlib_template_dir}"
                    )
                    get_data_folder_intro(use_local=use_local)
                    result = self.context.backtest().run_factor_backtest(
                        FactorBacktestRequest(
                            factors=factors,
                            scenario=request.scenario,
                            qlib_config_name=qlib_config_name,
                            qlib_template_dir=qlib_template_dir,
                            use_local=use_local,
                        )
                    )
                    metrics = self._extract_metrics(result.experiment if hasattr(result, "experiment") else result)
                    workspace_path = None
                    if hasattr(result, "experiment"):
                        ws = getattr(result.experiment, "experiment_workspace", None)
                        workspace_path = str(getattr(ws, "workspace_path", "")) or None
                    out = StrategyBacktestOutcome(
                        strategy_name=record.strategy_name,
                        mode="retrain",
                        metrics=self._metrics_to_dict(metrics),
                        workspace_path=workspace_path,
                        details={
                            "qlib_config_name": qlib_config_name,
                            "qlib_template_dir": qlib_template_dir,
                            "factor_python": resolve_factor_python_bin(),
                            "qlib_data_dir": request.qlib_data_dir,
                            "run_tag": request.run_tag,
                        },
                    )
                else:
                    model_uri = record.model.trained_artifact_uri if record.model else None
                    if not model_uri:
                        raise ValueError(f"Strategy {record.strategy_name} has no trained_artifact_uri for reuse_model mode.")
                    result = self.context.backtest().run_saved_model_backtest(
                        SavedModelBacktestRequest(
                            model_pickle_path=model_uri,
                            factors=factors,
                            scenario=request.scenario,
                            qlib_config_name=qlib_config_name,
                            qlib_template_dir=qlib_template_dir,
                            qlib_data_dir=request.qlib_data_dir,
                            use_local=use_local,
                            options=request.options,
                        )
                    )
                    metrics = self._extract_metrics(result.experiment if hasattr(result, "experiment") else result)
                    workspace_path = None
                    if hasattr(result, "experiment"):
                        ws = getattr(result.experiment, "experiment_workspace", None)
                        workspace_path = str(getattr(ws, "workspace_path", "")) or None
                    out = StrategyBacktestOutcome(
                        strategy_name=record.strategy_name,
                        mode="reuse_model",
                        metrics=self._metrics_to_dict(metrics),
                        workspace_path=workspace_path,
                        details={
                            "qlib_config_name": qlib_config_name,
                            "qlib_template_dir": qlib_template_dir,
                            "factor_python": resolve_factor_python_bin(),
                            "qlib_data_dir": request.qlib_data_dir,
                            "model_pickle_path": model_uri,
                            "run_tag": request.run_tag,
                            "note": "Current backend reuses saved model path via run_env hint; downstream runner support may vary.",
                        },
                    )
            except Exception as e:
                out = StrategyBacktestOutcome(
                    strategy_name=record.strategy_name,
                    mode=m,
                    metrics={},
                    workspace_path=None,
                    details={
                        "qlib_config_name": qlib_config_name,
                        "qlib_template_dir": qlib_template_dir,
                        "factor_python": resolve_factor_python_bin(),
                        "qlib_data_dir": request.qlib_data_dir,
                        "run_tag": request.run_tag,
                        "error": str(e),
                    },
                )

            outcomes.append(out)
            self._param_db.append_retest(
                record.strategy_name,
                {
                    "timestamp": timestamp,
                    "mode": out.mode,
                    "strategy_name": out.strategy_name,
                    "metrics": out.metrics,
                    "details": out.details,
                },
            )
        if request.qlib_data_dir:
            if old_qlib_data_dir is None:
                os.environ.pop("ALPHAPILOT_QLIB_DATA_DIR", None)
            else:
                os.environ["ALPHAPILOT_QLIB_DATA_DIR"] = old_qlib_data_dir
        return outcomes

    @property
    def param_database(self) -> Any:
        return self._param_db
