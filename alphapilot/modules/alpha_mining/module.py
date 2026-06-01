"""AlphaMiningModule: AlphaPilot factor mining as a pluggable module.

The module owns the factor-mining and single-shot backtest workflows. It
resolves loop classes + prop settings via the scenario registry and runs
them, reading runtime knobs (``use_local``) from the engine config. The
backtest artifacts are surfaced through the backtest system's result
store, demonstrating cross-system orchestration via the context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class AlphaMiningModule(BaseModule):
    """LLM-driven alpha factor mining + factor backtest."""

    name = "alpha_mining"

    def setup(self, context: "Context") -> None:
        self.context = context

    # ---- Workflows ----

    def run_mining(
        self,
        path: str | None = None,
        step_n: int | None = None,
        direction: str | None = None,
        stop_event: Any = None,
        scenario: str = "alpha_factor_mining",
    ) -> None:
        """Run the autonomous factor-mining loop."""
        from alphapilot.core.utils import import_class
        from alphapilot.log import logger
        from alphapilot.modules.alpha_mining.registry import get_scenario

        use_local = self.context.config.backtest.use_local
        spec = get_scenario(scenario, command="mine")
        loop_cls = import_class(spec.loop_class_path)
        prop_setting = import_class(spec.prop_setting_path)

        logger.info(
            f"[alpha_mining] scenario={scenario} use_local={use_local}"
        )
        if path is None:
            loop = loop_cls(
                prop_setting,
                potential_direction=direction,
                stop_event=stop_event,
                use_local=use_local,
                context=self.context,
            )
        else:
            loop = loop_cls.load(path, use_local=use_local)
            setattr(loop, "context", self.context)
        loop.run(step_n=step_n, stop_event=stop_event)

    def run_backtest(
        self,
        path: str | None = None,
        step_n: int | None = None,
        factor_path: str | None = None,
        scenario: str = "factor_backtest",
    ) -> None:
        """Run a single-shot factor backtest from a factor CSV/session."""
        from alphapilot.systems.backtest.types import FactorBacktestRequest

        if path is None and factor_path:
            self.context.backtest().run_factor_backtest(
                FactorBacktestRequest(
                    factor_path=factor_path,
                    scenario=scenario,
                    use_local=self.context.config.backtest.use_local,
                )
            )
            return

        from alphapilot.core.utils import import_class
        from alphapilot.modules.alpha_mining.registry import get_scenario

        spec = get_scenario(scenario, command="backtest")
        loop_cls = import_class(spec.loop_class_path)
        prop_setting = import_class(spec.prop_setting_path)

        if path is None:
            loop = loop_cls(
                prop_setting,
                factor_path=factor_path,
                context=self.context,
                use_local=self.context.config.backtest.use_local,
            )
        else:
            loop = loop_cls.load(path)
            setattr(loop, "context", self.context)
            setattr(loop, "use_local", self.context.config.backtest.use_local)
        loop.run(step_n=step_n)

    # ---- CLI contribution ----

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "mine": self.run_mining,
            "backtest": self.run_backtest,
        }
