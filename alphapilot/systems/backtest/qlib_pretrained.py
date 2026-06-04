"""Load a saved Qlib LGBModel artifact and skip ``fit`` during ``qrun``."""

from __future__ import annotations

import os
import pickle
import re
from pathlib import Path
from typing import Any

from qlib.contrib.model.gbdt import LGBModel

from alphapilot.log import logger

PRETRAINED_ENV_VAR = "ALPHAPILOT_PRETRAINED_MODEL_PKL"
_PRETRAINED_CLASS = "PretrainedLGBModel"
_PRETRAINED_MODULE = "alphapilot.systems.backtest.qlib_pretrained"


class PretrainedLGBModel(LGBModel):
    """LGBModel that loads ``fitted_model.pkl`` instead of training when configured."""

    def __init__(self, pretrained_pkl: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pretrained_pkl = pretrained_pkl

    def _resolve_pretrained_path(self) -> Path | None:
        raw = self.pretrained_pkl or os.environ.get(PRETRAINED_ENV_VAR)
        if not raw:
            return None
        path = Path(raw).expanduser().resolve()
        return path if path.exists() else None

    def fit(self, dataset, reweighter=None, **kwargs) -> None:  # noqa: ANN001
        path = self._resolve_pretrained_path()
        if path is None:
            super().fit(dataset, reweighter=reweighter, **kwargs)
            return

        with path.open("rb") as handle:
            loaded = pickle.load(handle)

        if not isinstance(loaded, LGBModel):
            raise TypeError(
                f"Expected qlib LGBModel in {path}, got {type(loaded).__name__}"
            )
        if loaded.model is None:
            raise ValueError(f"Pretrained model in {path} has no trained booster (model is None)")

        self.model = loaded.model
        if getattr(loaded, "params", None):
            self.params.update(loaded.params)
        logger.info(f"[reuse_model] Loaded pretrained LGBModel from {path} (training skipped)")


def patch_qlib_conf_for_pretrained(workspace_path: Path, qlib_config_name: str) -> None:
    """Point workspace qlib yaml at :class:`PretrainedLGBModel`."""
    conf_path = Path(workspace_path) / qlib_config_name
    if not conf_path.exists():
        raise FileNotFoundError(f"Qlib config not found: {conf_path}")

    text = conf_path.read_text(encoding="utf-8")
    if _PRETRAINED_CLASS in text and _PRETRAINED_MODULE in text:
        return

    updated = re.sub(
        r"(?m)^(\s*)class:\s*LGBModel\b.*$",
        rf"\1class: {_PRETRAINED_CLASS}",
        text,
        count=1,
    )
    updated = re.sub(
        r"(?m)^(\s*)module_path:\s*qlib\.contrib\.model\.gbdt\s*$",
        rf"\1module_path: {_PRETRAINED_MODULE}",
        updated,
        count=1,
    )
    if updated == text:
        raise RuntimeError(f"Could not patch LGBModel section in {conf_path}")

    conf_path.write_text(updated, encoding="utf-8")
    logger.info(f"[reuse_model] Patched {conf_path.name} to use {_PRETRAINED_CLASS}")


def build_pretrained_run_env(model_pickle_path: str | Path) -> dict[str, str]:
    """Environment variables passed to ``qrun`` for pretrained inference."""
    path = Path(model_pickle_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Pretrained model not found: {path}")
    return {PRETRAINED_ENV_VAR: str(path)}
