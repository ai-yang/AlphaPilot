from __future__ import annotations

from types import SimpleNamespace

import pytest

from alphapilot.components.coder.factor_coder.factor import FactorTask


def _task(expression: str) -> FactorTask:
    return FactorTask(
        factor_name="expression_sync",
        factor_description="test factor",
        factor_formulation="test formulation",
        factor_expression=expression,
        variables={"$close": "close"},
    )


class _Workspace:
    def __init__(self, target_task: FactorTask) -> None:
        self.target_task = target_task
        self.code_dict: dict[str, str] = {}

    def inject_code(self, **files: str) -> None:
        self.code_dict.update(files)


def test_expression_is_extracted_from_the_executable_literal() -> None:
    from alphapilot.components.coder.factor_coder.evolving_strategy import (
        _expression_from_rendered_code,
        code_template,
    )

    expression = 'ADD($close, DELAY($open, 2)) # "quoted"'
    code = code_template.render(expression=expression, factor_name="safe_name")

    assert _expression_from_rendered_code(code) == expression


@pytest.mark.parametrize(
    "code",
    [
        "expr = ''\n",
        "expr = build_expression()\n",
        "def factory():\n    expr = '$close'\n",
        "expr = '$close'\nexpr = '$open'\n",
        "expr = '$close'\nif:\n    pass\n",
    ],
)
def test_expression_extraction_rejects_ambiguous_source(code: str) -> None:
    from alphapilot.components.coder.factor_coder.evolving_strategy import (
        _expression_from_rendered_code,
    )

    with pytest.raises(ValueError):
        _expression_from_rendered_code(code)


@pytest.mark.parametrize("strategy_name", ["FactorParsingStrategy", "FactorRunningStrategy"])
def test_assignment_persists_the_expression_that_will_execute(
    strategy_name: str,
) -> None:
    from alphapilot.components.coder.factor_coder import evolving_strategy

    proposed_task = _task("TS_MEAN($close, 20)")
    workspace_task = _task("TS_MEAN($close, 20)")
    workspace = _Workspace(workspace_task)
    evo = SimpleNamespace(
        sub_tasks=[proposed_task],
        sub_workspace_list=[workspace],
    )
    executed_expression = "TS_MEAN($close, 10)"
    code = evolving_strategy.code_template.render(
        expression=executed_expression,
        factor_name=proposed_task.factor_name,
    )
    strategy = object.__new__(getattr(evolving_strategy, strategy_name))

    assert strategy.assign_code_list_to_evo([code], evo) is evo

    assert proposed_task.factor_expression == executed_expression
    assert workspace_task.factor_expression == executed_expression
    assert workspace.executed_factor_expression == executed_expression
    assert workspace.code_dict["factor.py"] == code


def test_assignment_rejects_a_partial_code_batch() -> None:
    from alphapilot.components.coder.factor_coder.evolving_strategy import (
        _assign_factor_codes,
    )

    evo = SimpleNamespace(
        sub_tasks=[_task("$close")],
        sub_workspace_list=[None],
    )

    with pytest.raises(ValueError, match="code count"):
        _assign_factor_codes([], evo)
