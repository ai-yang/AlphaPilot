"""AlphaMiningModule: AlphaPilot factor mining as a pluggable module.

The module owns the factor-mining and single-shot backtest workflows. It
resolves loop classes + prop settings via the scenario registry and runs
them, reading runtime knobs (``use_local``) from the engine config. The
backtest artifacts are surfaced through the backtest system's result
store, demonstrating cross-system orchestration via the context.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.core.path_safety import ensure_child_path
from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context
    from alphapilot.systems.backtest.types import (
        FactorBacktestRequest,
        FactorBacktestResult,
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
        market: str | None = None,
    ) -> None:
        """Run the autonomous factor-mining loop."""
        from alphapilot.core.utils import import_class
        from alphapilot.log import logger
        from alphapilot.modules.alpha_mining.registry import get_scenario
        from alphapilot.systems.data.factor_h5 import apply_context_env, prepare_factor_data_context
        from alphapilot.systems.run_workspace import run_workspace

        use_local = self.context.config.backtest.use_local
        spec = get_scenario(scenario, command="mine")
        loop_cls = import_class(spec.loop_class_path)
        prop_setting = import_class(spec.prop_setting_path)

        resolved_qlib_config = qlib_config_name or getattr(prop_setting, "qlib_config_name", None)
        resolved_template_dir = qlib_template_dir or getattr(prop_setting, "qlib_template_dir", None)
        bt_cfg = self.context.config.backtest

        # Prepare this run's factor h5 context (market/spec cache) and publish it via env so the
        # mining scenario's source-data description and every factor execution use this data.
        factor_data_ctx = prepare_factor_data_context(
            market=market,
            qlib_dir=str(self.context.config.data.qlib_data_dir),
            use_local=use_local,
        )
        apply_context_env(factor_data_ctx)

        logger.info(
            f"[alpha_mining] scenario={scenario} use_local={use_local} "
            f"qlib_config_name={resolved_qlib_config or 'default'} "
            f"qlib_template_dir={resolved_template_dir or 'factor_template (default)'} "
            f"market={factor_data_ctx.spec.market} factor_data_spec={factor_data_ctx.fingerprint} "
            f"pickle_cache_mine={bt_cfg.pickle_cache_dir_mine}"
        )
        # All factor/experiment workspaces this run creates land under runs/<id>/workspaces/
        # (the override must be active before the loop builds any workspace).
        with run_workspace(
            command="mine",
            market=factor_data_ctx.spec.market,
            scenario=scenario,
            qlib_config_name=resolved_qlib_config,
            qlib_template_dir=resolved_template_dir,
            factor_data_ctx=factor_data_ctx,
        ):
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
            loop.factor_data_context = factor_data_ctx
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

    @staticmethod
    def _parse_yaml_params(raw: str | dict | None) -> dict | None:
        """Parse ``--yaml_params`` (JSON string, ``.json``/``.yaml`` file path, or dict)."""
        if raw is None or isinstance(raw, dict):
            return raw
        import json

        text = str(raw).strip()
        if not text:
            return None
        candidate = Path(text).expanduser()
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8")
            if candidate.suffix.lower() in (".yaml", ".yml"):
                import yaml

                return yaml.safe_load(content)
            return json.loads(content)
        return json.loads(text)

    def run_backtest(
        self,
        path: str | None = None,
        step_n: int | None = None,
        factor_path: str | None = None,
        scenario: str = "factor_backtest",
        qlib_config_name: str | None = None,
        qlib_template_dir: str | None = None,
        mode: str = "multi_combined",
        yaml_params: str | None = None,
        market: str | None = None,
    ) -> None:
        """Run a single-shot factor backtest from a factor CSV.

        ``mode``: ``multi_combined`` (default) | ``single_ic`` | ``multi_sequential``.
        ``yaml_params``: optional JSON string / file path overriding model / strategy / dataset.
        ``market``: instrument pool for the factor h5 spec (default resolves from yaml/default).
        """
        from alphapilot.systems.backtest.types import FactorBacktestRequest
        from alphapilot.systems.data.factor_h5 import resolve_market
        from alphapilot.systems.run_workspace import run_workspace

        if path is not None:
            raise NotImplementedError(
                "Resuming factor backtest from a saved session path is no longer supported; "
                "use --factor_path with a factor CSV instead."
            )
        if factor_path is None:
            raise ValueError("factor_path is required for alphapilot backtest.")

        parsed_yaml = self._parse_yaml_params(yaml_params)
        # The h5 context is built inside the pipeline (_build_experiment, which attaches it to the
        # active run); resolve the market here only to name the run dir.
        run_market = resolve_market(explicit=market, yaml_params=parsed_yaml)
        with run_workspace(
            command="backtest",
            market=run_market,
            scenario=scenario,
            qlib_config_name=qlib_config_name,
            qlib_template_dir=qlib_template_dir,
        ):
            self.run_factor_backtest_request(
                FactorBacktestRequest(
                    factor_path=factor_path,
                    scenario=scenario,
                    qlib_config_name=qlib_config_name,
                    qlib_template_dir=qlib_template_dir,
                    use_local=self.context.config.backtest.use_local,
                    mode=mode,
                    yaml_params=parsed_yaml,
                    market=market,
                )
            )

    # ---- Mining log session management ----

    def list_mining_sessions(self) -> list[str]:
        """Return mining log session folder names under the configured log root."""
        from alphapilot.log.ui.session import filter_log_folders

        log_root = Path(self.context.config.log_dir)
        return [p.name for p in filter_log_folders(log_root)]

    def delete_mining_session(self, session: str) -> bool:
        """Delete a mining log session directory under the configured log root."""
        log_root = Path(self.context.config.log_dir).expanduser().resolve()
        candidate = Path(session).expanduser()
        if candidate.is_absolute() or len(candidate.parts) > 1:
            target = candidate.resolve()
        else:
            target = (log_root / session).resolve()
        ensure_child_path(log_root, target)
        if target == log_root:
            raise ValueError(f"Refusing to delete log root: {log_root}")
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        return True

    # ---- Run workspace management ----

    def list_runs(self) -> list[dict[str, Any]]:
        """List per-task run directories (newest first) with their manifest summary."""
        from alphapilot.systems.run_workspace import list_runs

        return list_runs()

    def delete_run(self, run_id: str) -> bool:
        """Delete a per-task run directory (shared cache symlink targets are preserved)."""
        from alphapilot.systems.run_workspace import delete_run

        return delete_run(run_id)

    # ---- CLI contribution ----

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "mine": self.run_mining,
            "backtest": self.run_backtest,
            "list_mine_logs": self.list_mining_sessions,
            "delete_mine_log": self.delete_mining_session,
            "list_runs": self.list_runs,
            "delete_run": self.delete_run,
        }
