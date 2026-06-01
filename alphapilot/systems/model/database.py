"""Model parameter database.

Today model hyperparameters live split between the qlib YAML templates
and ``ModelTask.hyperparameters``. This introduces a small centralized,
file-backed store so model configs become first-class and queryable,
mirroring the factor zoo. Default backend is JSON files on disk.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseModelParamDatabase(ABC):
    """Store / fetch model parameter sets keyed by model name."""

    @abstractmethod
    def save(self, model_name: str, params: dict[str, Any]) -> None: ...

    @abstractmethod
    def load(self, model_name: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...


class FileModelParamDatabase(BaseModelParamDatabase):
    """JSON-file-backed model parameter store under ``param_dir``."""

    def __init__(self, param_dir: Path) -> None:
        self.param_dir = Path(param_dir)

    def _path(self, model_name: str) -> Path:
        return self.param_dir / f"{model_name}.json"

    def save(self, model_name: str, params: dict[str, Any]) -> None:
        self.param_dir.mkdir(parents=True, exist_ok=True)
        with self._path(model_name).open("w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

    def load(self, model_name: str) -> dict[str, Any] | None:
        path = self._path(model_name)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_models(self) -> list[str]:
        if not self.param_dir.exists():
            return []
        return sorted(p.stem for p in self.param_dir.glob("*.json"))


def build_model_param_database(backend: str, param_dir: Path) -> BaseModelParamDatabase:
    """Factory: build a model param database for the configured backend."""
    if backend == "file":
        return FileModelParamDatabase(param_dir)
    raise ValueError(f"Unsupported model database backend: {backend!r}")
