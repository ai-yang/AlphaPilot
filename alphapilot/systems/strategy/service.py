"""Default strategy management system.

Wraps the existing model task loader and the qlib model runner, and adds
a centralized strategy parameter database. Training is delegated to the
backtest system so strategy and factor share one execution backend.
"""

from __future__ import annotations
from alphapilot.research.guards import guarded

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphapilot.systems.backtest.types import FactorDefinition
from alphapilot.systems.strategy.base import (
    BaseStrategySystem,
    StrategyBacktestOutcome,
    StrategyBacktestRequest,
    StrategyMetrics,
    StrategyModelSpec,
    StrategyRecord,
)
from alphapilot.components.coder.factor_coder.config import resolve_factor_python_bin
from alphapilot.kernel.paths import remap_legacy_relative_path
from alphapilot.log import logger
from alphapilot.systems.data.factor_h5 import ENV_FINGERPRINT, ENV_MARKET
from alphapilot.systems.strategy.backtest import run_strategy_asset_backtest
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

    @guarded("strategy", "write")
    def register_strategy(self, record: StrategyRecord) -> None:
        self._param_db.save_record(record)

    @guarded("strategy", "write")
    def create_strategy_from_factors(
        self,
        *,
        strategy_name: str,
        factor_names: list[str],
        model_name: str | None = None,
        market: str | None = None,
        yaml_params: dict[str, Any] | None = None,
    ) -> StrategyRecord:
        """Build and persist a strategy asset from factor-zoo factor names.

        Resolves each name to its expression via the factor system, then registers a
        ``StrategyRecord`` whose ``metadata`` carries the stock pool (``market``) and the
        rebalance / cost / date overrides (``yaml_params``) so the saved strategy is
        self-contained for later retests.
        """
        name = (strategy_name or "").strip()
        if not name:
            raise ValueError("strategy_name is required")
        # Preserve selection order while de-duplicating.
        wanted = list(dict.fromkeys(n for n in (factor_names or []) if n))
        if not wanted:
            raise ValueError("No factors selected.")

        rows = {row.get("factor_name"): row for row in self.context.factor().list_factors()}
        formulas: list[str] = []
        missing: list[str] = []
        factor_assets: list[dict[str, Any]] = []
        for n in wanted:
            row = rows.get(n)
            if row is None:
                missing.append(n)
                continue
            if row.get("metadata_integrity", True) is not True:
                raise ValueError(f"Factor research metadata failed integrity check: {n}")
            expression = str(row.get("factor_expression") or "").strip()
            if not expression:
                raise ValueError(f"Factor has no expression: {n}")
            formulas.append(expression)
            factor_assets.append(
                {
                    "factor_name": n,
                    "factor_expression_sha256": hashlib.sha256(
                        expression.encode("utf-8")
                    ).hexdigest(),
                    "metadata_sha256": str(row.get("metadata_sha256") or ""),
                    "metadata": dict(row.get("metadata") or {}),
                }
            )
        if missing:
            raise ValueError(f"Factors not found in library: {missing}")

        model_label = (model_name or "").strip()
        metadata: dict[str, Any] = {
            "source": "factor_library",
            "factor_names": wanted,
            "factor_assets": factor_assets,
            "factor_formula_hash": self._json_sha256(formulas),
            "factor_asset_fingerprint": self._json_sha256(factor_assets),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        research_metadata = [item["metadata"] for item in factor_assets]

        def unique_values(key: str) -> list[Any]:
            values = [item.get(key) for item in research_metadata]
            return list(
                {
                    json.dumps(value, ensure_ascii=False, sort_keys=True, default=str): value
                    for value in values
                    if value not in (None, "", {}, [])
                }.values()
            )

        factor_markets = [str(value) for value in unique_values("market")]
        requested_market = str(market or "").strip()
        if len(factor_markets) > 1:
            raise ValueError(f"Selected factors use different markets: {factor_markets}")
        if requested_market and factor_markets and requested_market != factor_markets[0]:
            raise ValueError("Requested market does not match selected factor metadata")
        resolved_market = requested_market or (factor_markets[0] if factor_markets else "")
        if resolved_market:
            metadata["market"] = resolved_market

        for key in ("provider_uri", "factor_data_fingerprint"):
            values = [str(value) for value in unique_values(key)]
            if len(values) > 1:
                raise ValueError(f"Selected factors use different {key} values")
            if values:
                metadata[key] = values[0]

        metadata["hypotheses"] = unique_values("hypothesis")
        metadata["mining_rounds"] = unique_values("mining_round")
        metadata["random_seeds"] = unique_values("seed")
        metadata["source_data_splits"] = unique_values("data_split")
        metadata["source_model_fingerprints"] = unique_values("model_fingerprint")
        metadata["source_template_fingerprints"] = unique_values(
            "qlib_template_fingerprint"
        )
        if yaml_params:
            frozen_yaml = dict(yaml_params)
            yaml_market = str(frozen_yaml.get("market") or "").strip()
            if yaml_market and resolved_market and yaml_market != resolved_market:
                raise ValueError("yaml_params.market does not match selected factors")
            if resolved_market:
                frozen_yaml["market"] = resolved_market
            yaml_provider = str(frozen_yaml.get("provider_uri") or "").strip()
            bound_provider = str(metadata.get("provider_uri") or "").strip()
            if yaml_provider and bound_provider:
                from alphapilot.research.execution import resource_path
                if resource_path(yaml_provider) != resource_path(bound_provider):
                    raise ValueError(
                        "yaml_params.provider_uri does not match selected factors"
                    )
            if bound_provider:
                frozen_yaml["provider_uri"] = bound_provider
            metadata["yaml_params"] = frozen_yaml
            metadata["data_split"] = {
                key: frozen_yaml[key]
                for key in (
                    "train_start",
                    "train_end",
                    "valid_start",
                    "valid_end",
                    "test_start",
                    "test_end",
                    "backtest_start",
                    "backtest_end",
                    "label_expression",
                )
                if key in frozen_yaml
            }
            metadata["qlib_template_fingerprint"] = str(
                frozen_yaml.get("qlib_template_fingerprint") or ""
            )

        record = StrategyRecord(
            strategy_name=name,
            factor_formulas=formulas,
            model=StrategyModelSpec(model_name=model_label) if model_label and model_label != "none" else None,
            metadata=metadata,
        )
        self.register_strategy(record)
        return record

    def get_strategy(self, strategy_name: str) -> StrategyRecord | None:
        return self._param_db.load_record(strategy_name)

    def list_strategy_records(self) -> list[StrategyRecord]:
        records: list[StrategyRecord] = []
        for name in self._param_db.list_strategies():
            rec = self._param_db.load_record(name)
            if rec is not None:
                records.append(rec)
        return records

    @guarded("strategy", "write")
    def delete_strategy(self, strategy_name: str) -> bool:
        return self._param_db.delete_strategy(strategy_name.strip())

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

    def _export_retest_portfolio_artifacts(
        self,
        record: StrategyRecord,
        out: StrategyBacktestOutcome,
        timestamp: str,
    ) -> None:
        if not out.workspace_path:
            return
        bundle_dir = self._param_db.retest_bundle_dir(record.strategy_name, timestamp, out.mode)
        if bundle_dir is None:
            return
        try:
            from alphapilot.systems.backtest.portfolio_artifacts import export_portfolio_to_dir

            files = export_portfolio_to_dir(out.workspace_path, bundle_dir)
            strategy_dir = self._param_db.strategy_dir(record.strategy_name)
            if strategy_dir is not None:
                out.details["artifacts_dir"] = str(bundle_dir.relative_to(strategy_dir))
            out.details["artifact_files"] = files
        except Exception as exc:
            out.details["artifact_export_error"] = str(exc)
            logger.warning(
                f"[strategy_backtest] portfolio export failed for {record.strategy_name} "
                f"mode={out.mode}: {exc}"
            )

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

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _json_sha256(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _register_retrained_asset(
        self,
        *,
        source_record: StrategyRecord,
        request: StrategyBacktestRequest,
        run: Any,
        metrics: StrategyMetrics | None,
        qlib_config_name: str | None,
        qlib_template_dir: str | Path | None,
        yaml_params: dict[str, Any] | None,
    ) -> StrategyRecord:
        """Freeze a successful retrain workspace into a new deployable asset."""

        target_name = str(request.save_as or "").strip()
        if not target_name:
            raise ValueError("save_as must be a non-empty strategy name")
        if self.get_strategy(target_name) is not None:
            raise ValueError(f"Strategy asset already exists: {target_name}")
        workspace_value = getattr(run, "workspace_path", None)
        if not workspace_value:
            raise ValueError("successful retrain did not expose a workspace")
        workspace = Path(workspace_value).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"retrain workspace is missing: {workspace}")

        experiment = run.result.experiment
        from alphapilot.systems.backtest.qlib_config import resolve_qlib_config_name
        from alphapilot.systems.backtest.scoring_model_export import (
            export_scoring_model_artifacts,
        )

        resolved_config = resolve_qlib_config_name(experiment, qlib_config_name)
        artifact_dir = export_scoring_model_artifacts(workspace, resolved_config)
        model_path = artifact_dir / "fitted_model.pkl"
        if not model_path.is_file():
            raise ValueError("retrain completed without a fitted_model.pkl artifact")

        factor_ctx = getattr(experiment, "factor_data_context", None)
        provider_uri = str(
            Path(
                request.qlib_data_dir
                or getattr(getattr(factor_ctx, "spec", None), "qlib_dir", "")
                or (source_record.metadata or {}).get("provider_uri")
                or self.context.config.data.qlib_data_dir
            ).expanduser().resolve()
        )
        market = str(
            getattr(getattr(factor_ctx, "spec", None), "market", "")
            or (source_record.metadata or {}).get("market")
            or ""
        ).strip()
        if not market:
            raise ValueError("retrained strategy has no bound market")

        factor_fingerprint = str(getattr(factor_ctx, "fingerprint", "") or "")
        if not factor_fingerprint:
            from alphapilot.systems.data.factor_h5 import FactorDataSpec

            factor_fingerprint = FactorDataSpec(
                qlib_dir=Path(provider_uri),
                market=market,
            ).fingerprint()

        frozen_yaml = dict(yaml_params or {})
        for key, expected in (("market", market), ("provider_uri", provider_uri)):
            supplied = frozen_yaml.get(key)
            if supplied and str(Path(supplied).expanduser().resolve() if key == "provider_uri" else supplied) != expected:
                raise ValueError(f"yaml_params.{key} does not match the trained data context")
            frozen_yaml[key] = expected

        model_config_path = artifact_dir / "model_config.json"
        fitted_state_path = artifact_dir / "fitted_training_state.json"
        model_config = (
            json.loads(model_config_path.read_text(encoding="utf-8"))
            if model_config_path.is_file()
            else {}
        )
        fitted_state = (
            json.loads(fitted_state_path.read_text(encoding="utf-8"))
            if fitted_state_path.is_file()
            else {}
        )
        config_path = workspace / resolved_config
        config_hash = self._file_sha256(config_path) if config_path.is_file() else ""
        model_hash = self._file_sha256(model_path)
        factor_hash = self._json_sha256(source_record.factor_formulas)
        metadata = {
            **dict(source_record.metadata or {}),
            "source": "strategy_retrain",
            "parent_strategy": source_record.strategy_name,
            "created_at": datetime.now().astimezone().isoformat(),
            "market": market,
            "provider_uri": provider_uri,
            "factor_data_fingerprint": factor_fingerprint,
            "factor_data_freq": str(
                getattr(getattr(factor_ctx, "spec", None), "freq", "day")
            ),
            "factor_data_start_date": str(
                getattr(
                    getattr(factor_ctx, "spec", None),
                    "start_date",
                    "2015-01-01",
                )
            ),
            "factor_formula_hash": factor_hash,
            "model_hash": model_hash,
            "qlib_config_name": resolved_config,
            "qlib_config_fingerprint": config_hash,
            "qlib_template_dir": str(qlib_template_dir) if qlib_template_dir else None,
            "qlib_template_source_dir": str(workspace),
            "yaml_params": frozen_yaml,
            "run_tag": request.run_tag,
        }
        saved = StrategyRecord(
            strategy_name=target_name,
            factor_formulas=list(source_record.factor_formulas),
            model=StrategyModelSpec(
                model_name=(
                    source_record.model.model_name
                    if source_record.model and source_record.model.model_name
                    else "lightgbm"
                ),
                hyper_params=model_config,
                trained_artifact_uri=str(model_path),
                fitted_params=fitted_state,
            ),
            metrics=metrics,
            metadata=metadata,
        )
        self.register_strategy(saved)
        persisted = self.get_strategy(target_name)
        if persisted is None or not persisted.model or not persisted.model.trained_artifact_uri:
            raise RuntimeError("saved retrained strategy could not be reloaded")
        return persisted

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
        # Record the factor data context active during training (market + h5 fingerprint) so
        # daily signals can later bind to the same instrument universe / data snapshot. Read from
        # the experiment's context when present, else from the env published at task entry.
        base_metadata: dict[str, Any] = {"train_result_type": type(result).__name__}
        ctx = getattr(experiment, "factor_data_context", None)
        if ctx is not None:
            base_metadata["market"] = ctx.spec.market
            base_metadata["factor_data_fingerprint"] = ctx.fingerprint
        else:
            env_market = os.environ.get(ENV_MARKET)
            if env_market:
                base_metadata["market"] = env_market
                base_metadata["factor_data_fingerprint"] = os.environ.get(ENV_FINGERPRINT, "")
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
            metadata={**base_metadata, **(metadata or {})},
        )
        self.register_strategy(record)
        return record

    @guarded("strategy", "write")
    def backtest_from_asset(self, request: StrategyBacktestRequest) -> list[StrategyBacktestOutcome]:
        record = self.get_strategy(request.strategy_name)
        if record is None:
            raise ValueError(f"Strategy asset not found: {request.strategy_name}")

        mode = request.mode.lower()
        if mode not in {"retrain", "reuse_model"}:
            raise ValueError(f"Unsupported mode: {request.mode}")
        if request.save_as:
            request.save_as = request.save_as.strip()
            if mode != "retrain":
                raise ValueError("save_as is only valid with mode=retrain")
            if not request.save_as:
                raise ValueError("save_as must be a non-empty strategy name")
            if self.get_strategy(request.save_as) is not None:
                raise ValueError(f"Strategy asset already exists: {request.save_as}")
        modes = [mode]

        factors = self._factors_to_defs(record.factor_formulas)
        # Optional per-run yaml_params override (money / rebalance strategy / costs / dates),
        # passed through options. Accept a dict (Portal) or a JSON string (CLI --options).
        yaml_params = request.options.get("yaml_params") if request.options else None
        if isinstance(yaml_params, str) and yaml_params.strip():
            import json

            yaml_params = json.loads(yaml_params)
        # Fall back to the rebalance / cost / date overrides saved with the strategy asset
        # (e.g. strategies created from the factor library) when the request omits them.
        if yaml_params is None:
            yaml_params = (record.metadata or {}).get("yaml_params")
        qlib_config_name = request.qlib_config_name or (record.metadata or {}).get("qlib_config_name")
        qlib_template_dir = remap_legacy_relative_path(
            request.qlib_template_dir or (record.metadata or {}).get("qlib_template_dir")
        )
        # Re-test on the same instrument universe the strategy was trained on.
        asset_market = (record.metadata or {}).get("market")
        use_local = (
            request.use_local
            if request.use_local is not None
            else self.context.config.backtest.use_local
        )
        outcomes: list[StrategyBacktestOutcome] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for m in modes:
            try:
                logger.info(
                    f"[strategy_backtest] {m} strategy={record.strategy_name} "
                    f"factors={len(factors)} python={resolve_factor_python_bin()} "
                    f"qlib_config={qlib_config_name} qlib_template_dir={qlib_template_dir}"
                )
                model_uri = None
                if m == "reuse_model":
                    model_uri = record.model.trained_artifact_uri if record.model else None
                    if not model_uri:
                        raise ValueError(
                            f"Strategy {record.strategy_name} has no trained_artifact_uri for reuse_model mode."
                        )
                old_qlib_data_dir = os.environ.get("ALPHAPILOT_QLIB_DATA_DIR")
                if request.qlib_data_dir:
                    os.environ["ALPHAPILOT_QLIB_DATA_DIR"] = str(request.qlib_data_dir)
                try:
                    run = run_strategy_asset_backtest(
                        self.context,
                        mode=m,
                        factors=factors,
                        scenario=request.scenario,
                        qlib_config_name=qlib_config_name,
                        qlib_template_dir=qlib_template_dir,
                        qlib_data_dir=request.qlib_data_dir,
                        use_local=use_local,
                        model_pickle_path=model_uri,
                        market=asset_market,
                        yaml_params=yaml_params,
                    )
                finally:
                    if request.qlib_data_dir:
                        if old_qlib_data_dir is None:
                            os.environ.pop("ALPHAPILOT_QLIB_DATA_DIR", None)
                        else:
                            os.environ["ALPHAPILOT_QLIB_DATA_DIR"] = old_qlib_data_dir
                metrics = self._extract_metrics(run.result.experiment)
                details: dict[str, Any] = {
                    "qlib_config_name": qlib_config_name,
                    "qlib_template_dir": qlib_template_dir,
                    "factor_python": resolve_factor_python_bin(),
                    "qlib_data_dir": request.qlib_data_dir,
                    "run_tag": request.run_tag,
                }
                if m == "reuse_model" and model_uri:
                    details["model_pickle_path"] = model_uri
                    details["note"] = (
                        "Loads strategy_zoo fitted_model.pkl via PretrainedLGBModel; "
                        "skips qrun training while still running signal and portfolio backtest."
                    )
                out = StrategyBacktestOutcome(
                    strategy_name=record.strategy_name,
                    mode=m,
                    metrics=self._metrics_to_dict(metrics),
                    workspace_path=run.workspace_path,
                    details=details,
                )
                if request.save_as:
                    saved = self._register_retrained_asset(
                        source_record=record,
                        request=request,
                        run=run,
                        metrics=metrics,
                        qlib_config_name=qlib_config_name,
                        qlib_template_dir=qlib_template_dir,
                        yaml_params=yaml_params if isinstance(yaml_params, dict) else None,
                    )
                    out.details.update(
                        {
                            "saved_strategy_name": saved.strategy_name,
                            "model_hash": (saved.metadata or {}).get("model_hash"),
                            "factor_hash": (saved.metadata or {}).get("factor_formula_hash"),
                            "factor_data_fingerprint": (saved.metadata or {}).get(
                                "factor_data_fingerprint"
                            ),
                            "qlib_config_fingerprint": (saved.metadata or {}).get(
                                "qlib_config_fingerprint"
                            ),
                        }
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

            self._export_retest_portfolio_artifacts(record, out, timestamp)
            outcomes.append(out)
            self._param_db.append_retest(
                record.strategy_name,
                {
                    "timestamp": timestamp,
                    "mode": out.mode,
                    "strategy_name": out.strategy_name,
                    "metrics": out.metrics,
                    "workspace_path": out.workspace_path,
                    "details": out.details,
                },
            )
        if request.save_as:
            error = outcomes[0].details.get("error") if outcomes else "no outcome"
            if error:
                raise RuntimeError(f"retrain save_as failed: {error}")
        return outcomes

    @property
    def param_database(self) -> Any:
        return self._param_db
