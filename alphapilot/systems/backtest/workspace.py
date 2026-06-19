"""Qlib workspace execution helper owned by the backtest system layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.core.experiment import FBWorkspace
from alphapilot.log import logger
from alphapilot.utils.env import QTDockerEnv


class QlibFBWorkspace(FBWorkspace):
    """File-based workspace that runs ``qrun`` and reads qlib outputs."""

    def __init__(self, template_folder_path: Path, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.inject_code_from_folder(template_folder_path)

    def execute(
        self,
        qlib_config_name: str = "conf.yaml",
        run_env: dict[str, Any] | None = None,
        use_local: bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        run_env = run_env or {}

        qtde = QTDockerEnv(is_local=use_local)
        qtde.prepare()

        logger.info(
            f"Execute {'Local' if use_local else 'Docker container'} Backtest: qrun {qlib_config_name}"
        )
        qtde.run(
            local_path=str(self.workspace_path),
            entry=f"qrun {qlib_config_name}",
            env=run_env,
        )

        logger.info(f"Read {'Local' if use_local else 'Docker container'} Backtest Result")
        qtde.run(
            local_path=str(self.workspace_path),
            entry="python read_exp_res.py",
            env=run_env,
        )

        ret_path = self.workspace_path / "ret.pkl"
        if not ret_path.exists():
            logger.error(f"File {ret_path} does not exist (qrun likely failed).")
            return None
        ret_df = pd.read_pickle(ret_path)
        logger.log_object(ret_df, tag="Quantitative Backtesting Chart")

        csv_path = self.workspace_path / "qlib_res.csv"
        if not csv_path.exists():
            logger.error(f"File {csv_path} does not exist.")
            return None

        try:
            from alphapilot.systems.backtest.scoring_model_export import export_scoring_model_artifacts

            export_scoring_model_artifacts(self.workspace_path, qlib_config_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Scoring model artifact export failed (backtest result kept): {exc}")

        return pd.read_csv(csv_path, index_col=0).iloc[:, 0]
