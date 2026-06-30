"""Qlib factor runner for the backtest system layer."""

from __future__ import annotations

import json
import os
import pickle
import shutil
from pathlib import Path
from typing import Any, Union

import pandas as pd

from alphapilot.components.runner import CachedRunner
from alphapilot.core.conf import RD_AGENT_SETTINGS
from alphapilot.core.exception import FactorEmptyError
from alphapilot.core.utils import cache_with_pickle, md5_hash, multiprocessing_wrapper
from alphapilot.log import logger
from alphapilot.systems.backtest.protocols import FactorBacktestCapable
from alphapilot.systems.backtest.qlib_config import resolve_qlib_config_name
from alphapilot.systems.backtest.qlib_pretrained import (
    PRETRAINED_ENV_VAR,
    patch_qlib_conf_for_pretrained,
)
from alphapilot.systems.data.factor_h5 import ENV_FINGERPRINT, ENV_MARKET
from alphapilot.systems.data.frequency import FREQUENCIES, portfolio_artifact_names


def _factor_data_cache_parts(exp: Any) -> list[str]:
    """Factor-data fingerprint pieces for the cache key (context object or env fallback)."""
    ctx = getattr(exp, "factor_data_context", None)
    if ctx is not None:
        return [
            f"factor_data_fingerprint:{ctx.fingerprint}",
            f"market:{ctx.spec.market}",
            f"qlib_dir:{ctx.spec.qlib_dir}",
        ]
    fingerprint = os.environ.get(ENV_FINGERPRINT)
    if fingerprint:
        return [
            f"factor_data_fingerprint:{fingerprint}",
            f"market:{os.environ.get(ENV_MARKET, '')}",
        ]
    return []


def _portfolio_artifact_names() -> tuple[str, ...]:
    """Workspace artifacts to sync between cached runs.

    The qlib PortAnaRecord positions/indicators filenames carry the rebalance freq
    tag (``1day`` for daily, ``5min`` ... for intraday), so include every supported
    frequency variant — only files that actually exist are copied.
    """
    names = ["ret.pkl", "qlib_res.csv", "combined_factors_df.pkl"]
    for freq in FREQUENCIES:
        artifacts = portfolio_artifact_names(freq)
        names.extend([artifacts["positions"], artifacts["indicators"]])
    # Dedupe while preserving order (day-first).
    return tuple(dict.fromkeys(names))


_PORTFOLIO_ARTIFACT_NAMES = _portfolio_artifact_names()


def _coerce_yaml_params(yaml_params: Any) -> Any:
    """Return a ``QlibYamlParams`` from an instance or plain dict.

    A plain dict is treated as a *patch*: when it omits ``template_type`` we default it to
    ``combined`` (the LLM-factor norm). Otherwise ``model_validate`` defaults to ``baseline`` and
    would silently render the wrong qlib template for combined-factor runs.
    """
    from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams

    if isinstance(yaml_params, QlibYamlParams):
        return yaml_params
    if isinstance(yaml_params, dict) and "template_type" not in yaml_params:
        yaml_params = {"template_type": "combined", **yaml_params}
    return QlibYamlParams.model_validate(yaml_params)


def _yaml_params_fingerprint(yaml_params: Any) -> str:
    """Stable hash of the params so model/strategy/dataset changes bust the cache.

    Round-trips through ``model_validate(model_dump())`` first so an instance and an
    equivalent plain dict hash identically (pydantic does not coerce field *defaults*,
    only validated input, e.g. ``account`` int-vs-float), avoiding spurious cache misses.
    """
    params = _coerce_yaml_params(yaml_params)
    normalized = type(params).model_validate(params.model_dump())
    return md5_hash(json.dumps(normalized.model_dump(mode="json"), sort_keys=True, default=str))


def _render_yaml_params_to_workspace(yaml_params: Any, workspace_path: Path) -> str:
    """Render ``QlibYamlParams`` into the workspace yaml; return the config filename.

    ``template_type`` (baseline/combined) selects the filename explicitly, replacing the
    implicit ``based_experiments`` rule for the rendered path.
    """
    from alphapilot.systems.backtest.qlib_yaml.generator import render_yaml_text

    params = _coerce_yaml_params(yaml_params)
    config_name = (
        "conf.yaml" if params.template_type == "baseline" else "conf_cn_combined_kdd_ver.yaml"
    )
    rendered = render_yaml_text(params)
    (Path(workspace_path) / config_name).write_text(rendered, encoding="utf-8")
    logger.info(
        f"[factor_runner] rendered qlib yaml from QlibYamlParams "
        f"(model={params.model_class}, strategy={params.strategy_class}) -> {config_name}"
    )
    return config_name


