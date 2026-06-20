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

    @abstractmethod
    def strategy_dir(self, strategy_name: str) -> Path | None: ...

    @abstractmethod
    def append_retest(self, strategy_name: str, payload: dict[str, Any]) -> Path | None: ...

    @abstractmethod
    def retest_bundle_dir(self, strategy_name: str, timestamp: str, mode: str) -> Path | None: ...

    @abstractmethod
    def delete_strategy(self, strategy_name: str) -> bool: ...


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
    def _copy_qlib_template_snapshot(
        record_dict: dict[str, Any],
        sdir: Path,
        *,
        artifact_uri_hint: str | None = None,
    ) -> None:
        metadata = record_dict.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            return

        config_name = metadata.get("qlib_config_name")
        if not isinstance(config_name, str) or not config_name:
            model = record_dict.get("model")
            if isinstance(model, dict):
                hyper_params = model.get("hyper_params")
                if isinstance(hyper_params, dict):
                    config_name = hyper_params.get("qlib_config")
        if not isinstance(config_name, str) or not config_name:
            return

        candidate_dirs: list[Path] = []
        for key in ("qlib_template_source_dir", "qlib_template_dir"):
            raw = metadata.get(key)
            if isinstance(raw, str) and raw:
                candidate_dirs.append(Path(raw).expanduser())

        model = record_dict.get("model")
        artifact_candidates = [artifact_uri_hint]
        artifact_candidates.append(model.get("trained_artifact_uri") if isinstance(model, dict) else None)
        for artifact_uri in artifact_candidates:
            if not isinstance(artifact_uri, str) or not artifact_uri:
                continue
            artifact_path = Path(artifact_uri).expanduser()
            candidate_dirs.append(artifact_path.parent.parent / "qlib_template")

        source_dir = next(
            (path for path in candidate_dirs if path.exists() and (path / config_name).exists()),
            None,
        )
        if source_dir is None:
            return

        dst_dir = sdir / "qlib_template"
        dst_dir.mkdir(parents=True, exist_ok=True)

        copied: list[str] = []
        for filename in (config_name, "read_exp_res.py", "manifest.json"):
            src = source_dir / filename
            if not src.exists() or not src.is_file():
                continue
            dst = dst_dir / filename
            if src.resolve() == dst.resolve():
                copied.append(filename)
                continue
            shutil.copy2(src, dst)
            copied.append(filename)

        if not copied:
            return

        metadata["qlib_config_path"] = f"qlib_template/{config_name}"
        metadata["qlib_template_snapshot_dir"] = "qlib_template"
        metadata["qlib_template_source_dir"] = str(source_dir.resolve())
        metadata["qlib_template_files"] = copied

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
        original_artifact_uri = model.get("trained_artifact_uri") if isinstance(model, dict) else None
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

        self._copy_qlib_template_snapshot(
            record_dict,
            sdir,
            artifact_uri_hint=original_artifact_uri if isinstance(original_artifact_uri, str) else None,
        )

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

    def strategy_dir(self, strategy_name: str) -> Path | None:
        sdir = self._strategy_dir(strategy_name)
        if (sdir / "strategy_record.json").exists():
            return sdir
        return None

    def retest_bundle_dir(self, strategy_name: str, timestamp: str, mode: str) -> Path | None:
        sdir = self.strategy_dir(strategy_name)
        if sdir is None:
            return None
        bundle = sdir / "retests" / f"{timestamp}_{mode}"
        bundle.mkdir(parents=True, exist_ok=True)
        return bundle

    def delete_strategy(self, strategy_name: str) -> bool:
        from alphapilot.core.path_safety import ensure_child_path

        deleted = False
        sdir = self._strategy_dir(strategy_name)
        if (sdir / "strategy_record.json").exists():
            ensure_child_path(self.param_dir, sdir)
            shutil.rmtree(sdir)
            deleted = True

        legacy = self._legacy_path(strategy_name)
        if legacy.exists():
            ensure_child_path(self.param_dir, legacy)
            legacy.unlink()
            deleted = True

        return deleted

    def append_retest(self, strategy_name: str, payload: dict[str, Any]) -> Path | None:
        sdir = self.strategy_dir(strategy_name)
        if sdir is None:
            return None
        retests_dir = sdir / "retests"
        retests_dir.mkdir(parents=True, exist_ok=True)
        ts = payload.get("timestamp")
        if not isinstance(ts, str) or not ts:
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            payload["timestamp"] = ts
        out = retests_dir / f"{ts}_{payload.get('mode', 'unknown')}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return out


def build_strategy_param_database(backend: str, param_dir: Path) -> BaseStrategyParamDatabase:
    """Factory: build a strategy param database for the configured backend."""
    if backend == "file":
        return FileStrategyParamDatabase(param_dir)
    raise ValueError(f"Unsupported strategy database backend: {backend!r}")
