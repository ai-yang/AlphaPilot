"""Export Qlib scoring-model config and fitted artifacts from a backtest workspace."""

from __future__ import annotations

import json
import os
import pickle
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from alphapilot.log import logger

# Qlib trainer persists the fitted wrapper as ``params.pkl`` (see qlib.model.trainer).
RECORDER_MODEL_KEYS = (
    "params.pkl",
    "model.pkl",
    "model",
    "init_model",
    "trained_model",
)


def _load_task_model_from_conf(workspace_path: Path, qlib_config_name: str) -> dict[str, Any]:
    conf_path = workspace_path / qlib_config_name
    if not conf_path.exists():
        return {}
    with conf_path.open("r", encoding="utf-8") as f:
        conf = yaml.safe_load(f) or {}
    task = conf.get("task") or {}
    model = task.get("model") or {}
    dataset = task.get("dataset") or {}
    return {
        "qlib_config": qlib_config_name,
        "model_class": model.get("class"),
        "model_module": model.get("module_path"),
        "model_kwargs": model.get("kwargs") or {},
        "dataset_segments": (dataset.get("kwargs") or {}).get("segments"),
    }


def _metrics_from_workspace(workspace_path: Path) -> dict[str, Any]:
    csv_path = workspace_path / "qlib_res.csv"
    if not csv_path.exists():
        return {}
    series = pd.read_csv(csv_path, index_col=0).iloc[:, 0]
    return {str(k): float(v) if pd.notna(v) else None for k, v in series.items()}


