"""Minimal qlib scenario for factor evaluation (no LLM prompts)."""

from __future__ import annotations

from pathlib import Path

from alphapilot.core.experiment import Task
from alphapilot.core.scenario import Scenario
from alphapilot.systems.backtest.qlib.template_paths import resolve_qlib_template_dir


class QlibFactorEvaluationScenario(Scenario):
    """Scenario stub used by :class:`FactorCoder` during CSV factor evaluation."""

    def __init__(
        self,
        *,
        use_local: bool = True,
        qlib_template_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.use_local = use_local
        self.qlib_template_dir = resolve_qlib_template_dir(qlib_template_dir)

    @property
    def background(self) -> str:
        return "Qlib factor evaluation (user-supplied expressions)."

    @property
    def interface(self) -> str:
        return ""

    @property
    def output_format(self) -> str:
        return ""

    @property
    def simulator(self) -> str:
        return ""

    @property
    def rich_style_description(self) -> str:
        return "Factor evaluation backtest"

    @property
    def experiment_setting(self) -> str | None:
        return None

    def get_scenario_all_desc(
        self,
        task: Task | None = None,
        filtered_tag: str | None = None,
        simple_background: bool | None = None,
    ) -> str:
        return self.background
