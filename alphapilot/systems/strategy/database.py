"""Strategy parameter database.

Stores strategy / scoring-model hyperparameters and related config as JSON
files on disk (mirroring the factor zoo pattern). Default backend is
file-based under ``param_dir``.
"""

from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any

from alphapilot.systems.strategy.base import StrategyMetrics, StrategyModelSpec, StrategyRecord


class BaseStrategyParamDatabase(ABC):
    """Store / fetch strategy parameter sets keyed by name."""

    @abstractmethod
    def save_record(self, record: StrategyRecord) -> None: ...

    @abstractmethod
    def load_record(self, strategy_name: str) -> StrategyRecord | None: ...

    @abstractmethod
    def save(self, strategy_name: str, params: dict[str, Any]) -> None: ...

    @abstractmethod
    def load(self, strategy_name: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_strategies(self) -> list[str]: ...


class FileStrategyParamDatabase(BaseStrategyParamDatabase):
    """File-backed strategy store under ``param_dir`` (one folder per strategy)."""

    def __init__(self, param_dir: Path) -> None:
        self.param_dir = Path(param_dir)

    @staticmethod
    def _sanitize_name(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip())
        return cleaned or "unnamed_strategy"

    def _strategy_dir(self, strategy_name: str) -> Path:
        return self.param_dir / self._sanitize_name(strategy_name)

    def _record_path(self, strategy_name: str) -> Path:
        return self._strategy_dir(strategy_name) / "strategy_record.json"

    def _legacy_path(self, strategy_name: str) -> Path:
        return self.param_dir / f"{strategy_name}.json"

    @staticmethod
    def _record_from_dict(data: dict[str, Any]) -> StrategyRecord:
        model_raw = data.get("model")
        metrics_raw = data.get("metrics")
        return StrategyRecord(
            strategy_name=data["strategy_name"],
            factor_formulas=list(data.get("factor_formulas", [])),
            model=StrategyModelSpec(**model_raw) if isinstance(model_raw, dict) else None,
            metrics=StrategyMetrics(**metrics_raw) if isinstance(metrics_raw, dict) else None,
            metadata=dict(data.get("metadata", {})),
        )

    def save_record(self, record: StrategyRecord) -> None:
        self.param_dir.mkdir(parents=True, exist_ok=True)
        sdir = self._strategy_dir(record.strategy_name)
        sdir.mkdir(parents=True, exist_ok=True)

        record_dict = asdict(record)

        model = record_dict.get("model")
        if isinstance(model, dict):
            uri = model.get("trained_artifact_uri")
            if isinstance(uri, str) and uri:
                src = Path(uri).expanduser()
                if src.exists() and src.is_file():
                    dst_dir = sdir / "artifacts"
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    dst = dst_dir / src.name
                    shutil.copy2(src, dst)
                    model["trained_artifact_uri"] = str(dst)

        with (sdir / "factors.json").open("w", encoding="utf-8") as f:
            json.dump({"factor_formulas": record_dict.get("factor_formulas", [])}, f, ensure_ascii=False, indent=2)
        with (sdir / "model.json").open("w", encoding="utf-8") as f:
            json.dump({"model": record_dict.get("model")}, f, ensure_ascii=False, indent=2)
        with (sdir / "metrics.json").open("w", encoding="utf-8") as f:
            json.dump({"metrics": record_dict.get("metrics")}, f, ensure_ascii=False, indent=2)
        with (sdir / "metadata.json").open("w", encoding="utf-8") as f:
            json.dump({"metadata": record_dict.get("metadata", {})}, f, ensure_ascii=False, indent=2)
        with self._record_path(record.strategy_name).open("w", encoding="utf-8") as f:
            json.dump(record_dict, f, ensure_ascii=False, indent=2)

    def load_record(self, strategy_name: str) -> StrategyRecord | None:
        data = self.load(strategy_name)
        if data is None:
            return None
        if "strategy_name" not in data:
            # Backward compatibility for legacy parameter-only entries.
            data = {
                "strategy_name": strategy_name,
                "factor_formulas": [],
                "model": {"model_name": strategy_name, "hyper_params": data},
                "metrics": None,
                "metadata": {"legacy_params_only": True},
            }
        return self._record_from_dict(data)

    def save(self, strategy_name: str, params: dict[str, Any]) -> None:
        # Backward compatible generic writer; now stores in strategy folder.
        self.param_dir.mkdir(parents=True, exist_ok=True)
        sdir = self._strategy_dir(strategy_name)
        sdir.mkdir(parents=True, exist_ok=True)
        with self._record_path(strategy_name).open("w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

    def load(self, strategy_name: str) -> dict[str, Any] | None:
        path = self._record_path(strategy_name)
        if not path.exists():
            # Legacy flat json compatibility.
            legacy = self._legacy_path(strategy_name)
            if not legacy.exists():
                return None
            with legacy.open("r", encoding="utf-8") as f:
                return json.load(f)
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_strategies(self) -> list[str]:
        if not self.param_dir.exists():
            return []
        folder_names = [p.name for p in self.param_dir.iterdir() if p.is_dir() and (p / "strategy_record.json").exists()]
        legacy_names = [p.stem for p in self.param_dir.glob("*.json")]
        return sorted(set(folder_names + legacy_names))


def build_strategy_param_database(backend: str, param_dir: Path) -> BaseStrategyParamDatabase:
    """Factory: build a strategy param database for the configured backend."""
    if backend == "file":
        return FileStrategyParamDatabase(param_dir)
    raise ValueError(f"Unsupported strategy database backend: {backend!r}")
