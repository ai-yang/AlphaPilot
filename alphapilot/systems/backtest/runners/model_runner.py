"""Qlib model runner for the backtest system layer."""

from __future__ import annotations

from typing import Any

from alphapilot.components.runner import CachedRunner
from alphapilot.core.exception import ModelEmptyError
from alphapilot.core.utils import cache_with_pickle


class QlibModelRunner(CachedRunner[Any]):
    """Model runner that injects model code then executes qlib."""

    @cache_with_pickle(CachedRunner.get_cache_key, CachedRunner.assign_cached_result)
    def develop(
        self,
        exp: Any,
        *,
        use_local: bool = True,
        run_env: dict[str, str] | None = None,
    ) -> Any:
        if exp.sub_workspace_list[0].code_dict.get("model.py") is None:
            raise ModelEmptyError("model.py is empty")

        exp.experiment_workspace.inject_code(**{"model.py": exp.sub_workspace_list[0].code_dict["model.py"]})

        env_to_use = {"PYTHONPATH": "./"}
        if run_env:
            env_to_use.update(run_env)
        if exp.sub_tasks[0].model_type == "TimeSeries":
            env_to_use.update({"dataset_cls": "TSDatasetH", "step_len": 20, "num_timesteps": 20})
        elif exp.sub_tasks[0].model_type == "Tabular":
            env_to_use.update({"dataset_cls": "DatasetH"})

        result = exp.experiment_workspace.execute(
            qlib_config_name="conf.yaml",
            run_env=env_to_use,
            use_local=use_local,
        )
        exp.result = result
        return exp
