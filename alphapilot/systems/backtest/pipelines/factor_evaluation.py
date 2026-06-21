"""Factor evaluation pipeline owned by the backtest system (CSV → calculate → qlib)."""

from __future__ import annotations

import csv
import math
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from alphapilot.components.coder.factor_coder import FactorCoder
from alphapilot.core.pickle_cache import pickle_cache_scope
from alphapilot.systems.backtest.pipelines.factor_source import build_factor_experiment_from_csv
from alphapilot.systems.backtest.qlib.scenario import QlibFactorEvaluationScenario
from alphapilot.systems.backtest.types import (
    FactorBacktestRequest,
    FactorBacktestResult,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _resolve_use_local(context: Context, use_local: bool | None) -> bool:
    if use_local is not None:
        return use_local
    return context.config.backtest.use_local


def prepare_factor_csv(request: FactorBacktestRequest) -> tuple[Path, bool]:
    """Return ``(csv path, is_temporary)``."""
    if request.factor_path is not None:
        return Path(request.factor_path).expanduser(), False

    if not request.factors:
        raise ValueError("FactorBacktestRequest requires factor_path or non-empty factors.")

    fd, temp_path = tempfile.mkstemp(prefix="alphapilot_factors_", suffix=".csv")
    temp_csv = Path(temp_path)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["factor_name", "factor_expression"])
        writer.writeheader()
        for factor in request.factors:
            writer.writerow(
                {
                    "factor_name": factor.factor_name,
                    "factor_expression": factor.factor_expression,
                }
            )
    return temp_csv, True


VALID_MODES = ("multi_combined", "single_ic", "multi_sequential")


def _cleanup_temp_csv(path: Path, is_temp: bool) -> None:
    if is_temp:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_single_factor_csv(factor_name: str, factor_expression: str) -> Path:
    fd, temp_path = tempfile.mkstemp(prefix="alphapilot_seq_factor_", suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["factor_name", "factor_expression"])
        writer.writeheader()
        writer.writerow({"factor_name": factor_name, "factor_expression": factor_expression})
    return Path(temp_path)


def _extract_portfolio_metrics(metrics) -> dict:
    """Pull a curated set from a qlib ``qlib_res.csv`` Series for the leaderboard.

    Mirrors the alias-matching spirit of ``systems/strategy/service.py:_extract_metrics``.
    """
    keys = ("IC", "RankIC", "ICIR", "RankICIR", "AnnReturn", "IR", "MaxDD")
    out = {k: float("nan") for k in keys}
    if metrics is None or not hasattr(metrics, "index"):
        return out

    def _exact(name: str) -> float:
        return float(metrics[name]) if name in metrics.index else float("nan")

    def _sub(*needles: str) -> float:
        for idx in metrics.index:
            low = str(idx).lower()
            if all(n in low for n in needles):
                try:
                    return float(metrics[idx])
                except (TypeError, ValueError):
                    return float("nan")
        return float("nan")

    out["IC"] = _exact("IC")
    out["RankIC"] = _exact("Rank IC")
    out["ICIR"] = _exact("ICIR")
    out["RankICIR"] = _exact("Rank ICIR")
    ann = _sub("annualized_return", "with_cost")
    out["AnnReturn"] = ann if not math.isnan(ann) else _sub("annualized_return")
    ir = _sub("information_ratio", "with_cost")
    out["IR"] = ir if not math.isnan(ir) else _sub("information_ratio")
    mdd = _sub("max_drawdown", "with_cost")
    out["MaxDD"] = mdd if not math.isnan(mdd) else _sub("max_drawdown")
    return out


def _write_sequential_leaderboard(leaderboard, experiment) -> None:
    if leaderboard is None or getattr(leaderboard, "empty", True):
        return
    try:
        from alphapilot.systems.backtest.artifacts import default_workspace_root

        if experiment is not None:
            target = Path(experiment.experiment_workspace.workspace_path)
        else:
            target = Path(default_workspace_root())
        target.mkdir(parents=True, exist_ok=True)
        leaderboard.to_csv(target / "factor_portfolio_leaderboard.csv", index=False)
    except Exception:  # noqa: BLE001
        pass


