"""AlphaForge Expression -> alphapilot DSL translator tests.

Every translated string must parse cleanly via the alphapilot factor DSL
parser (``parse_expression``); untranslatable operators must be reported as
such rather than producing a bad string.
"""

import pytest

# Importing the shared base puts the vendored ``alphagen`` package on sys.path.
import alphapilot.modules.alphaforge  # noqa: F401
from alphapilot.modules.alphaforge.translate import (
    UntranslatableError,
    translate,
    try_translate,
)
from alphapilot.components.coder.factor_coder.expr_parser import parse_expression

from alphagen.data.expression import (
    Abs, Add, CSRank, Constant, Div, Greater, Inv, Less, Log, Mul, Pow, Ref,
    S_log1p, Sign, Sub,
    ts_corr, ts_cov, ts_delta, ts_div, ts_ema, ts_ir, ts_mad, ts_max,
    ts_max_diff, ts_mean, ts_med, ts_min, ts_min_diff, ts_min_max_diff,
    ts_pctchange, ts_rank, ts_std, ts_sum, ts_var, ts_wma,
    ts_kurt, ts_skew,
)
from alphagen_generic.features import close, high, low, open_, volume, vwap


def _parses(dsl: str) -> bool:
    """parse_expression returns a non-empty translated form without raising."""
    out = parse_expression(dsl)
    return isinstance(out, str) and len(out) > 0


# Representative tree per supported operator category.
TRANSLATABLE_CASES = [
    close,
    Constant(2.0),
    Add(close, open_),
    Sub(high, low),
    Mul(close, Constant(-0.01)),          # negative constant -> must be wrapped
    Div(close, open_),
    Pow(close, Constant(2.0)),            # -> POW(...) (no infix **)
    Abs(Sub(close, open_)),
    Sign(close),
    Log(volume),
    Inv(close),
    CSRank(close),
    S_log1p(close),                       # -> MULTIPLY(SIGN(.),LOG(ABS(.)))
    Ref(close, 5),
    ts_mean(close, 10),
    ts_sum(volume, 5),
    ts_std(close, 20),
    ts_var(close, 10),
    ts_max(high, 10),
    ts_min(low, 10),
    ts_med(close, 10),
    ts_mad(close, 10),
    ts_rank(close, 10),
    ts_delta(close, 5),
    ts_pctchange(close, 5),
    ts_wma(close, 10),
    ts_ema(close, 10),
    ts_div(close, 5),                     # decomposed
    ts_ir(close, 10),                     # decomposed
    ts_max_diff(high, 10),                # decomposed
    ts_min_diff(low, 10),                 # decomposed
    ts_min_max_diff(close, 10),           # decomposed
    ts_cov(close, volume, 10),
    ts_corr(close, volume, 10),
    Greater(close, open_),                # -> MAX(.,.)
    Less(close, open_),                   # -> MIN(.,.)
    # nested / realistic
    CSRank(Div(ts_corr(close, volume, 10), ts_std(close, 20))),
    Add(Mul(ts_mean(close, 5), Constant(2.0)), ts_delta(volume, 1)),
]


@pytest.mark.parametrize("expr", TRANSLATABLE_CASES, ids=lambda e: type(e).__name__)
def test_translation_parses(expr):
    dsl = translate(expr)
    assert "$" in dsl or dsl.replace(".", "").replace("-", "").isdigit() or "(" in dsl
    assert _parses(dsl), f"DSL did not parse: {dsl!r}"


def test_feature_prefix_and_names():
    assert translate(close) == "$close"
    assert translate(vwap) == "$vwap"
    assert translate(open_) == "$open"


def test_pow_is_function_not_infix():
    assert translate(Pow(close, Constant(2.0))) == "POW($close,2)"


def test_negative_constant_wrapped():
    # would otherwise yield "$close*-0.01" which the parser rejects
    assert translate(Mul(close, Constant(-0.01))) == "($close*(-0.01))"


def test_decomposition_shapes():
    assert translate(ts_div(close, 5)) == "DIVIDE($close,DELAY($close,5))"
    assert translate(ts_ir(close, 10)) == "DIVIDE(TS_MEAN($close,10),TS_STD($close,10))"


@pytest.mark.parametrize("expr", [ts_skew(close, 10), ts_kurt(close, 10)])
def test_untranslatable_raise(expr):
    with pytest.raises(UntranslatableError):
        translate(expr)
    assert try_translate(expr) is None
