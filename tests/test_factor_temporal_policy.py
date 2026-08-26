from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from alphapilot.components.coder.factor_coder.factor import FactorTask
from alphapilot.components.coder.factor_coder.factor_ast import (
    ExpressionSemanticError,
    TemporalValidationPolicy,
    validate_expression_semantics,
)
from alphapilot.systems.factor.regulator.factor_regulator import FactorRegulator


def _bounded_policy(*, allow_unbounded_causal: bool = False) -> TemporalValidationPolicy:
    return TemporalValidationPolicy.bounded(
        min_window=2,
        max_window=60,
        max_lookback=60,
        allow_unbounded_causal=allow_unbounded_causal,
    )


def _semantic_error(expression: str) -> ExpressionSemanticError:
    with pytest.raises(ExpressionSemanticError) as caught:
        validate_expression_semantics(expression)
    return caught.value


def test_temporal_policy_is_frozen_and_bounded_limits_are_opt_in() -> None:
    default_policy = TemporalValidationPolicy()
    with pytest.raises(FrozenInstanceError):
        default_policy.min_window = 2  # type: ignore[misc]

    one_period = validate_expression_semantics("TS_MEAN($close, 1)")
    long_history = validate_expression_semantics(
        "TS_MEAN(DELAY($close, 80), 100)"
    )
    assert (one_period.lookback_kind, one_period.lookback) == ("finite", 0)
    assert (long_history.lookback_kind, long_history.lookback) == ("finite", 179)

    with pytest.raises(ExpressionSemanticError) as caught:
        validate_expression_semantics(
            "TS_MEAN($close, 1)", policy=_bounded_policy()
        )
    assert caught.value.code == "window_out_of_policy"

    with pytest.raises(ExpressionSemanticError) as caught:
        validate_expression_semantics(
            "TS_MEAN(DELAY($close, 22), 40)", policy=_bounded_policy()
        )
    assert caught.value.code == "lookback_out_of_policy"


@pytest.mark.parametrize("function_name", ["DELAY", "DELTA", "TS_PCTCHANGE"])
def test_public_policy_rejects_future_looking_lags(function_name: str) -> None:
    error = _semantic_error(f"{function_name}($close, -1)")
    assert error.code == "future_looking_lag"


def test_full_history_percentile_is_noncausal_but_rolling_form_is_finite() -> None:
    error = _semantic_error("PERCENTILE($close, 0.5)")
    assert error.code == "noncausal_percentile"

    analysis = validate_expression_semantics("PERCENTILE($close, 0.5, 20)")
    assert (analysis.lookback_kind, analysis.lookback) == ("finite", 19)


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ("DOES_NOT_EXIST($close)", "unknown_function"),
        ("calculate_beta($close, $open)", "unknown_function"),
        ("mean($close)", "unknown_function"),
        ("Ts_Mean($close, 5)", "unknown_function"),
        ("Mean($close, 5)", "unknown_function"),
        ("$ABS($close)", "invalid_function_name"),
        ("ABS()", "invalid_arity"),
        ("ABS($close, 1)", "invalid_arity"),
        ("MAX($close, $open, $high, $low)", "invalid_arity"),
        ("EMA($close)", "invalid_arity"),
        ("SUMIF($close, 5)", "invalid_arity"),
        ("BB_UPPER($close)", "invalid_arity"),
    ],
)
def test_function_whitelist_and_arity_fail_with_stable_codes(
    expression: str, code: str
) -> None:
    assert _semantic_error(expression).code == code


@pytest.mark.parametrize(
    ("expression", "expected_lookback"),
    [
        ("TS_MEAN($close)", 4),
        ("TS_STD($close)", 19),
        ("TS_CORR($close, $volume)", 4),
        ("TS_VAR($close, 5, 0)", 4),
        ("TS_QUANTILE($close)", 4),
        ("REGBETA($close, SEQUENCE(5))", 4),
        ("SMA($close, 20)", 19),
        ("MAX($close, $open, 0)", 0),
    ],
)
def test_runtime_defaults_and_supported_arities_are_analyzed(
    expression: str, expected_lookback: int
) -> None:
    analysis = validate_expression_semantics(expression)
    assert analysis.lookback_kind == "finite"
    assert analysis.lookback == expected_lookback


