"""Strategy parameter database.

Stores strategy / scoring-model hyperparameters and related config as JSON
files on disk (mirroring the factor zoo pattern). Default backend is
file-based under ``param_dir``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseStrategyParamDatabase(ABC):
    """Store / fetch strategy parameter sets keyed by name."""

    @abstractmethod
    def save(self, strategy_name: str, params: dict[str, Any]) -> None: ...

    @abstractmethod
    def load(self, strategy_name: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_strategies(self) -> list[str]: ...


class FileStrategyParamDatabase(BaseStrategyParamDatabase):
    """JSON-file-backed strategy parameter store under ``param_dir``."""

    def __init__(self, param_dir: Path) -> None:
        self.param_dir = Path(param_dir)

    def _path(self, strategy_name: str) -> Path:
        return self.param_dir / f"{strategy_name}.json"

    def save(self, strategy_name: str, params: dict[str, Any]) -> None:
        self.param_dir.mkdir(parents=True, exist_ok=True)
        with self._path(strategy_name).open("w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

    def load(self, strategy_name: str) -> dict[str, Any] | None:
        path = self._path(strategy_name)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_strategies(self) -> list[str]:
        if not self.param_dir.exists():
            return []
        return sorted(p.stem for p in self.param_dir.glob("*.json"))


def build_strategy_param_database(backend: str, param_dir: Path) -> BaseStrategyParamDatabase:
    """Factory: build a strategy param database for the configured backend."""
    if backend == "file":
        return FileStrategyParamDatabase(param_dir)
    raise ValueError(f"Unsupported strategy database backend: {backend!r}")