def _find_params_pkl_in_mlruns(workspace_path: Path) -> Path | None:
    mlruns = workspace_path / "mlruns"
    if not mlruns.is_dir():
        return None
    candidates = sorted(
        mlruns.glob("**/artifacts/params.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_object_from_recorder(recorder: Any, keys: tuple[str, ...] = RECORDER_MODEL_KEYS) -> tuple[Any, str] | None:
    for key in keys:
        try:
            return recorder.load_object(key), key
        except Exception:  # noqa: BLE001
            continue
    return None


def _get_latest_recorder_in_workspace(workspace_path: Path) -> tuple[Any, str] | None:
    """Resolve the recorder for the most recent ``qrun`` in *workspace_path*."""
    workspace_path = Path(workspace_path).resolve()
    pkl_path = _find_params_pkl_in_mlruns(workspace_path)
    if pkl_path is not None:
        with pkl_path.open("rb") as f:
            return pickle.load(f), "mlruns/artifacts/params.pkl"

    cwd = os.getcwd()
    try:
        os.chdir(workspace_path)
        import qlib
        from qlib.workflow import R

        qlib.init()
        latest_recorder = None
        experiment_name = None
        for experiment in R.list_experiments():
            for recorder_id in R.list_recorders(experiment_name=experiment):
                if recorder_id is None:
                    continue
                recorder = R.get_recorder(recorder_id=recorder_id, experiment_name=experiment)
                end_time = recorder.info.get("end_time")
                if latest_recorder is None:
                    latest_recorder = recorder
                    experiment_name = experiment
                elif end_time is not None and end_time > latest_recorder.info.get("end_time"):
                    latest_recorder = recorder
                    experiment_name = experiment

        if latest_recorder is None:
            return None

        loaded = _load_object_from_recorder(latest_recorder)
        if loaded is None:
            return None
        obj, key = loaded
        return obj, f"recorder:{experiment_name}:{latest_recorder.id}:{key}"
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not load model from Qlib recorder in workspace: {exc}")
        return None
    finally:
        os.chdir(cwd)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(data), f, ensure_ascii=False, indent=2)


def _serialize_lightgbm_booster(booster: Any, artifact_dir: Path) -> dict[str, Any]:
    """Persist trained LightGBM booster (tree ensemble) in reloadable formats."""
    out: dict[str, Any] = {"format": "lightgbm.Booster"}

    lgb_txt = artifact_dir / "fitted_model.lgb.txt"
    booster.save_model(str(lgb_txt))
    out["model_file"] = lgb_txt.name

    best_iteration = getattr(booster, "best_iteration", None)
    if best_iteration is not None:
        out["best_iteration"] = int(best_iteration)
    out["num_trees"] = int(booster.num_trees())

    feature_names = list(booster.feature_name())
    out["feature_names"] = feature_names

    importance: dict[str, Any] = {}
    for imp_type in ("gain", "split"):
        try:
            scores = booster.feature_importance(importance_type=imp_type)
            importance[imp_type] = {
                name: float(score) for name, score in zip(feature_names, scores, strict=False)
            }
        except Exception:  # noqa: BLE001
            continue
    out["feature_importance"] = importance

    return out


def _serialize_fitted_model(model_obj: Any, artifact_dir: Path) -> dict[str, Any]:
    """
    Save trained model state (not just yaml hyperparameters).

    Writes:
    - ``fitted_model.pkl`` — full Qlib model object from ``params.pkl``
    - ``fitted_model.lgb.txt`` — native LightGBM model (when applicable)
    - ``fitted_training_state.json`` — best_iteration, importances, etc.
    """
    meta: dict[str, Any] = {
        "saved": False,
        "model_type": f"{model_obj.__class__.__module__}.{model_obj.__class__.__name__}",
    }

    with (artifact_dir / "fitted_model.pkl").open("wb") as f:
        pickle.dump(model_obj, f)
    meta["saved"] = True
    meta["pickle_file"] = "fitted_model.pkl"

    # Qlib LGBModel: hyperparameters in .params, trained booster in .model
    if hasattr(model_obj, "params") and isinstance(getattr(model_obj, "params"), dict):
        meta["training_hyperparameters"] = _json_safe(dict(model_obj.params))
        _write_json(artifact_dir / "training_hyperparameters.json", meta["training_hyperparameters"])

    booster = getattr(model_obj, "model", None)
    if booster is not None and booster.__class__.__module__.startswith("lightgbm"):
        meta["lightgbm"] = _serialize_lightgbm_booster(booster, artifact_dir)
        _write_json(artifact_dir / "fitted_training_state.json", meta)
        return meta

    # Other sklearn-like models
    if hasattr(model_obj, "get_params"):
        try:
            meta["sklearn_params"] = _json_safe(model_obj.get_params())
        except Exception:  # noqa: BLE001
            pass

    _write_json(artifact_dir / "fitted_training_state.json", meta)
    return meta


def _recorder_meta_from_loaded(loaded: tuple[Any, str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"recorder_found": False}
    if loaded is None:
        return out
    model_obj, source = loaded
    out["recorder_found"] = True
    out["source"] = source
    out["model_type"] = f"{model_obj.__class__.__module__}.{model_obj.__class__.__name__}"
    if hasattr(model_obj, "params") and isinstance(getattr(model_obj, "params"), dict):
        out["training_hyperparameters"] = _json_safe(dict(model_obj.params))
    out["has_trained_booster"] = getattr(model_obj, "model", None) is not None
    return out


def export_scoring_model_artifacts(
    workspace_path: Path,
    qlib_config_name: str,
) -> Path:
    """
    Write artifacts under ``workspace/artifacts/scoring_model/``.

    Returns the artifact directory path.
    """
    workspace_path = Path(workspace_path)
    artifact_dir = workspace_path / "artifacts" / "scoring_model"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    model_config = _load_task_model_from_conf(workspace_path, qlib_config_name)
    loaded = _get_latest_recorder_in_workspace(workspace_path)
    recorder_meta = _recorder_meta_from_loaded(loaded)

    _write_json(artifact_dir / "model_config.json", model_config)

    metrics = _metrics_from_workspace(workspace_path)
    fitted_meta: dict[str, Any] | None = None
    if loaded is not None:
        model_obj, source = loaded
        try:
            fitted_meta = _serialize_fitted_model(model_obj, artifact_dir)
            fitted_meta["source"] = source
            logger.info(
                f"Saved fitted scoring model to {artifact_dir} "
                f"(type={fitted_meta.get('model_type')}, lgb={bool(fitted_meta.get('lightgbm'))})"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not serialize fitted model: {exc}")
            fitted_meta = {"saved": False, "error": str(exc)}

    summary = {
        "model_config": model_config,
        "metrics": metrics,
        "recorder": recorder_meta,
        "fitted_model": fitted_meta,
    }
    _write_json(artifact_dir / "scoring_model_summary.json", summary)

    metrics_path = workspace_path / "qlib_res.csv"
    if metrics_path.exists():
        shutil.copy2(metrics_path, artifact_dir / "qlib_metrics.csv")

    return artifact_dir


def persist_qlib_template_to_log(
    log_root: Path,
    round_no: int,
    workspace_path: Path,
    qlib_config_name: str,
    *,
    template_dir: str | Path | None = None,
) -> Path:
    """Copy the qlib yaml and ``read_exp_res.py`` used for this round into the mining log."""
    from alphapilot.log.mine_paths import qlib_template_log_dir

    workspace_path = Path(workspace_path)
    log_root = Path(log_root)
    dst = qlib_template_log_dir(log_root, round_no)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    saved_files: list[str] = []
    template_path = Path(template_dir).expanduser().resolve() if template_dir else None

    config_dst = dst / qlib_config_name
    config_src = workspace_path / qlib_config_name
    if not config_src.exists() and template_path is not None:
        config_src = template_path / qlib_config_name
    if config_src.exists():
        shutil.copy2(config_src, config_dst)
        saved_files.append(qlib_config_name)

    read_exp_dst = dst / "read_exp_res.py"
    read_exp_src = workspace_path / "read_exp_res.py"
    if not read_exp_src.exists() and template_path is not None:
        read_exp_src = template_path / "read_exp_res.py"
    if read_exp_src.exists():
        shutil.copy2(read_exp_src, read_exp_dst)
        saved_files.append("read_exp_res.py")

    manifest = {
        "qlib_config_name": qlib_config_name,
        "qlib_template_dir": str(template_path) if template_path else None,
        "workspace": str(workspace_path.resolve()),
        "files": saved_files,
    }
    _write_json(dst / "manifest.json", manifest)

    logger.info(
        f"[因子挖掘] 第 {round_no} 轮 Qlib 模板已保存: {dst.relative_to(log_root)} "
        f"(config={qlib_config_name}, files={saved_files})"
    )
    return dst


def persist_scoring_model_to_log(
    log_root: Path,
    round_no: int,
    workspace_path: Path,
    qlib_config_name: str,
) -> Path:
    """Export from workspace and copy into ``log/.../rounds/round_XX/04_backtest/scoring_model/``."""
    from alphapilot.log.mine_paths import scoring_model_log_dir

    workspace_path = Path(workspace_path)
    log_root = Path(log_root)
    export_scoring_model_artifacts(workspace_path, qlib_config_name)

    src = workspace_path / "artifacts" / "scoring_model"
    dst = scoring_model_log_dir(log_root, round_no)
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True, exist_ok=True)

    fitted_ok = (dst / "fitted_model.pkl").exists() or (dst / "fitted_model.lgb.txt").exists()
    logger.info(
        f"[因子挖掘] 第 {round_no} 轮打分模型已保存: {dst.relative_to(log_root)} "
        f"(config={qlib_config_name}, fitted={'yes' if fitted_ok else 'no'})"
    )
    return dst