@pytest.mark.parametrize(
    ("expression", "expected_lookback"),
    [
        ("Mean($close, 5)", 4),
        ("Std($close, 20)", 19),
        ("Ref($close, 3)", 3),
        ("Rank($close)", 0),
    ],
)
def test_legacy_qlib_aliases_are_explicit_and_case_sensitive(
    expression: str, expected_lookback: int
) -> None:
    analysis = validate_expression_semantics(
        expression, allow_legacy_aliases=True
    )
    assert analysis.lookback_kind == "finite"
    assert analysis.lookback == expected_lookback

    function_name = expression.split("(", 1)[0]
    wrong_arity = f"{function_name}($close)" if function_name != "Rank" else "Rank()"
    with pytest.raises(ExpressionSemanticError) as caught:
        validate_expression_semantics(
            wrong_arity, allow_legacy_aliases=True
        )
    assert caught.value.code == "invalid_arity"


@pytest.mark.parametrize(
    "expression",
    [
        "SEQUENCE(100)",
        "ADD(SEQUENCE(100), 1)",
        "TS_CORR($close, ADD(SEQUENCE(100), 1))",
        "TS_COVARIANCE($close, MULTIPLY(SEQUENCE(100), 2))",
        "REGBETA(SEQUENCE(100), $close)",
    ],
)
def test_sequence_rejects_indirect_or_wrong_argument_contexts(
    expression: str,
) -> None:
    error = _semantic_error(expression)
    assert error.code == "invalid_sequence_context"


@pytest.mark.parametrize(
    "expression",
    [
        "TS_CORR($close, SEQUENCE(5))",
        "TS_COVARIANCE($close, SEQUENCE(5))",
        "REGBETA($close, SEQUENCE(5))",
        "REGRESI($close, SEQUENCE(5))",
    ],
)
def test_sequence_is_allowed_as_the_documented_direct_regressor(
    expression: str,
) -> None:
    analysis = validate_expression_semantics(expression)
    assert analysis.lookback_kind == "finite"
    assert analysis.lookback == 4


@pytest.mark.parametrize("function_name", ["TS_CORR", "TS_COVARIANCE"])
def test_sequence_operand_controls_runtime_correlation_window(
    function_name: str,
) -> None:
    default_window = validate_expression_semantics(
        f"{function_name}($close, SEQUENCE(17))"
    )
    overridden_window = validate_expression_semantics(
        f"{function_name}(DELAY($close, 3), SEQUENCE(17), 5)"
    )

    assert (default_window.lookback_kind, default_window.lookback) == ("finite", 16)
    assert (overridden_window.lookback_kind, overridden_window.lookback) == (
        "finite",
        19,
    )


@pytest.mark.parametrize(
    "expression",
    [
        "EMA($close, 20)",
        "SMA($close, 20, 2)",
        "MACD($close)",
        "MACD($close, 12, 26)",
        "RSI($close)",
        "TS_MEAN(EMA($close, 20), 5)",
    ],
)
def test_ewm_operators_are_typed_as_unbounded_causal(expression: str) -> None:
    analysis = validate_expression_semantics(expression)
    assert analysis.lookback_kind == "unbounded_causal"
    assert analysis.lookback is None

    with pytest.raises(ExpressionSemanticError) as caught:
        validate_expression_semantics(expression, policy=_bounded_policy())
    assert caught.value.code == "unbounded_lookback"


