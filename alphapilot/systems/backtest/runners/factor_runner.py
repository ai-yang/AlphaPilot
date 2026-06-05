"""Qlib factor runner for the backtest system layer."""

from __future__ import annotations

import pickle
import shutil
from pathlib import Path
from typing import Any, Union

import pandas as pd
from pandarallel import pandarallel

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

pandarallel.initialize(verbose=1)


_PORTFOLIO_ARTIFACT_NAMES = (
    "ret.pkl",
    "qlib_res.csv",
    "positions_normal_1day.pkl",
    "indicators_normal_1day.pkl",
    "combined_factors_df.pkl",
)


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

    def calculate_information_coefficient(
        self,
        concat_feature: pd.DataFrame,
        sota_feature_column_size: int,
        new_feature_columns_size: int,
    ) -> pd.Series:
        res = pd.Series(index=range(sota_feature_column_size * new_feature_columns_size))
        for col1 in range(sota_feature_column_size):
            for col2 in range(sota_feature_column_size, sota_feature_column_size + new_feature_columns_size):
                res.loc[col1 * new_feature_columns_size + col2 - sota_feature_column_size] = concat_feature.iloc[
                    :, col1
                ].corr(concat_feature.iloc[:, col2])
        return res

    def deduplicate_new_factors(self, sota_feature: pd.DataFrame, new_feature: pd.DataFrame) -> pd.DataFrame:
        concat_feature = pd.concat([sota_feature, new_feature], axis=1)
        ic_max = (
            concat_feature.groupby("datetime")
            .parallel_apply(
                lambda x: self.calculate_information_coefficient(x, sota_feature.shape[1], new_feature.shape[1])
            )
            .mean()
        )
        ic_max.index = pd.MultiIndex.from_product([range(sota_feature.shape[1]), range(new_feature.shape[1])])
        ic_max = ic_max.unstack().max(axis=0)
        return new_feature.iloc[:, ic_max[ic_max < 0.99].index]

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
            sota_factor = None
            if exp.based_experiments and len(exp.based_experiments) > 1:
                sota_factor = self.process_factor_data(exp.based_experiments)

            new_factors = self.process_factor_data(exp)
            if new_factors.empty:
                raise FactorEmptyError("No valid factor data found to merge.")

            if False:  # sota_factor is not None and not sota_factor.empty:
                new_factors = self.deduplicate_new_factors(sota_factor, new_factors)
                if new_factors.empty:
                    raise FactorEmptyError("No valid factor data found to merge.")
                combined_factors = pd.concat([sota_factor, new_factors], axis=1).dropna()
            else:
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
