"""The public validator and generated factor runtime must accept the same signs."""
import numpy as np
import pandas as pd
import pytest

from alphapilot.components.coder.factor_coder import function_lib as fl
from alphapilot.components.coder.factor_coder.expr_parser import parse_expression as compile_expression
from alphapilot.components.coder.factor_coder.factor_ast import (
    ExpressionSemanticError,
    validate_expression_semantics,
)


@pytest.mark.parametrize("expression,expected", [
    ("ZSCORE(-TS_SUM($return,5))", lambda data: fl.ZSCORE(-fl.TS_SUM(data["return"], 5))),
    ("-$close", lambda data: -data["close"]),
    ("+$close", lambda data: data["close"]),
    ("-($close-$open)", lambda data: -(data["close"] - data["open"])),
    ("--$close", lambda data: data["close"]),
    ("2*-$close", lambda data: -2 * data["close"]),
    ("$close--$open", lambda data: data["close"] + data["open"]),
    ("TS_SUM($return,+5)", lambda data: fl.TS_SUM(data["return"], 5)),
])
def test_unary_signs_validate_and_compute_identically(expression, expected):
    index = pd.MultiIndex.from_product(
        [pd.date_range("2024-01-01", periods=6), ["AAA", "BBB", "CCC"]],
        names=["datetime", "instrument"],
    )
    data = {
        "return": pd.Series(np.arange(18, dtype=float) / 100, index=index),
        "close": pd.Series(np.arange(18, dtype=float) + 10, index=index),
        "open": pd.Series(np.arange(18, dtype=float) * 2 + 5, index=index),
    }
    validate_expression_semantics(expression)
    compiled = compile_expression(expression)
    for name in data:
        compiled = compiled.replace("$" + name, f"data[{name!r}]")
    actual = eval(compiled, {"__builtins__": {}, "data": data,
                            "ZSCORE": fl.ZSCORE, "TS_SUM": fl.TS_SUM,
                            "ADD": fl.ADD, "SUBTRACT": fl.SUBTRACT})
    pd.testing.assert_series_equal(actual, expected(data))


@pytest.mark.parametrize("expression,code", [
    ("DELAY($close,-1)", "future_looking_lag"),
    ("DELAY($close,-(+1))", "future_looking_lag"),
    ("TS_SUM($close,-5)", "invalid_window"),
    ("TS_SUM($close,-$open)", "invalid_integer_argument"),
])
def test_unary_signs_do_not_bypass_temporal_validation(expression, code):
    with pytest.raises(ExpressionSemanticError) as caught:
        validate_expression_semantics(expression)
    assert caught.value.code == code


@pytest.mark.parametrize("expression", ["$close**2", "$close//2", "$close;print(1)", "$close.trailing"])
def test_runtime_compiler_rejects_invalid_operators_and_trailing_syntax(expression):
    with pytest.raises(ValueError):
        compile_expression(expression)
