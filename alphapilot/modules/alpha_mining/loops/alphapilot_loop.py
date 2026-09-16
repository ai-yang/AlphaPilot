from alphapilot.research.guards import guarded
"""
Model workflow with session control
It is from `rdagent/modules/alpha_mining/model.py` and try to replace `rdagent/modules/alpha_mining/RDAgent.py`
"""

import time
import pandas as pd
import json
import hashlib
import re
from typing import Any

from alphapilot.components.workflow.conf import BaseFacSetting
from alphapilot.core.developer import Developer
from alphapilot.core.proposal import (
    Hypothesis2Experiment,
    HypothesisExperiment2Feedback,
    HypothesisGen,  
    Trace,
)
from alphapilot.core.scenario import Scenario
from alphapilot.core.utils import import_class
from alphapilot.log import logger
from alphapilot.log.time import measure_time
from alphapilot.utils.workflow import LoopBase, LoopMeta
from alphapilot.core.exception import FactorEmptyError
from alphapilot.core.pickle_cache import pickle_cache_scope
import threading


import datetime
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tqdm.auto import tqdm

from alphapilot.core.exception import CoderError
from alphapilot.log import logger
from alphapilot.log.mine_paths import qlib_template_log_dir, scoring_model_log_dir
from functools import wraps

# 定义装饰器：在函数调用前检查stop_event

            
def stop_event_check(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        stop_event = getattr(self, "_stop_event", None)
        if stop_event is not None and stop_event.is_set():
            # 当收到停止信号时，可以直接抛出异常或返回特定值，这里示例抛出异常
            raise Exception("Operation stopped due to stop_event flag.")
        return func(self, *args, **kwargs)
    return wrapper


class AlphaPilotLoop(LoopBase, metaclass=LoopMeta):
    skip_loop_error = (FactorEmptyError,)

    def __getstate__(self) -> dict[str, Any]:
        """Exclude process-local services from workflow snapshots.

        ``Context`` retains the live ``MainEngine`` and all registered systems
        and modules.  That object graph contains locks, executors, and other
        process-local resources that cannot be pickled.  A resumed mining run
        rebinds the current context in ``AlphaMiningModule.run_mining``.
        """
        state = self.__dict__.copy()
        state["context"] = None
        state["_stop_event"] = None
        return state
    
    @measure_time
    def __init__(
        self,
        PROP_SETTING: BaseFacSetting,
        potential_direction,
        stop_event: threading.Event,
        use_local: bool = True,
        context: Any | None = None,
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
        yaml_params: Any = None,
        save_factors_to_library: bool = False,
        random_seed: int | None = None,
        campaign_id: str | None = None,
    ):
        with logger.tag("init"):
            self.context = context
            self.use_local = use_local
            self.potential_direction = potential_direction
            # Optional qlib-config override (money / rebalance / costs / dates) applied to the
            # in-loop factor evaluation; ``None`` keeps the template defaults.
            self.yaml_params = yaml_params
            # When True, each round's mined factors are also added to the factor library (zoo).
            self.save_factors_to_library = save_factors_to_library
            self.random_seed = random_seed
            self.campaign_id = campaign_id
            self.round_persistence: list[dict[str, Any]] = []
            self.qlib_config_name = qlib_config_name or getattr(PROP_SETTING, "qlib_config_name", None)
            self.qlib_template_dir = qlib_template_dir or getattr(PROP_SETTING, "qlib_template_dir", None)
            logger.info(f"初始化AlphaPilotLoop，使用{'本地环境' if use_local else 'Docker容器'}回测")
            scen_kwargs: dict[str, Any] = {"use_local": use_local}
            if self.qlib_template_dir:
                scen_kwargs["qlib_template_dir"] = self.qlib_template_dir
            scen: Scenario = import_class(PROP_SETTING.scen)(**scen_kwargs)
            logger.log_object(scen, tag="scenario")

            ### 换成基于初始hypo的，生成完整的hypo
            self.hypothesis_generator: HypothesisGen = import_class(PROP_SETTING.hypothesis_gen)(scen, potential_direction)
            logger.log_object(self.hypothesis_generator, tag="hypothesis generator")

            ### 换成一次生成10个因子
            self.factor_constructor: Hypothesis2Experiment = import_class(PROP_SETTING.hypothesis2experiment)()
            logger.log_object(self.factor_constructor, tag="experiment generation")

            ### 加入代码执行中的 Variables / Functions
            self.coder: Developer = import_class(PROP_SETTING.coder)(scen)
            logger.log_object(self.coder, tag="coder")

            self.summarizer: HypothesisExperiment2Feedback = import_class(PROP_SETTING.summarizer)(scen)
            logger.log_object(self.summarizer, tag="summarizer")
            self.trace = Trace(scen=scen)
            
            self._stop_event = stop_event
            super().__init__()

    @classmethod
    def load(cls, path, use_local: bool = True):
        """加载现有会话"""
        instance = super().load(path)
        instance.use_local = use_local
        instance._stop_event = None
        logger.info(f"加载AlphaPilotLoop，使用{'本地环境' if use_local else 'Docker容器'}回测")
        return instance

    @measure_time
    @stop_event_check
    def factor_propose(self, prev_out: dict[str, Any]):
        """
        提出作为构建因子的基础的假设
        """
        with logger.tag("r"):  
            idea = self.hypothesis_generator.gen(self.trace)
            logger.log_object(idea, tag="hypothesis generation")
        return idea

    @measure_time
    @stop_event_check
    def factor_construct(self, prev_out: dict[str, Any]):
        """
        基于假设构造多个不同的因子
        """
        with logger.tag("r"): 
            factor = self.factor_constructor.convert(prev_out["factor_propose"], self.trace)
            logger.log_object(factor.sub_tasks, tag="experiment generation")
        return factor

    @measure_time
    @stop_event_check
    def factor_calculate(self, prev_out: dict[str, Any]):
        """
        根据因子表达式计算过去的因子表（因子值）
        """
        with logger.tag("d"), pickle_cache_scope("mine"):
            factor = self.coder.develop(prev_out["factor_construct"])
            logger.log_object(factor.sub_workspace_list, tag="coder result")
        return factor
    

    @measure_time
    @stop_event_check
    def factor_backtest(self, prev_out: dict[str, Any]):
        """
        回测因子
        """
        with logger.tag("ef"):  # evaluate and feedback
            logger.info(f"Start factor backtest (Local: {self.use_local})")
            experiment = prev_out["factor_calculate"]
            experiment.mining_round = self.loop_idx + 1
            experiment.persist_scoring_model_log = True
            # Bind this run's factor data context so the runner's cache key and factor execution
            # use the right h5 universe (env already published in run_mining as a fallback).
            factor_data_ctx = getattr(self, "factor_data_context", None)
            if factor_data_ctx is not None:
                experiment.factor_data_context = factor_data_ctx
            if self.qlib_config_name:
                experiment.qlib_config_name = self.qlib_config_name
            # Apply the optional money/rebalance/cost override to this round's evaluation; the
            # runner renders it via ``getattr(exp, "yaml_params")`` (factor_runner.py).
            loop_yaml_params = getattr(self, "yaml_params", None)
            if loop_yaml_params is not None:
                experiment.yaml_params = loop_yaml_params
            if self.context is None:
                raise RuntimeError(
                    "factor_backtest requires a kernel Context; inject context when constructing the loop."
                )
            from alphapilot.systems.backtest.types import (
                FactorExperimentBacktestRequest,
            )

            with pickle_cache_scope("mine"):
                exp = self.context.backtest().run_factor_experiment(
                    FactorExperimentBacktestRequest(
                        experiment=experiment,
                        qlib_config_name=self.qlib_config_name,
                        use_local=self.use_local,
                        pickle_cache_scope="mine",
                    )
                )
            if exp is None:
                logger.error(f"Factor extraction failed.")
                raise FactorEmptyError("Factor extraction failed.")
            logger.log_object(exp, tag="runner result")
        return exp

    @measure_time
    @stop_event_check
    def feedback(self, prev_out: dict[str, Any]):
        feedback = self.summarizer.generate_feedback(prev_out["factor_backtest"], prev_out["factor_propose"], self.trace)
        with logger.tag("ef"):  # evaluate and feedback
            logger.log_object(feedback, tag="feedback")
        self.trace.hist.append((prev_out["factor_propose"], prev_out["factor_backtest"], feedback))
        strategy_status = self._save_strategy_asset(prev_out)
        factor_status: dict[str, Any] = {
            "saved": 0,
            "candidates": 0,
            "error": "factor-library persistence was not requested",
        }
        if getattr(self, "save_factors_to_library", False):
            factor_status = self._save_factors_to_library(prev_out)
        persistence = getattr(self, "round_persistence", None)
        if not isinstance(persistence, list):
            persistence = []
            self.round_persistence = persistence
        persistence.append(
            {
                "round_no": self.loop_idx + 1,
                "strategy": strategy_status,
                "factors": factor_status,
            }
        )

    def _save_strategy_asset(self, prev_out: dict[str, Any]) -> dict[str, Any]:
        """
        Persist round-level factor/model/metrics as a strategy asset package.
        Failures should not break the mining workflow.
        """
        if self.context is None:
            return {"saved": False, "error": "kernel context is unavailable"}
        try:
            from alphapilot.systems.strategy import StrategyMetrics, StrategyModelSpec, StrategyRecord

            round_no = self.loop_idx + 1
            result = prev_out.get("factor_backtest")
            if result is None:
                return {"saved": False, "error": "factor backtest result is unavailable"}

            factor_formulas: list[str] = []
            for task in getattr(result, "sub_tasks", []) or []:
                expr = getattr(task, "factor_expression", None)
                if expr:
                    factor_formulas.append(str(expr))

            metrics_raw = getattr(result, "result", None)
            if hasattr(metrics_raw, "to_dict"):
                metrics_raw = metrics_raw.to_dict()
            metrics = None
            if isinstance(metrics_raw, dict):
                metrics = StrategyMetrics(
                    ic=_to_float(metrics_raw.get("IC", metrics_raw.get("ic"))),
                    icir=_to_float(metrics_raw.get("ICIR", metrics_raw.get("information_ratio", metrics_raw.get("icir")))),
                    rank_ic=_to_float(metrics_raw.get("Rank IC", metrics_raw.get("rank_ic", metrics_raw.get("rankIC")))),
                    rank_icir=_to_float(metrics_raw.get("Rank ICIR", metrics_raw.get("rank_icir", metrics_raw.get("rankICIR")))),
                    extra={k: v for k, v in metrics_raw.items()},
                )

            model_artifact_uri = None
            fitted_params: dict[str, Any] = {}
            model_params: dict[str, Any] = {}
            model_dir = scoring_model_log_dir(logger.log_trace_path, round_no)
            artifact = model_dir / "fitted_model.pkl"
            if artifact.exists():
                model_artifact_uri = str(artifact)
            fit_state = model_dir / "fitted_training_state.json"
            if fit_state.exists():
                with fit_state.open("r", encoding="utf-8") as f:
                    fitted_params = json.load(f)
            model_cfg = model_dir / "model_config.json"
            if model_cfg.exists():
                with model_cfg.open("r", encoding="utf-8") as f:
                    model_params = json.load(f)

            record = StrategyRecord(
                strategy_name=build_mine_strategy_name(round_no, getattr(self, "potential_direction", None)),
                factor_formulas=factor_formulas,
                model=StrategyModelSpec(
                    model_name="lightgbm",
                    hyper_params=model_params,
                    trained_artifact_uri=model_artifact_uri,
                    fitted_params=fitted_params,
                ),
                metrics=metrics,
                metadata={
                    "source": "mine",
                    "campaign_id": getattr(self, "campaign_id", None),
                    "round_no": round_no,
                    "random_seed": getattr(self, "random_seed", None),
                    "hypothesis": getattr(prev_out.get("factor_propose"), "hypothesis", None),
                    "mining_direction": getattr(self, "potential_direction", None),
                    "market": (
                        getattr(
                            getattr(getattr(self, "factor_data_context", None), "spec", None),
                            "market",
                            None,
                        )
                    ),
                    "provider_uri": str(
                        getattr(
                            getattr(getattr(self, "factor_data_context", None), "spec", None),
                            "qlib_dir",
                            "",
                        )
                    ),
                    "factor_data_fingerprint": getattr(
                        getattr(self, "factor_data_context", None), "fingerprint", ""
                    ),
                    "factor_data_freq": getattr(
                        getattr(getattr(self, "factor_data_context", None), "spec", None),
                        "freq",
                        "day",
                    ),
                    "factor_data_start_date": getattr(
                        getattr(getattr(self, "factor_data_context", None), "spec", None),
                        "start_date",
                        "2015-01-01",
                    ),
                    "yaml_params": getattr(self, "yaml_params", None) or {},
                    "data_split": _data_split_metadata(getattr(self, "yaml_params", None)),
                    "factor_formula_hash": _json_sha256(factor_formulas),
                    "model_hash": _file_sha256(artifact) if artifact.exists() else "",
                    "qlib_template_fingerprint": _tree_sha256(
                        qlib_template_log_dir(logger.log_trace_path, round_no)
                    ),
                    "qlib_config_name": getattr(result, "qlib_config_name", None) or self.qlib_config_name,
                    "qlib_template_dir": getattr(result, "qlib_template_dir", None) or self.qlib_template_dir,
                    "qlib_template_source_dir": str(qlib_template_log_dir(logger.log_trace_path, round_no)),
                },
            )
            self.context.strategy().register_strategy(record)
            logger.info(
                f"[strategy.save] name={record.strategy_name} "
                f"factors={len(record.factor_formulas)} "
                f"model={record.model.model_name if record.model else None} "
                f"ic={record.metrics.ic if record.metrics else None} "
                f"icir={record.metrics.icir if record.metrics else None} "
                f"artifact={record.model.trained_artifact_uri if record.model else None}"
            )
            return {
                "saved": True,
                "strategy_name": record.strategy_name,
                "factor_count": len(record.factor_formulas),
                "model_path": model_artifact_uri or "",
                "model_hash": _file_sha256(artifact) if artifact.exists() else "",
                "qlib_template_fingerprint": _tree_sha256(
                    qlib_template_log_dir(logger.log_trace_path, round_no)
                ),
                "factor_data_fingerprint": getattr(
                    getattr(self, "factor_data_context", None), "fingerprint", ""
                ),
                "error": "",
            }
        except Exception as e:
            logger.warning(f"[strategy.save] round asset save failed: {e}")
            return {"saved": False, "error": f"{type(e).__name__}: {e}"}

    @guarded("factor", "write")
    def _save_factors_to_library(self, prev_out: dict[str, Any]) -> dict[str, Any]:
        """Add this round's mined factor expressions to the factor library (zoo).

        Reuses ``factor().add_factor`` (validates + dedups by name/expression). A name clash with a
        *different* expression is retried with a round suffix. Failures are non-fatal.
        """
        if self.context is None:
            return {
                "saved": 0,
                "candidates": 0,
                "error": "kernel context is unavailable",
            }
        try:
            from alphapilot.systems.factor.types import REJECT_DUPLICATE_NAME

            result = prev_out.get("factor_backtest")
            if result is None:
                return {
                    "saved": 0,
                    "candidates": 0,
                    "error": "factor backtest result is unavailable",
                }
            round_no = self.loop_idx + 1
            factor_system = self.context.factor()
            factor_system.database.reload()
            added = 0
            direction = getattr(self, "potential_direction", None)
            direction_slug = _keyword_slug(direction, max_len=24)
            campaign_slug = _keyword_slug(
                getattr(self, "campaign_id", None), max_len=24
            )
            factor_data_ctx = getattr(self, "factor_data_context", None)
            factor_data_spec = getattr(factor_data_ctx, "spec", None)
            hypothesis = getattr(prev_out.get("factor_propose"), "hypothesis", None)
            model_dir = scoring_model_log_dir(logger.log_trace_path, round_no)
            model_artifact = model_dir / "fitted_model.pkl"
            template_dir = qlib_template_log_dir(logger.log_trace_path, round_no)
            base_metadata = {
                "source": "llm_mining",
                "campaign_id": getattr(self, "campaign_id", None),
                "market": getattr(factor_data_spec, "market", None),
                "provider_uri": str(getattr(factor_data_spec, "qlib_dir", "")),
                "factor_data_fingerprint": getattr(factor_data_ctx, "fingerprint", ""),
                "factor_data_freq": getattr(factor_data_spec, "freq", "day"),
                "data_split": _data_split_metadata(getattr(self, "yaml_params", None)),
                "hypothesis": hypothesis,
                "mining_direction": direction,
                "mining_round": round_no,
                "seed": getattr(self, "random_seed", None),
                "model_fingerprint": (
                    _file_sha256(model_artifact) if model_artifact.exists() else ""
                ),
                "qlib_template_fingerprint": _tree_sha256(template_dir),
                "yaml_params": getattr(self, "yaml_params", None) or {},
            }
            tasks = list(getattr(result, "sub_tasks", []) or [])
            candidates = 0
            for i, task in enumerate(tasks):
                expr = getattr(task, "factor_expression", None)
                if not expr:
                    continue
                candidates += 1
                original_name = str(
                    getattr(task, "factor_name", None) or f"factor_{i:02d}"
                )
                name = (
                    f"llm_{campaign_slug}_{direction_slug}_r{round_no:02d}_"
                    f"{_keyword_slug(original_name, max_len=32)}"
                )
                expression = str(expr)
                expression_hash = hashlib.sha256(expression.encode("utf-8")).hexdigest()
                try:
                    from alphapilot.components.coder.factor_coder.factor_ast import (
                        parse_expression,
                    )

                    factor_ast = str(parse_expression(expression))
                except Exception:  # noqa: BLE001 - factor system validation is authoritative
                    factor_ast = ""
                metadata = {
                    **base_metadata,
                    "original_factor_name": original_name,
                    "factor_ast": factor_ast,
                    "factor_expression_sha256": expression_hash,
                }
                metadata["asset_fingerprint"] = _json_sha256(metadata)
                categories = ["mined", "llm", f"llm:{direction_slug}"]
                res = factor_system.add_factor(
                    name,
                    expression,
                    categories=categories,
                    metadata=metadata,
                    save=False,
                )
                # Duplicate name with a different expression -> retry under a round-tagged name.
                if not res.acceptable and getattr(res, "code", None) == REJECT_DUPLICATE_NAME:
                    res = factor_system.add_factor(
                        f"{name}_{expression_hash[:8]}",
                        expression,
                        categories=categories,
                        metadata=metadata,
                        save=False,
                    )
                if res.acceptable:
                    added += 1
            if added:
                factor_system.database.save()
            logger.info(f"[factor.save] round {round_no}: added {added} factor(s) to the library")
            return {"saved": added, "candidates": candidates, "error": ""}
        except Exception as e:  # noqa: BLE001 — auto-save must never break mining
            logger.warning(f"[factor.save] round factor-library save failed: {e}")
            return {
                "saved": 0,
                "candidates": 0,
                "error": f"{type(e).__name__}: {e}",
            }


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    if not root.is_dir():
        return ""
    digest = hashlib.sha256(b"alphapilot-mining-template-v1\0")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _data_split_metadata(yaml_params: Any) -> dict[str, Any]:
    if not isinstance(yaml_params, dict):
        return {}
    keys = (
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
    return {key: yaml_params[key] for key in keys if key in yaml_params}


def _keyword_slug(keyword: str | None, max_len: int = 32) -> str:
    if not keyword:
        return "no_keyword"
    cleaned = re.sub(r"\s+", "_", keyword.strip())
    cleaned = re.sub(r"[^0-9a-zA-Z_\-\u4e00-\u9fff]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return "no_keyword"
    return cleaned[:max_len]


def build_mine_strategy_name(round_no: int, keyword: str | None) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"mine_round_{round_no:02d}_{ts}_{_keyword_slug(keyword)}"