class QlibFactorRunner(CachedRunner[Any]):
    """Factor runner that prepares factor outputs then executes qlib."""

    @staticmethod
    def _sync_workspace_artifacts(src_ws: Path, dst_ws: Path) -> None:
        for name in _PORTFOLIO_ARTIFACT_NAMES:
            src = src_ws / name
            dst = dst_ws / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    def get_cache_key(self, exp: Any, **kwargs: Any) -> str:
        parts: list[str] = []
        for based_exp in exp.based_experiments:
            for task in based_exp.sub_tasks:
                parts.append(task.get_task_information())
        for task in exp.sub_tasks:
            parts.append(task.get_task_information())
        parts.append(f"qlib_config:{resolve_qlib_config_name(exp)}")
        parts.append(f"qlib_template_dir:{getattr(exp, 'qlib_template_dir', '') or ''}")
        parts.append(f"use_local:{kwargs.get('use_local', True)}")
        run_env = kwargs.get("run_env") or getattr(exp, "run_env", None) or {}
        pretrained = run_env.get(PRETRAINED_ENV_VAR, "")
        parts.append(f"pretrained:{pretrained}")
        yaml_params = getattr(exp, "yaml_params", None)
        if yaml_params is not None:
            parts.append(f"yaml_params:{_yaml_params_fingerprint(yaml_params)}")
        # Bind the result to the factor data universe so switching markets/instruments does not
        # reuse a stale combined_factors_df.pkl. Absent when no context/env (legacy behavior).
        parts.extend(_factor_data_cache_parts(exp))
        return md5_hash("\n---\n".join(parts))

    def assign_cached_result(self, exp: Any, cached_res: Any) -> Any:
        exp = super().assign_cached_result(exp, cached_res)
        src_ws = getattr(getattr(cached_res, "experiment_workspace", None), "workspace_path", None)
        dst_ws = getattr(getattr(exp, "experiment_workspace", None), "workspace_path", None)
        if src_ws is None or dst_ws is None:
            return exp
        src_ws, dst_ws = Path(src_ws), Path(dst_ws)
        if src_ws.resolve() != dst_ws.resolve():
            self._sync_workspace_artifacts(src_ws, dst_ws)
            logger.info(
                f"[factor_runner] synced portfolio artifacts from cached workspace {src_ws.name} -> {dst_ws.name}"
            )
        return exp

    @cache_with_pickle(CachedRunner.get_cache_key, CachedRunner.assign_cached_result)
    def develop(
        self,
        exp: Union[FactorBacktestCapable, Any],
        use_local: bool = True,
        run_env: dict[str, str] | None = None,
    ) -> Any:
        run_env = dict(run_env or getattr(exp, "run_env", None) or {})
        if run_env:
            exp.run_env = run_env

        if exp.based_experiments and exp.based_experiments[-1].result is None:
            based = exp.based_experiments[-1]
            if based.sub_tasks:
                exp.based_experiments[-1] = self.develop(
                    based, use_local=use_local, run_env=run_env
                )

        if exp.sub_tasks:
            new_factors = self.process_factor_data(exp)
            if new_factors.empty:
                raise FactorEmptyError("No valid factor data found to merge.")

            combined_factors = new_factors

            if len(combined_factors.columns) >= 2:
                pd.set_option("display.width", 1000)
                logger.info(f"Factor correlation: \n\n{combined_factors.corr()}\n")

            combined_factors = combined_factors.sort_index()
            combined_factors = combined_factors.loc[:, ~combined_factors.columns.duplicated(keep="last")]
            combined_factors.columns = pd.MultiIndex.from_product([["feature"], combined_factors.columns])

            logger.info(f"Factor values this round: \n\n{combined_factors.tail()}\n\n")
            with open(exp.experiment_workspace.workspace_path / "combined_factors_df.pkl", "wb") as f:
                pickle.dump(combined_factors, f)

        config_name = resolve_qlib_config_name(exp)
        exp.qlib_config_name = config_name
        workspace_path = Path(exp.experiment_workspace.workspace_path)
        yaml_params = getattr(exp, "yaml_params", None)
        if yaml_params is not None:
            config_name = _render_yaml_params_to_workspace(yaml_params, workspace_path)
            exp.qlib_config_name = config_name
        if run_env.get(PRETRAINED_ENV_VAR):
            patch_qlib_conf_for_pretrained(workspace_path, config_name)
            logger.info(
                f"Execute factor backtest with pretrained model "
                f"(Use {'Local' if use_local else 'Docker'}): {config_name}"
            )
        else:
            logger.info(
                f"Execute factor backtest (Use {'Local' if use_local else 'Docker container'}): {config_name}"
            )
        result = exp.experiment_workspace.execute(
            qlib_config_name=config_name,
            use_local=use_local,
            run_env=run_env,
        )
        logger.info(f"Backtesting results: \n{result.iloc[2:] if result is not None else 'None'}")
        exp.result = result

        round_no = getattr(exp, "mining_round", None)
        if round_no is not None and getattr(exp, "persist_scoring_model_log", False):
            from alphapilot.systems.backtest.scoring_model_export import (
                persist_qlib_template_to_log,
                persist_scoring_model_to_log,
            )

            ws_path = exp.experiment_workspace.workspace_path
            persist_scoring_model_to_log(
                logger.log_trace_path,
                int(round_no),
                ws_path,
                config_name,
            )
            persist_qlib_template_to_log(
                logger.log_trace_path,
                int(round_no),
                ws_path,
                config_name,
                template_dir=getattr(exp, "qlib_template_dir", None),
            )

        return exp

    def process_factor_data(self, exp_or_list: Any) -> pd.DataFrame:
        experiments = exp_or_list if isinstance(exp_or_list, list) else [exp_or_list]
        factor_dfs: list[pd.DataFrame] = []

        for exp in experiments:
            sub_workspaces = getattr(exp, "sub_workspace_list", None) or []
            # Propagate the data context to each factor workspace so its execute()/hash_func use
            # this task's h5 even under multiprocessing (pickled to spawned children).
            ctx = getattr(exp, "factor_data_context", None)
            if ctx is not None:
                for implementation in sub_workspaces:
                    implementation.factor_data_context = ctx
            message_and_df_list = multiprocessing_wrapper(
                [(implementation.execute, ("All",)) for implementation in sub_workspaces],
                n=RD_AGENT_SETTINGS.multi_proc_n,
            )
            for _message, df in message_and_df_list:
                if df is not None and "datetime" in df.index.names:
                    time_diff = df.index.get_level_values("datetime").to_series().diff().dropna().unique()
                    if pd.Timedelta(minutes=1) not in time_diff:
                        factor_dfs.append(df)

        if factor_dfs:
            return pd.concat(factor_dfs, axis=1)
        raise FactorEmptyError("No valid factor data found to merge.")