def test_bounded_policy_can_explicitly_allow_unbounded_causal_operators() -> None:
    analysis = validate_expression_semantics(
        "EMA($close, 20)",
        policy=_bounded_policy(allow_unbounded_causal=True),
    )
    assert analysis.lookback_kind == "unbounded_causal"
    assert analysis.lookback is None


def test_regulator_surfaces_temporal_analysis_and_semantic_error_codes() -> None:
    regulator = FactorRegulator()

    ok, evaluation, message, code = regulator.check_expression_detailed(
        "EMA($close, 20)"
    )
    assert ok is True
    assert message is None and code is None
    assert evaluation is not None
    assert evaluation["lookback"] is None
    assert evaluation["lookback_kind"] == "unbounded_causal"

    invalid = regulator.validate_expression("ABS($close, 1)")
    assert invalid.acceptable is False
    assert invalid.code == "invalid_arity"

    bypass = regulator.validate_expression("$ABS($close)")
    assert bypass.acceptable is False
    assert bypass.code == "invalid_function_name"


def test_regulator_explicitly_owns_the_legacy_qlib_dialect_boundary() -> None:
    compatible = FactorRegulator()
    strict = FactorRegulator(allow_legacy_aliases=False)

    assert compatible.allow_legacy_aliases is True
    ok, evaluation, message, code = compatible.check_expression_detailed(
        "Mean($close, 5)"
    )
    assert ok is True
    assert evaluation is not None and evaluation["lookback"] == 4
    assert message is None and code is None

    rejected = strict.validate_expression("Mean($close, 5)")
    assert rejected.acceptable is False
    assert rejected.code == "unknown_function"


def test_evolving_strategy_uses_public_causal_defaults() -> None:
    from alphapilot.components.coder.factor_coder import evolving_strategy

    one_period_code = evolving_strategy._render_factor_code(
        expression="TS_MEAN($close, 1)", factor_name="one_period"
    )
    ewm_code = evolving_strategy._render_factor_code(
        expression="EMA($close, 20)", factor_name="ewm"
    )

    assert evolving_strategy._expression_from_rendered_code(one_period_code) == (
        "TS_MEAN($close, 1)"
    )
    assert evolving_strategy._expression_from_rendered_code(ewm_code) == (
        "EMA($close, 20)"
    )

    with pytest.raises(ExpressionSemanticError) as caught:
        evolving_strategy._render_factor_code(
            expression="Mean($close, 5)", factor_name="legacy"
        )
    assert caught.value.code == "unknown_function"


@pytest.mark.parametrize(
    "response",
    [
        None,
        "not json",
        "[]",
        '{}',
        '{"expr": 3}',
        '{"expr": "   "}',
    ],
)
def test_repair_response_schema_has_one_stable_error(response: object) -> None:
    from alphapilot.components.coder.factor_coder import evolving_strategy

    with pytest.raises(ExpressionSemanticError) as caught:
        evolving_strategy._repaired_expression_from_response(response)
    assert caught.value.code == "invalid_repair_response"

    assert evolving_strategy._repaired_expression_from_response(
        '{"expr": " TS_MEAN($close, 5) "}'
    ) == "TS_MEAN($close, 5)"


def _task(name: str, expression: str) -> FactorTask:
    return FactorTask(
        factor_name=name,
        factor_description="test factor",
        factor_formulation="test formulation",
        factor_expression=expression,
        variables={"$close": "close"},
    )


