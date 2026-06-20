"""Backtest engine protocol.

An engine consumes a *developed* factor experiment (factor values already computable
via its ``sub_workspace_list``) and produces an :class:`EngineOutcome`. Two concrete
engines exist:

- :class:`~alphapilot.systems.backtest.engines.qlib_workflow.QlibWorkflowEngine` — runs a
  full qlib ``qrun`` (model training + portfolio backtest). Used by ``multi_combined`` and
  ``multi_sequential``.
- :class:`~alphapilot.systems.backtest.engines.qlib_signal.QlibSignalEngine` — computes
  per-factor IC / RankIC / ICIR without ``qrun`` or model training. Used by ``single_ic``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class EngineOutcome:
    """Unified engine result.

    ``metrics`` carries portfolio-level metrics (a ``pd.Series`` from ``qlib_res.csv``) for
    the workflow engine, or the per-factor leaderboard frame for the signal engine.
    ``per_factor`` is the per-factor row list (``single_ic`` / ``multi_sequential``).
    """

    metrics: Any = None
    per_factor: list[dict] | None = None
    experiment: Any = None


@runtime_checkable
class BacktestEngine(Protocol):
    """Protocol implemented by all backtest engines."""

    name: str

    def run(
        self,
        exp: Any,
        *,
        use_local: bool = True,
        run_env: dict[str, str] | None = None,
    ) -> EngineOutcome:
        """Evaluate ``exp`` and return an :class:`EngineOutcome`."""
        ...
