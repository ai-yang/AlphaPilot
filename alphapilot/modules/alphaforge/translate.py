"""Output-boundary translator: AlphaForge ``Expression`` -> alphapilot DSL.

The miners search/evaluate internally on the vendored alphagen torch engine
(fast GPU batch eval). When a factor is *kept*, we translate its typed
``Expression`` AST into alphapilot's native factor DSL string (the
``RANK(DELTA($close, 1))`` form parsed by
``alphapilot.components.coder.factor_coder.expr_parser.parse_expression``),
so the produced factors are first-class citizens of alphapilot's own factor
zoo / backtest -- no alphagen objects leak past this boundary.

We walk the AST (dispatch by node category + class name) rather than regex the
``str(expr)`` form, which is far more robust. Operators with no faithful
alphapilot equivalent (``ts_skew`` / ``ts_kurt``) raise
:class:`UntranslatableError`; the pipeline catches that and just skips the
factor. The set of operators actually emitted by each miner is configured to
stay within the translatable subset.
"""

from __future__ import annotations

# Importing this submodule imports the parent package first, which runs the
# sys.path shim in ``alphaforge/__init__.py`` -> the vendored ``alphagen``
# package becomes importable by its original name.
from alphagen.data.expression import (
    BinaryOperator,
    Constant,
    Expression,
    Feature,
    PairRollingOperator,
    RollingOperator,
    UnaryOperator,
)


class UntranslatableError(Exception):
    """Raised when an Expression has no faithful alphapilot DSL equivalent."""


# Unary: alphagen class name -> alphapilot function_lib name.
_UNARY_MAP = {
    "Abs": "ABS",
    "Sign": "SIGN",
    "Log": "LOG",      # both are log1p-style: alphapilot LOG == log(x+1)
    "Inv": "INV",
    "CSRank": "RANK",  # cross-sectional percentile rank
}

# Binary infix arithmetic (alphapilot parser supports + - * / as infix).
_BINARY_INFIX = {"Add": "+", "Sub": "-", "Mul": "*", "Div": "/"}

# Rolling (operand, dt): class name -> function_lib name.
_ROLLING_MAP = {
    "Ref": "DELAY",
    "ts_mean": "TS_MEAN",
    "ts_sum": "TS_SUM",
    "ts_std": "TS_STD",
    "ts_var": "TS_VAR",
    "ts_max": "TS_MAX",
    "ts_min": "TS_MIN",
    "ts_med": "TS_MEDIAN",
    "ts_mad": "TS_MAD",
    "ts_rank": "TS_RANK",
    "ts_delta": "DELTA",
    "ts_pctchange": "TS_PCTCHANGE",
    "ts_wma": "WMA",
    "ts_ema": "EMA",
}

# Pair rolling (lhs, rhs, dt): class name -> function_lib name.
_PAIR_MAP = {"ts_cov": "TS_COVARIANCE", "ts_corr": "TS_CORR"}


def _fmt_const(value: float) -> str:
    """Format a constant as a parser-safe token.

    Negative numbers are wrapped in parentheses so they never sit directly
    after another operator (e.g. ``$close*-0.01`` -> ``$close*(-0.01)``); the
    DSL parser rejects two adjacent arithmetic-operator characters.
    """
    f = float(value)
    s = str(int(f)) if f.is_integer() else repr(f)
    return f"({s})" if f < 0 else s


def translate(expr: Expression) -> str:
    """Translate an alphagen ``Expression`` AST into an alphapilot DSL string."""
    name = type(expr).__name__

    # ---- terminals ----
    if isinstance(expr, Feature):
        return "$" + expr._feature.name.lower()
    if isinstance(expr, Constant):
        return _fmt_const(expr._value)

    # ---- unary ----
    if isinstance(expr, UnaryOperator):
        x = translate(expr._operand)
        if name in _UNARY_MAP:
            return f"{_UNARY_MAP[name]}({x})"
        if name == "S_log1p":  # sign(x) * log1p(|x|); alphapilot LOG is log1p
            return f"MULTIPLY(SIGN({x}),LOG(ABS({x})))"
        raise UntranslatableError(f"unary operator {name!r}")

    # ---- binary ----
    if isinstance(expr, BinaryOperator):
        lhs = translate(expr._lhs)
        rhs = translate(expr._rhs)
        if name in _BINARY_INFIX:
            return f"({lhs}{_BINARY_INFIX[name]}{rhs})"
        if name == "Pow":          # no infix ** in the DSL parser
            return f"POW({lhs},{rhs})"
        if name == "Greater":      # element-wise max (binary MAX)
            return f"MAX({lhs},{rhs})"
        if name == "Less":         # element-wise min (binary MIN)
            return f"MIN({lhs},{rhs})"
        raise UntranslatableError(f"binary operator {name!r}")

    # ---- rolling (single operand + window) ----
    if isinstance(expr, RollingOperator):
        x = translate(expr._operand)
        dt = int(expr._delta_time)
        if name in _ROLLING_MAP:
            return f"{_ROLLING_MAP[name]}({x},{dt})"
        # decomposable rolling ops (no atomic equivalent in function_lib)
        if name == "ts_div":
            return f"DIVIDE({x},DELAY({x},{dt}))"
        if name == "ts_ir":
            return f"DIVIDE(TS_MEAN({x},{dt}),TS_STD({x},{dt}))"
        if name == "ts_max_diff":
            return f"({x}-TS_MAX({x},{dt}))"
        if name == "ts_min_diff":
            return f"({x}-TS_MIN({x},{dt}))"
        if name == "ts_min_max_diff":
            return f"(TS_MAX({x},{dt})-TS_MIN({x},{dt}))"
        # ts_skew / ts_kurt: no rolling skew/kurt in function_lib
        raise UntranslatableError(f"rolling operator {name!r}")

    # ---- pair rolling (lhs, rhs, window) ----
    if isinstance(expr, PairRollingOperator):
        lhs = translate(expr._lhs)
        rhs = translate(expr._rhs)
        dt = int(expr._delta_time)
        if name in _PAIR_MAP:
            return f"{_PAIR_MAP[name]}({lhs},{rhs},{dt})"
        raise UntranslatableError(f"pair-rolling operator {name!r}")

    raise UntranslatableError(f"expression node {name!r}")


def try_translate(expr: Expression) -> str | None:
    """Translate, returning ``None`` instead of raising on untranslatable nodes."""
    try:
        return translate(expr)
    except UntranslatableError:
        return None