def test_repair_retries_invalid_json_schema_and_noncausal_expressions(
    monkeypatch,
) -> None:
    from alphapilot.components.coder.factor_coder import evolving_strategy

    target_task = _task("repair_target", "TS_MEAN($close, 20)")
    task_key = target_task.get_task_information()
    failed = SimpleNamespace(
        implementation=SimpleNamespace(code='expr = "TS_MEAN($close, 20)"'),
        feedback="runtime failure",
    )
    successful_task = _task("successful", "TS_STD($close, 20)")
    successful = SimpleNamespace(
        target_task=successful_task,
        implementation=SimpleNamespace(code='expr = "TS_STD($close, 20)"'),
    )
    knowledge = SimpleNamespace(
        task_to_former_failed_traces={task_key: ([failed], None)},
        task_to_similar_task_successful_knowledge={task_key: [successful]},
    )

    class FakeLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    json.dumps([]),
                    json.dumps({"expr": 3}),
                    json.dumps({"expr": "DELAY($close, -1)"}),
                    json.dumps({"expr": "TS_MEAN($close, 10)"}),
                ]
            )
            self.prompts: list[str] = []

        def count_tokens(self, **_kwargs) -> int:
            return 1

        def chat_completion(self, *, user_prompt: str, **_kwargs) -> str:
            self.prompts.append(user_prompt)
            return next(self.responses)

    fake_llm = FakeLLM()
    monkeypatch.setattr(evolving_strategy, "get_llm", lambda **_kwargs: fake_llm)
    strategy = object.__new__(evolving_strategy.FactorParsingStrategy)
    strategy.scen = SimpleNamespace(
        get_scenario_all_desc=lambda *_args, **_kwargs: "scenario"
    )

    code = strategy.implement_one_task(target_task, knowledge)

    assert evolving_strategy._expression_from_rendered_code(code) == (
        "TS_MEAN($close, 10)"
    )
    assert len(fake_llm.prompts) == 4
    assert "rejected by the local validator" in fake_llm.prompts[1]


def test_assignment_persists_semantically_valid_repaired_expression() -> None:
    from alphapilot.components.coder.factor_coder import evolving_strategy

    proposed_task = _task("sync_target", "TS_MEAN($close, 20)")
    workspace_task = _task("sync_target", "TS_MEAN($close, 20)")

    class FakeWorkspace:
        def __init__(self) -> None:
            self.target_task = workspace_task
            self.code_dict: dict[str, str] = {}

        def inject_code(self, **files: str) -> None:
            self.code_dict.update(files)

    workspace = FakeWorkspace()
    evo = SimpleNamespace(
        sub_tasks=[proposed_task],
        sub_workspace_list=[workspace],
    )
    repaired_expression = "TS_MEAN($close, 10)"
    repaired_code = evolving_strategy._render_factor_code(
        expression=repaired_expression,
        factor_name=proposed_task.factor_name,
    )
    strategy = object.__new__(evolving_strategy.FactorParsingStrategy)

    strategy.assign_code_list_to_evo([repaired_code], evo)

    assert proposed_task.factor_expression == repaired_expression
    assert workspace.target_task.factor_expression == repaired_expression
    assert workspace.executed_factor_expression == repaired_expression
    assert workspace.code_dict["factor.py"] == repaired_code


def test_assignment_rejects_noncausal_code_before_persisting_it() -> None:
    from alphapilot.components.coder.factor_coder import evolving_strategy

    proposed_task = _task("sync_target", "TS_MEAN($close, 20)")
    workspace_task = _task("sync_target", "TS_MEAN($close, 20)")

    class FakeWorkspace:
        def __init__(self) -> None:
            self.target_task = workspace_task
            self.code_dict: dict[str, str] = {}

        def inject_code(self, **files: str) -> None:
            self.code_dict.update(files)

    workspace = FakeWorkspace()
    evo = SimpleNamespace(
        sub_tasks=[proposed_task],
        sub_workspace_list=[workspace],
    )
    unsafe_code = evolving_strategy.code_template.render(
        expression="DELAY($close, -1)",
        factor_name=proposed_task.factor_name,
    )

    with pytest.raises(ExpressionSemanticError) as caught:
        evolving_strategy._assign_factor_codes([unsafe_code], evo)

    assert caught.value.code == "future_looking_lag"
    assert proposed_task.factor_expression == "TS_MEAN($close, 20)"
    assert workspace_task.factor_expression == "TS_MEAN($close, 20)"
    assert workspace.code_dict == {}
