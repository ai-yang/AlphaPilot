"""Signal (IC) engine: per-factor IC / RankIC / ICIR without ``qrun`` or a model.

Reuses the existing factor-calculation path (``QlibFactorRunner.process_factor_data``) to
get factor values, plus a trivial ``$close`` pseudo-factor computed in the same pass to
derive the forward-return label (perfectly index-aligned, no ``qlib.init``). The DSL has no
``Ref``/future shift, so the label is computed in pandas as
``shift(-2)/shift(-1) - 1`` per instrument — matching the standard
``Ref($close,-2)/Ref($close,-1)-1`` qlib label.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.log import logger
from alphapilot.systems.backtest.engines.base import EngineOutcome

#: Pseudo-factor name injected by the pipeline so the engine can build the label.
CLOSE_TASK_NAME = "__close__"
LEADERBOARD_FILE = "factor_ic_leaderboard.csv"


def make_close_task() -> Any:
    """A ``$close`` pseudo-factor task, computed alongside the real factors."""
    from alphapilot.components.coder.factor_coder.factor import FactorTask

    return FactorTask(
        factor_name=CLOSE_TASK_NAME,
        factor_description="",
        factor_formulation="",
        factor_expression="$close",
        variables="",
    )


def _safe_ratio(num: float, den: float) -> float:
    if den is None or not math.isfinite(den) or den == 0:
        return float("nan")
    return float(num / den)


def _resolve_levels(index: pd.MultiIndex) -> tuple[str | int, str | int]:
    """Return ``(datetime_level, instrument_level)`` names for a factor frame index."""
    names = list(index.names)
    if "datetime" in names:
        dt = "datetime"
    else:
        dt = names[0]
    inst_candidates = [n for n in names if n != dt]
    inst = inst_candidates[0] if inst_candidates else names[-1]
    return dt, inst


def compute_forward_return_label(close: pd.Series, inst_level: str | int) -> pd.Series:
    """Standard next-period forward return: ``close.shift(-2)/close.shift(-1) - 1`` per stock."""
    grouped = close.groupby(level=inst_level)
    return grouped.shift(-2) / grouped.shift(-1) - 1.0


def _per_factor_ic(factor: pd.Series, label: pd.Series, dt_level: str | int) -> dict[str, Any]:
    pair = pd.concat([factor.rename("f"), label.rename("y")], axis=1).dropna()
    if pair.empty:
        return {"IC": float("nan"), "RankIC": float("nan"), "ICIR": float("nan"),
                "RankICIR": float("nan"), "n_days": 0}
    daily = pair.groupby(level=dt_level)
    ic = daily.apply(lambda g: g["f"].corr(g["y"]))
    rank_ic = daily.apply(lambda g: g["f"].corr(g["y"], method="spearman"))
    return {
        "IC": float(ic.mean()),
        "RankIC": float(rank_ic.mean()),
        "ICIR": _safe_ratio(ic.mean(), ic.std()),
        "RankICIR": _safe_ratio(rank_ic.mean(), rank_ic.std()),
        "n_days": int(ic.notna().sum()),
    }


def compute_factor_ic_table(factor_frame: pd.DataFrame) -> pd.DataFrame:
    """Per-factor IC leaderboard from a frame whose columns include ``CLOSE_TASK_NAME``.

    ``factor_frame`` is indexed by ``(datetime, instrument)``; every column except the close
    pseudo-factor is treated as a factor to score against the forward-return label.
    """
    if CLOSE_TASK_NAME not in factor_frame.columns:
        raise ValueError(
            f"single_ic requires the '{CLOSE_TASK_NAME}' pseudo-factor column to build the label; "
            f"got columns {list(factor_frame.columns)}"
        )
    dt_level, inst_level = _resolve_levels(factor_frame.index)
    label = compute_forward_return_label(factor_frame[CLOSE_TASK_NAME], inst_level)

    rows: list[dict[str, Any]] = []
    for col in factor_frame.columns:
        if col == CLOSE_TASK_NAME:
            continue
        row = {"factor_name": col}
        row.update(_per_factor_ic(factor_frame[col], label, dt_level))
        rows.append(row)

    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values("IC", ascending=False, key=lambda s: s.abs()).reset_index(drop=True)
    return table


class QlibSignalEngine:
    """Compute per-factor IC/RankIC/ICIR; no ``qrun``, no model training."""

    name = "qlib_signal"

    def run(
        self,
        exp: Any,
        *,
        use_local: bool = True,
        run_env: dict[str, str] | None = None,
    ) -> EngineOutcome:
        from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner

        runner = QlibFactorRunner(getattr(exp, "scen", None))
        factor_frame = runner.process_factor_data(exp)
        table = compute_factor_ic_table(factor_frame)

        try:
            ws = Path(exp.experiment_workspace.workspace_path)
            ws.mkdir(parents=True, exist_ok=True)
            table.to_csv(ws / LEADERBOARD_FILE, index=False)
            logger.info(f"[single_ic] wrote IC leaderboard ({len(table)} factors) -> {ws / LEADERBOARD_FILE}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[single_ic] failed to write IC leaderboard: {exc}")

        per_factor = table.to_dict("records")
        exp.result = table
        return EngineOutcome(metrics=table, per_factor=per_factor, experiment=exp)
