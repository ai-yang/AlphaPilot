"""
Model workflow with session control
It is from `rdagent/modules/alpha_mining/model.py` and try to replace `rdagent/modules/alpha_mining/RDAgent.py`
"""

import time
import pandas as pd
import json
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
        if STOP_EVENT is not None and STOP_EVENT.is_set():
            # 当收到停止信号时，可以直接抛出异常或返回特定值，这里示例抛出异常
            raise Exception("Operation stopped due to stop_event flag.")
        return func(self, *args, **kwargs)
    return wrapper


class AlphaPilotLoop(LoopBase, metaclass=LoopMeta):
    skip_loop_error = (FactorEmptyError,)
    
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
    ):
        with logger.tag("init"):
            self.context = context
            self.use_local = use_local
            self.potential_direction = potential_direction
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
            
            global STOP_EVENT
            STOP_EVENT = stop_event
            super().__init__()

    @classmethod
    def load(cls, path, use_local: bool = True):
        """加载现有会话"""
        instance = super().load(path)
        instance.use_local = use_local
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
        self._save_strategy_asset(prev_out)

    def _save_strategy_asset(self, prev_out: dict[str, Any]) -> None:
        """
        Persist round-level factor/model/metrics as a strategy asset package.
        Failures should not break the mining workflow.
        """
        if self.context is None:
            return
        try:
            from alphapilot.systems.strategy import StrategyMetrics, StrategyModelSpec, StrategyRecord

            round_no = self.loop_idx + 1
            result = prev_out.get("factor_backtest")
            if result is None:
                return

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
                    "round_no": round_no,
                    "hypothesis": getattr(prev_out.get("factor_propose"), "hypothesis", None),
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
        except Exception as e:
            logger.warning(f"[strategy.save] round asset save failed: {e}")


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


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
