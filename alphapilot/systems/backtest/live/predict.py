"""Single-day model scoring.

Reuses the factor-calculation path to build today's ``combined_factors_df.pkl`` and the
``QlibYamlParams`` renderer to get the *same* handler (data_loader + infer_processors) used at
training, then runs ``model.predict`` on a one-day ``DatasetH`` (test segment = the target
date). qlib applies the infer processors (Fillna + cross-sectional CSZScoreNorm) automatically,
so scores match training-time inference.
"""

from __future__ import annotations

import os
import pickle
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.log import logger

# History buffer (calendar days) so factor lookbacks + processors have enough data.
_WINDOW_BUFFER_DAYS = 400


def _coerce_params(yaml_params: Any):
    from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams

    if yaml_params is None:
        return QlibYamlParams.defaults_for("combined")
    if isinstance(yaml_params, QlibYamlParams):
        return yaml_params
    # A partial dict is a patch onto the combined template (daily signals gate combined-factor
    # computation on template_type); default it so an override that omits template_type still works.
    if isinstance(yaml_params, dict) and "template_type" not in yaml_params:
        yaml_params = {"template_type": "combined", **yaml_params}
    return QlibYamlParams.model_validate(yaml_params)


def latest_factor_date(
    *, factor_data_dir: str | Path | None = None, use_local: bool = True
) -> str | None:
    """Newest date in the factor source (``daily_pv.h5``); ``None`` if unreadable.

    Combined-template factors are computed from this file, so it — *not* the qlib price
    calendar — bounds the newest day we can score. When the qlib store is fresher than this
    file (prices updated but factors not regenerated), scoring beyond it yields no rows and the
    daily signal is silently empty. The daily-trade tool uses this to anchor/validate the
    execution date so it never trades on a day that has no scores.

    Resolution precedence: explicit ``factor_data_dir`` (a ``<spec_hash>/`` cache dir or a dir
    directly holding ``daily_pv.h5``) → ``ALPHAPILOT_FACTOR_DATA*`` env → legacy global folders.
    """
    import os

    from alphapilot.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS as cfg
    from alphapilot.systems.data.factor_h5 import ENV_DATA_DEBUG_DIR, ENV_DATA_DIR

    candidates: list[Path] = []
    if factor_data_dir is not None:
        base = Path(factor_data_dir)
        candidates += [base / "daily_pv.h5", base / "all" / "daily_pv.h5"]
    env_all = os.environ.get(ENV_DATA_DIR)
    env_debug = os.environ.get(ENV_DATA_DEBUG_DIR)
    if env_all:
        candidates.append(Path(env_all) / "daily_pv.h5")
    if env_debug:
        candidates.append(Path(env_debug) / "daily_pv.h5")
    # Mined (version-2) factors read the full ``data_folder``; fall back to the debug copy.
    candidates += [
        Path(cfg.data_folder) / "daily_pv.h5",
        Path(cfg.data_folder_debug) / "daily_pv.h5",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            frame = pd.read_hdf(path)
            return pd.Timestamp(frame.index.get_level_values(0).max()).strftime("%Y-%m-%d")
        except Exception as exc:  # noqa: BLE001 — best-effort; fall through to next candidate
            logger.warning(f"[daily_trade] could not read factor source {path}: {exc}")
    return None


def compute_combined_factors(
    factor_csv: str | Path,
    *,
    qlib_template_dir: str | None,
    use_local: bool,
    run_env: dict | None = None,
) -> Path:
    """Compute factor values and write ``combined_factors_df.pkl``; return its path.

    Mirrors the pkl-writing block of ``QlibFactorRunner.develop`` (factor_runner.py) but stops
    before ``qrun`` — we only need the factor frame for inference.

    The factor data context is expected to already be published via env by the caller
    (``generate_daily_signal``); when absent we fall back to the legacy global folders so this
    function keeps working standalone.
    """
    import os

    from alphapilot.components.coder.factor_coder import FactorCoder
    from alphapilot.components.coder.factor_coder.data import ensure_factor_data
    from alphapilot.core.pickle_cache import pickle_cache_scope
    from alphapilot.systems.backtest.pipelines.factor_source import build_factor_experiment_from_csv
    from alphapilot.systems.backtest.qlib.scenario import QlibFactorEvaluationScenario
    from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner
    from alphapilot.systems.data.factor_h5 import ENV_DATA_DIR

    if not os.environ.get(ENV_DATA_DIR):
        ensure_factor_data(use_local=use_local)
    scenario = QlibFactorEvaluationScenario(use_local=use_local, qlib_template_dir=qlib_template_dir)
    experiment = build_factor_experiment_from_csv(factor_csv, qlib_template_dir=qlib_template_dir)
    experiment.run_env = dict(run_env or {})

    with pickle_cache_scope("backtest"):
        coder = FactorCoder(scenario, with_feedback=False, with_knowledge=False, knowledge_self_gen=False)
        experiment = coder.develop(experiment)
        frame = QlibFactorRunner(None).process_factor_data(experiment)

    frame = frame.sort_index()
    frame = frame.loc[:, ~frame.columns.duplicated(keep="last")]
    frame.columns = pd.MultiIndex.from_product([["feature"], frame.columns])

    ws = Path(experiment.experiment_workspace.workspace_path)
    ws.mkdir(parents=True, exist_ok=True)
    pkl_path = ws / "combined_factors_df.pkl"
    with pkl_path.open("wb") as handle:
        pickle.dump(frame, handle)
    logger.info(f"[daily_trade] wrote combined factors ({frame.shape}) -> {pkl_path}")
    return pkl_path


def _patch_static_loader_path(node: Any, abs_pkl_path: str) -> bool:
    """Recursively point any StaticDataLoader's ``config`` at the absolute pkl path."""
    found = False
    if isinstance(node, dict):
        cls = str(node.get("class", ""))
        if "StaticDataLoader" in cls:
            node.setdefault("kwargs", {})["config"] = abs_pkl_path
            found = True
        for value in node.values():
            found = _patch_static_loader_path(value, abs_pkl_path) or found
    elif isinstance(node, list):
        for item in node:
            found = _patch_static_loader_path(item, abs_pkl_path) or found
    return found


def build_dataset_config(
    params: Any, date: str, combined_pkl: Path | None, start_date: str | None = None
) -> dict:
    """Render the qlib yaml and return a ``task.dataset`` config for test = ``[start_date, date]``."""
    import yaml

    from alphapilot.systems.backtest.qlib_yaml.generator import render_yaml_text

    conf = yaml.safe_load(render_yaml_text(params))
    dataset_conf = conf["task"]["dataset"]
    handler_kwargs = dataset_conf["kwargs"]["handler"]["kwargs"]

    seg_start = start_date or date
    window_start = (
        datetime.strptime(seg_start, "%Y-%m-%d") - timedelta(days=_WINDOW_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")
    handler_kwargs["start_time"] = window_start
    handler_kwargs["end_time"] = date
    dataset_conf["kwargs"]["segments"] = {"test": [seg_start, date]}

    if combined_pkl is not None:
        patched = _patch_static_loader_path(handler_kwargs.get("data_loader"), str(combined_pkl.resolve()))
        if not patched:
            logger.warning("[daily_trade] no StaticDataLoader found to attach combined_factors_df.pkl")
    return dataset_conf


def _init_qlib(params: Any, provider_uri: str | None = None) -> None:
    import qlib

    resolved = provider_uri or os.environ.get("ALPHAPILOT_QLIB_DATA_DIR") or params.provider_uri
    try:
        qlib.init(provider_uri=resolved, region=params.region)
    except Exception as exc:  # noqa: BLE001 — qlib re-init / already-inited is non-fatal
        logger.info(f"[daily_trade] qlib.init note: {exc}")


def predict_scores(
    date: str,
    model_pickle_path: str | Path,
    factor_csv: str | Path | None,
    *,
    yaml_params: Any = None,
    qlib_template_dir: str | None = None,
    use_local: bool = True,
    run_env: dict | None = None,
    provider_uri: str | None = None,
    start_date: str | None = None,
) -> pd.Series:
    """Return per-stock scores over ``[start_date, date]`` indexed by ``(datetime, instrument)``."""
    params = _coerce_params(yaml_params)

    combined_pkl: Path | None = None
    if params.template_type == "combined":
        if not factor_csv:
            raise ValueError("combined template requires a factor_csv to compute today's factors")
        combined_pkl = compute_combined_factors(
            factor_csv, qlib_template_dir=qlib_template_dir, use_local=use_local, run_env=run_env
        )

    dataset_conf = build_dataset_config(params, date, combined_pkl, start_date=start_date)

    _init_qlib(params, provider_uri)
    from qlib.utils import init_instance_by_config

    # Run in a scratch dir so any relative StaticDataLoader path still resolves.
    scratch = Path(combined_pkl).parent if combined_pkl is not None else Path(os.getcwd())
    cwd = os.getcwd()
    try:
        os.chdir(scratch)
        dataset = init_instance_by_config(dataset_conf)
        with open(model_pickle_path, "rb") as handle:
            model = pickle.load(handle)
        scores = model.predict(dataset)
    finally:
        os.chdir(cwd)

    if isinstance(scores, pd.DataFrame):
        scores = scores.iloc[:, 0]
    scores = scores.dropna()

    # qlib only trades on a day that has a signal, so the *execution* date itself must be
    # scored. If it is missing, the factor source is staler than the price store and the
    # backtest would silently produce no trades — fail loudly with an actionable message.
    date_ts = pd.Timestamp(date)
    if scores.empty or not (scores.index.get_level_values(0) == date_ts).any():
        factor_day = latest_factor_date(use_local=use_local)
        raise ValueError(
            f"No scores for execution date {date}: the factor source (daily_pv.h5) covers up "
            f"to {factor_day or 'an unknown date'}, which is staler than the qlib price store. "
            f"Refresh the factor data to >= {date}, or use a --date within factor coverage "
            f"(<= {factor_day or 'the latest factor date'})."
        )
    logger.info(f"[daily_trade] scored {len(scores)} instruments for {date}")
    return scores