class FactorEvaluationPipeline:
    """End-to-end evaluation for user-supplied factor expressions (no mining loop)."""

    def run(self, context: Context, request: FactorBacktestRequest) -> FactorBacktestResult:
        if request.mode not in VALID_MODES:
            raise ValueError(
                f"Unknown backtest mode '{request.mode}'; expected one of {list(VALID_MODES)}"
            )
        if request.mode == "single_ic":
            return self._run_single_ic(context, request)
        if request.mode == "multi_sequential":
            return self._run_multi_sequential(context, request)
        return self._run_combined(context, request)

    # -- shared helpers ---------------------------------------------------

    def _build_experiment(self, context, request, factor_csv, *, extra_tasks=None):
        from alphapilot.systems.data.factor_h5 import apply_context_env, prepare_or_reuse_context

        use_local = _resolve_use_local(context, request.use_local)
        # Prepare the task's factor h5 context (market/spec cache) and publish it via env BEFORE
        # the scenario is built, so the LLM source-data description and factor execution all read
        # this task's data instead of the global shared folder.
        factor_data_ctx = prepare_or_reuse_context(
            market=getattr(request, "market", None),
            qlib_dir=str(context.config.data.qlib_data_dir),
            yaml_params=request.yaml_params,
            factor_data_dir=getattr(request, "factor_data_dir", None),
            use_local=use_local,
        )
        apply_context_env(factor_data_ctx)
        # When invoked under an `alphapilot backtest` run, link the shared h5 cache into the run
        # dir and record its fingerprint. No-op for internal callers (strategy/daily) with no run.
        from alphapilot.systems.run_workspace import current_run

        run = current_run()
        if run is not None:
            run.attach_factor_data(factor_data_ctx)
        scenario = QlibFactorEvaluationScenario(
            use_local=use_local,
            qlib_template_dir=request.qlib_template_dir,
        )
        scenario.factor_data_context = factor_data_ctx
        experiment = build_factor_experiment_from_csv(
            factor_csv,
            qlib_template_dir=request.qlib_template_dir,
        )
        if extra_tasks:
            experiment.sub_tasks = list(experiment.sub_tasks) + list(extra_tasks)
        if request.qlib_config_name:
            experiment.qlib_config_name = request.qlib_config_name
        experiment.run_env = {**dict(request.run_env), **factor_data_ctx.env()}
        experiment.factor_data_context = factor_data_ctx
        if request.yaml_params is not None:
            experiment.yaml_params = request.yaml_params
        return experiment, scenario, use_local

    @staticmethod
    def _develop(scenario, experiment):
        coder = FactorCoder(
            scenario,
            with_feedback=False,
            with_knowledge=False,
            knowledge_self_gen=False,
        )
        return coder.develop(experiment)

    # -- mode: multi_combined (today's default) ---------------------------

    def _run_combined(self, context, request) -> FactorBacktestResult:
        from alphapilot.systems.backtest.engines.qlib_workflow import QlibWorkflowEngine
        from alphapilot.systems.backtest.qlib_config import resolve_qlib_config_name

        factor_csv, is_temp = prepare_factor_csv(request)
        try:
            experiment, scenario, use_local = self._build_experiment(context, request, factor_csv)
            with pickle_cache_scope("backtest"):
                experiment = self._develop(scenario, experiment)
                outcome = QlibWorkflowEngine().run(
                    experiment, use_local=use_local, run_env=experiment.run_env
                )
            experiment = outcome.experiment
            experiment.qlib_config_name = resolve_qlib_config_name(experiment)
            return FactorBacktestResult(
                experiment=experiment, metrics=outcome.metrics, mode="multi_combined"
            )
        finally:
            _cleanup_temp_csv(factor_csv, is_temp)

    # -- mode: single_ic (per-factor IC, no qrun) -------------------------

    def _run_single_ic(self, context, request) -> FactorBacktestResult:
        from alphapilot.systems.backtest.engines.qlib_signal import QlibSignalEngine, make_close_task

        factor_csv, is_temp = prepare_factor_csv(request)
        try:
            experiment, scenario, use_local = self._build_experiment(
                context, request, factor_csv, extra_tasks=[make_close_task()]
            )
            with pickle_cache_scope("backtest"):
                experiment = self._develop(scenario, experiment)
                outcome = QlibSignalEngine().run(
                    experiment, use_local=use_local, run_env=experiment.run_env
                )
            return FactorBacktestResult(
                experiment=outcome.experiment,
                metrics=outcome.metrics,
                mode="single_ic",
                per_factor=outcome.per_factor,
            )
        finally:
            _cleanup_temp_csv(factor_csv, is_temp)

    # -- mode: multi_sequential (per-factor full qrun) --------------------

    def _run_multi_sequential(self, context, request) -> FactorBacktestResult:
        import pandas as pd

        from alphapilot.systems.backtest.engines.qlib_workflow import QlibWorkflowEngine
        from alphapilot.systems.backtest.qlib_config import resolve_qlib_config_name

        factor_csv, is_temp = prepare_factor_csv(request)
        try:
            factor_df = pd.read_csv(
                factor_csv, usecols=["factor_name", "factor_expression"]
            ).drop_duplicates(subset="factor_name", keep="first")

            rows: list[dict] = []
            last_experiment = None
            with pickle_cache_scope("backtest"):
                for _, frow in factor_df.iterrows():
                    single_csv = _write_single_factor_csv(
                        frow["factor_name"], frow["factor_expression"]
                    )
                    try:
                        experiment, scenario, use_local = self._build_experiment(
                            context, request, single_csv
                        )
                        experiment = self._develop(scenario, experiment)
                        outcome = QlibWorkflowEngine().run(
                            experiment, use_local=use_local, run_env=experiment.run_env
                        )
                        experiment = outcome.experiment
                        experiment.qlib_config_name = resolve_qlib_config_name(experiment)
                        last_experiment = experiment
                        rows.append(
                            {"factor_name": frow["factor_name"], **_extract_portfolio_metrics(outcome.metrics)}
                        )
                    finally:
                        _cleanup_temp_csv(single_csv, True)

            leaderboard = pd.DataFrame(rows)
            if not leaderboard.empty and "IC" in leaderboard.columns:
                leaderboard = leaderboard.sort_values(
                    "IC", ascending=False, key=lambda s: s.abs()
                ).reset_index(drop=True)
            _write_sequential_leaderboard(leaderboard, last_experiment)
            return FactorBacktestResult(
                experiment=last_experiment,
                metrics=leaderboard,
                mode="multi_sequential",
                per_factor=rows,
            )
        finally:
            _cleanup_temp_csv(factor_csv, is_temp)


def run_factor_evaluation(context: Context, request: FactorBacktestRequest) -> FactorBacktestResult:
    """Module-level entry for :meth:`QlibBacktestSystem.run_factor_evaluation`."""
    return FactorEvaluationPipeline().run(context, request)
