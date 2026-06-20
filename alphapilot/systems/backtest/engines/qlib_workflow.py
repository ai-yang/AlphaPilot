"""Qlib ``qrun`` workflow engine (model training + portfolio backtest).

Thin wrapper over :class:`QlibFactorRunner.develop` so the existing ``multi_combined``
path is byte-for-byte unchanged, while ``multi_sequential`` can reuse the same engine
per single-factor experiment.
"""

from __future__ import annotations

from typing import Any

from alphapilot.systems.backtest.engines.base import EngineOutcome


class QlibWorkflowEngine:
    """Run a full qlib ``qrun`` on a developed factor experiment."""

    name = "qlib_workflow"

    def __init__(self, scen: Any = None) -> None:
        self._scen = scen

    def run(
        self,
        exp: Any,
        *,
        use_local: bool = True,
        run_env: dict[str, str] | None = None,
    ) -> EngineOutcome:
        from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner

        runner = QlibFactorRunner(self._scen if self._scen is not None else getattr(exp, "scen", None))
        exp = runner.develop(exp, use_local=use_local, run_env=run_env)
        return EngineOutcome(metrics=getattr(exp, "result", None), experiment=exp)
