"""Qlib experiment shells (workspace + template binding).

LLM scenarios and prompts remain under ``modules.alpha_mining.qlib.experiment``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alphapilot.components.coder.factor_coder.factor import (
    FactorExperiment,
    FactorFBWorkspace,
    FactorTask,
)
from alphapilot.components.coder.model_coder.model import (
    ModelExperiment,
    ModelFBWorkspace,
    ModelTask,
)
from alphapilot.systems.backtest.qlib.template_paths import (
    DEFAULT_QLIB_MODEL_TEMPLATE_DIR,
    resolve_qlib_template_dir,
)
from alphapilot.systems.backtest.workspace import QlibFBWorkspace


class QlibFactorExperiment(FactorExperiment[FactorTask, QlibFBWorkspace, FactorFBWorkspace]):
    """Factor experiment with a qlib ``qrun`` workspace."""

    def __init__(
        self,
        *args: Any,
        template_folder_path: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        tpl = resolve_qlib_template_dir(template_folder_path)
        self.qlib_template_dir = str(tpl)
        self.experiment_workspace = QlibFBWorkspace(template_folder_path=tpl)


class QlibModelExperiment(ModelExperiment[ModelTask, QlibFBWorkspace, ModelFBWorkspace]):
    """Model experiment with a qlib ``qrun`` workspace."""

    def __init__(
        self,
        *args: Any,
        template_folder_path: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        tpl = resolve_qlib_template_dir(
            template_folder_path,
            default=DEFAULT_QLIB_MODEL_TEMPLATE_DIR,
        )
        self.experiment_workspace = QlibFBWorkspace(template_folder_path=tpl)
