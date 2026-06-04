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
    from alphapilot.modules.alpha_mining.pipelines.strategy_backtest import StrategyAssetBacktestRun
    from alphapilot.systems.backtest.types import (
        FactorBacktestRequest,
        FactorBacktestResult,
        FactorDefinition,
        SavedModelBacktestRequest,
    )


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
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
    ) -> None:
        """Run the autonomous factor-mining loop."""
        from alphapilot.core.utils import import_class
        from alphapilot.log import logger
        from alphapilot.modules.alpha_mining.registry import get_scenario

        use_local = self.context.config.backtest.use_local
        spec = get_scenario(scenario, command="mine")
        loop_cls = import_class(spec.loop_class_path)
        prop_setting = import_class(spec.prop_setting_path)

        resolved_qlib_config = qlib_config_name or getattr(prop_setting, "qlib_config_name", None)
        resolved_template_dir = qlib_template_dir or getattr(prop_setting, "qlib_template_dir", None)
        logger.info(
            f"[alpha_mining] scenario={scenario} use_local={use_local} "
            f"qlib_config_name={resolved_qlib_config or 'default'} "
            f"qlib_template_dir={resolved_template_dir or 'factor_template (default)'}"
        )
        if path is None:
            loop = loop_cls(
                prop_setting,
                potential_direction=direction,
                stop_event=stop_event,
                use_local=use_local,
                context=self.context,
                qlib_config_name=resolved_qlib_config,
                qlib_template_dir=resolved_template_dir,
            )
        else:
            loop = loop_cls.load(path, use_local=use_local)
            setattr(loop, "context", self.context)
            if resolved_qlib_config:
                loop.qlib_config_name = resolved_qlib_config
            if resolved_template_dir:
                loop.qlib_template_dir = resolved_template_dir
        loop.run(step_n=step_n, stop_event=stop_event)

    def run_factor_backtest_request(self, request: "FactorBacktestRequest") -> "FactorBacktestResult":
        """Orchestrate CSV/list factor backtest (propose → calculate → qlib via backtest system)."""
        from alphapilot.modules.alpha_mining.pipelines.factor_backtest import (
            run_factor_backtest_from_request,
        )
        from alphapilot.systems.backtest.types import FactorBacktestRequest, FactorBacktestResult

        return run_factor_backtest_from_request(self.context, request)

    def run_saved_model_backtest_request(
        self, request: "SavedModelBacktestRequest"
    ) -> "FactorBacktestResult":
        from alphapilot.modules.alpha_mining.pipelines.factor_backtest import (
            run_saved_model_backtest_from_request,
        )
        from alphapilot.systems.backtest.types import FactorBacktestResult, SavedModelBacktestRequest

        return run_saved_model_backtest_from_request(self.context, request)

    def run_strategy_asset_backtest(
        self,
        *,
        mode: str,
        factors: list["FactorDefinition"],
        scenario: str = "factor_backtest",
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
        qlib_data_dir: str | None = None,
        use_local: bool | None = None,
        model_pickle_path: str | None = None,
    ) -> "StrategyAssetBacktestRun":
        from alphapilot.modules.alpha_mining.pipelines.strategy_backtest import (
            run_strategy_asset_backtest,
        )

        if mode not in ("retrain", "reuse_model"):
            raise ValueError(f"Unsupported mode: {mode!r}")
        return run_strategy_asset_backtest(
            self.context,
            mode=mode,  # type: ignore[arg-type]
            factors=factors,
            scenario=scenario,
            qlib_config_name=qlib_config_name,
            qlib_template_dir=qlib_template_dir,
            qlib_data_dir=qlib_data_dir,
            use_local=use_local,
            model_pickle_path=model_pickle_path,
        )

    def run_backtest(
        self,
        path: str | None = None,
        step_n: int | None = None,
        factor_path: str | None = None,
        scenario: str = "factor_backtest",
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
    ) -> None:
        """Run a single-shot factor backtest from a factor CSV."""
        from alphapilot.systems.backtest.types import FactorBacktestRequest

        if path is not None:
            raise NotImplementedError(
                "Resuming factor backtest from a saved session path is no longer supported; "
                "use --factor_path with a factor CSV instead."
            )
        if factor_path is None:
            raise ValueError("factor_path is required for alphapilot backtest.")

        self.run_factor_backtest_request(
            FactorBacktestRequest(
                factor_path=factor_path,
                scenario=scenario,
                qlib_config_name=qlib_config_name,
                qlib_template_dir=qlib_template_dir,
                use_local=self.context.config.backtest.use_local,
            )
        )

    # ---- CLI contribution ----

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "mine": self.run_mining,
            "backtest": self.run_backtest,
        }
