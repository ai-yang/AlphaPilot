"""Default model management system.

Wraps the existing model task loader and the qlib model runner, and adds
a centralized model parameter database. Training is delegated to the
backtest system so model and factor share one execution backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphapilot.systems.model.base import BaseModelSystem
from alphapilot.systems.model.database import build_model_param_database

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class ModelSystem(BaseModelSystem):
    """Model import + param database + training."""

    def setup(self, context: "Context") -> None:
        self.context = context
        cfg = context.config.model
        self._param_db = build_model_param_database(cfg.database_backend, cfg.param_dir)

    def import_model(self, source: Any, *, kind: str = "pdf") -> Any:
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
        raise ValueError(f"Unsupported model import kind: {kind!r}")

    def train(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        from alphapilot.systems.backtest.types import ModelExperimentBacktestRequest

        return self.context.backtest().run_model_experiment(
            ModelExperimentBacktestRequest(
                experiment=experiment,
                use_local=use_local,
            )
        )

    @property
    def param_database(self) -> Any:
        return self._param_db
