"""Load user factor definitions into a qlib factor experiment."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from alphapilot.components.coder.factor_coder.factor import FactorTask
from alphapilot.systems.backtest.qlib.experiment import QlibFactorExperiment
from alphapilot.systems.backtest.qlib.template_paths import resolve_qlib_template_dir


def build_factor_experiment_from_csv(
    factor_path: str | Path,
    *,
    qlib_template_dir: str | Path | None = None,
) -> QlibFactorExperiment:
    """Parse a factor CSV and return a :class:`QlibFactorExperiment` ready for calculation."""
    path = Path(factor_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Factor CSV not found: {path}")

    tpl = resolve_qlib_template_dir(qlib_template_dir)
    factor_df = pd.read_csv(path, usecols=["factor_name", "factor_expression"])
    tasks = [
        FactorTask(
            factor_name=row["factor_name"],
            factor_description="",
            factor_formulation="",
            factor_expression=row["factor_expression"],
            variables="",
        )
        for _, row in factor_df.iterrows()
    ]

    exp = QlibFactorExperiment(tasks, template_folder_path=tpl)
    exp.based_experiments = [QlibFactorExperiment(sub_tasks=[], template_folder_path=tpl)]

    unique_tasks: list[FactorTask] = []
    for task in tasks:
        duplicate = False
        for based_exp in exp.based_experiments:
            for sub_task in based_exp.sub_tasks:
                if task.factor_name == sub_task.factor_name:
                    duplicate = True
                    break
            if duplicate:
                break
        if not duplicate:
            unique_tasks.append(task)

    exp.tasks = unique_tasks
    return exp
