from pyparsing import (
    Combine,
    DelimitedList,
    Forward,
    Literal,
    OpAssoc,
    Optional,
    ParseException,
    ParseResults,
    ParserElement,
    Regex,
    Word,
    alphanums,
    alphas,
    infix_notation,
    one_of,
)
from dataclasses import dataclass
from typing import List, Literal as TypingLiteral, Union, Optional as Opt
from collections import defaultdict
import math
import sys
import pandas as pd

# Enable packrat parsing for better performance
ParserElement.enable_packrat()

# Set higher recursion limit for complex expressions
sys.setrecursionlimit(4000)

# AST Node classes
@dataclass
class Node:
    def tree_str(self, level: int = 0) -> str:
        """Return a tree-like string representation with given indent level."""
        indent = "  " * level
        return f"{indent}{self._node_str()}"
    
    def _node_str(self) -> str:
        """Basic string representation of the node for tree view."""
        return str(self)
        
    def print_tree(self):
        """Print the AST in a tree structure."""
        print(self.tree_str())

@dataclass
class VarNode(Node):
    name: str
    
    def __str__(self):
        return self.name
        
    def _node_str(self):
        return f"VAR({self.name})"

@dataclass
class NumberNode(Node):
    value: float
    
    def __str__(self):
        return str(self.value)
        
    def _node_str(self):
        return f"NUM({self.value})"

@dataclass
class FunctionNode(Node):
    name: str
    args: List[Node]
    
    def __str__(self):
        args_str = ", ".join(str(arg) for arg in self.args)
        return f"{self.name}({args_str})"
        
    def _node_str(self):
        return f"FUNC({self.name})"
        
    def tree_str(self, level: int = 0) -> str:
        indent = "  " * level
        result = [f"{indent}{self._node_str()}"]
        for arg in self.args:
            result.append(arg.tree_str(level + 1))
        return "\n".join(result)

@dataclass
class BinaryOpNode(Node):
    op: str
    left: Node
    right: Node
    
    def __str__(self):
        return f"({str(self.left)} {self.op} {str(self.right)})"
        
    def _node_str(self):
        return f"OP({self.op})"
        
    def tree_str(self, level: int = 0) -> str:
        indent = "  " * level
        result = [f"{indent}{self._node_str()}"]
        result.append(self.left.tree_str(level + 1))
        result.append(self.right.tree_str(level + 1))
        return "\n".join(result)

@dataclass
class ConditionalNode(Node):
    condition: Node
    true_expr: Node
    false_expr: Node
    
    def __str__(self):
        return f"({str(self.condition)} ? {str(self.true_expr)} : {str(self.false_expr)})"
        
    def _node_str(self):
        return "CONDITIONAL"
        
    def tree_str(self, level: int = 0) -> str:
        indent = "  " * level
        result = [f"{indent}{self._node_str()}"]
        result.append(self.condition.tree_str(level + 1))
        result.append(self.true_expr.tree_str(level + 1))
        result.append(self.false_expr.tree_str(level + 1))
        return "\n".join(result)

# Basic elements definition
var = Combine(Optional(Literal("$")) + Word(alphas, alphanums + "_"))
number = Regex(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")

# Operators definition
mul_div = one_of("* /")
add_sub = one_of("+ -")
comparison = one_of("> < >= <= == !=")
logical_and = one_of("&& &")
logical_or = one_of("|| |")
conditional = ("?", ":")

def create_var_node(tokens):
    return VarNode(tokens[0])

def create_number_node(tokens):
    return NumberNode(float(tokens[0]))

def create_function_node(tokens):
    name = tokens[0]  # function name
    args = tokens[2:-1]  # skip parentheses
    
    def unwrap(arg):
        if isinstance(arg, (list, ParseResults)):
            if len(arg) == 1:
                return unwrap(arg[0])
            return [unwrap(x) for x in arg][0]  # first element
        return arg
    
    processed_args = [unwrap(arg) for arg in args]
    # All args should be Node classes
    assert all(isinstance(arg, Node) for arg in processed_args), f"Invalid args: {processed_args}"
    return FunctionNode(name, processed_args)

def create_binary_op_node(tokens):
    tokens = tokens[0]
    def unwrap(arg):
        if isinstance(arg, (list, ParseResults)):
            if len(arg) == 1:
                return unwrap(arg[0])
            return [unwrap(x) for x in arg]
        return arg
    
    if len(tokens) == 3:
        return BinaryOpNode(tokens[1], unwrap(tokens[0]), unwrap(tokens[2]))
    
    result = unwrap(tokens[0])
    for i in range(1, len(tokens)-1, 2):
        result = BinaryOpNode(tokens[i], result, unwrap(tokens[i+1]))
    return result

def create_conditional_node(tokens):
    tokens = tokens[0]
    def unwrap(arg):
        if isinstance(arg, (list, ParseResults)):
            if len(arg) == 1:
                return unwrap(arg[0])
            return [unwrap(x) for x in arg]
        return arg
    
    return ConditionalNode(
        unwrap(tokens[0]),
        unwrap(tokens[2]),
        unwrap(tokens[4])
    )

# Expression parser definition
expr = Forward()

# Basic elements
var.set_parse_action(create_var_node)
number.set_parse_action(create_number_node)

# Function call
function_call = var + "(" + Optional(DelimitedList(expr)) + ")"
function_call.set_parse_action(create_function_node)

# Operands
operand = function_call | var | number | ("(" + expr + ")").set_parse_action(lambda tokens: tokens[1])

# Complete expression
expr <<= infix_notation(
    operand,
    [
        (mul_div, 2, OpAssoc.LEFT, create_binary_op_node),
        (add_sub, 2, OpAssoc.LEFT, create_binary_op_node),
        (comparison, 2, OpAssoc.LEFT, create_binary_op_node),
        (logical_and, 2, OpAssoc.LEFT, create_binary_op_node),
        (logical_or, 2, OpAssoc.LEFT, create_binary_op_node),
        (conditional, 3, OpAssoc.RIGHT, create_conditional_node),
    ]
)

def parse_expression(text: str) -> Node:
    """Parse an expression and return its AST."""
    try:
        result = expr.parse_string(text, parse_all=True)
        return result[0]  # Extract the first element from ParseResults
    except ParseException as e:
        raise ValueError(f"Failed to parse expression: {str(e)}")


class ExpressionSemanticError(ValueError):
    """Raised when a parsed factor expression violates a stable DSL contract."""

    def __init__(self, message: str, *, code: str = "semantic_error") -> None:
        super().__init__(message)
        self.code = code


LookbackKind = TypingLiteral["finite", "unbounded_causal"]

FINITE_LOOKBACK: LookbackKind = "finite"
UNBOUNDED_CAUSAL: LookbackKind = "unbounded_causal"


@dataclass(frozen=True)
class TemporalAnalysis:
    """Causal history required by an expression.

    ``lookback`` counts periods before the current timestamp.  Exponentially
    weighted operators consume the complete available past and are represented
    as ``unbounded_causal`` rather than being assigned a misleading finite span.
    """

    lookback_kind: LookbackKind
    lookback: int | None

    def __post_init__(self) -> None:
        if self.lookback_kind == FINITE_LOOKBACK:
            if isinstance(self.lookback, bool) or not isinstance(self.lookback, int):
                raise ValueError("Finite temporal analysis requires an integer lookback.")
            if self.lookback < 0:
                raise ValueError("Finite lookback must be non-negative.")
        elif self.lookback_kind == UNBOUNDED_CAUSAL:
            if self.lookback is not None:
                raise ValueError("Unbounded causal analysis cannot have a finite lookback.")
        else:
            raise ValueError(f"Unknown lookback kind: {self.lookback_kind!r}.")

    @classmethod
    def finite(cls, lookback: int = 0) -> "TemporalAnalysis":
        return cls(lookback_kind=FINITE_LOOKBACK, lookback=lookback)

    @classmethod
    def unbounded_causal(cls) -> "TemporalAnalysis":
        return cls(lookback_kind=UNBOUNDED_CAUSAL, lookback=None)


@dataclass(frozen=True)
class TemporalValidationPolicy:
    """Configurable temporal limits applied after causal safety checks.

    The public default permits every positive rolling window and any finite
    causal lookback.  Callers that need experiment-specific limits must opt in
    through :meth:`bounded`; no mining campaign limits are global defaults.
    """

    min_window: int = 1
    max_window: int | None = None
    max_lookback: int | None = None
    allow_unbounded_causal: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.min_window, bool) or not isinstance(self.min_window, int):
            raise ValueError("min_window must be an integer.")
        if self.min_window < 1:
            raise ValueError("min_window must be at least 1.")
        if self.max_window is not None:
            if isinstance(self.max_window, bool) or not isinstance(self.max_window, int):
                raise ValueError("max_window must be an integer or None.")
            if self.max_window < self.min_window:
                raise ValueError("max_window must be greater than or equal to min_window.")
        if self.max_lookback is not None:
            if isinstance(self.max_lookback, bool) or not isinstance(self.max_lookback, int):
                raise ValueError("max_lookback must be an integer or None.")
            if self.max_lookback < 0:
                raise ValueError("max_lookback must be non-negative.")
        if not isinstance(self.allow_unbounded_causal, bool):
            raise ValueError("allow_unbounded_causal must be a boolean.")

    @classmethod
    def bounded(
        cls,
        *,
        min_window: int,
        max_window: int,
        max_lookback: int,
        allow_unbounded_causal: bool = False,
    ) -> "TemporalValidationPolicy":
        return cls(
            min_window=min_window,
            max_window=max_window,
            max_lookback=max_lookback,
            allow_unbounded_causal=allow_unbounded_causal,
        )


@dataclass(frozen=True)
class _FunctionSignature:
    min_args: int
    max_args: int


# This is the executable expression surface in function_lib.py, excluding
# implementation helpers and operational-only n_jobs parameters.
_FUNCTION_SIGNATURES: dict[str, _FunctionSignature] = {
    "DELTA": _FunctionSignature(1, 2),
    "RANK": _FunctionSignature(1, 1),
    "MEAN": _FunctionSignature(1, 1),
    "STD": _FunctionSignature(1, 1),
    "SKEW": _FunctionSignature(1, 1),
    "KURT": _FunctionSignature(1, 1),
    "MAX": _FunctionSignature(1, 3),
    "MIN": _FunctionSignature(1, 3),
    "MEDIAN": _FunctionSignature(1, 1),
    "TS_RANK": _FunctionSignature(1, 2),
    "TS_MAX": _FunctionSignature(1, 2),
    "TS_MIN": _FunctionSignature(1, 2),
    "TS_MEAN": _FunctionSignature(1, 2),
    "TS_MEDIAN": _FunctionSignature(1, 2),
    "PERCENTILE": _FunctionSignature(2, 3),
    "TS_SUM": _FunctionSignature(1, 2),
    "TS_ARGMAX": _FunctionSignature(1, 2),
    "TS_ARGMIN": _FunctionSignature(1, 2),
    "ABS": _FunctionSignature(1, 1),
    "DELAY": _FunctionSignature(1, 2),
    "TS_CORR": _FunctionSignature(2, 3),
    "TS_COVARIANCE": _FunctionSignature(2, 3),
    "TS_STD": _FunctionSignature(1, 2),
    "TS_VAR": _FunctionSignature(1, 3),
    "SIGN": _FunctionSignature(1, 1),
    "SMA": _FunctionSignature(2, 3),
    "EMA": _FunctionSignature(2, 2),
    "WMA": _FunctionSignature(1, 2),
    "COUNT": _FunctionSignature(1, 2),
    "SUMIF": _FunctionSignature(3, 3),
    "FILTER": _FunctionSignature(2, 2),
    "PROD": _FunctionSignature(1, 2),
    "DECAYLINEAR": _FunctionSignature(1, 2),
    "HIGHDAY": _FunctionSignature(1, 2),
    "LOWDAY": _FunctionSignature(1, 2),
    "SEQUENCE": _FunctionSignature(1, 1),
    "SUMAC": _FunctionSignature(1, 2),
    "REGBETA": _FunctionSignature(2, 3),
    "REGRESI": _FunctionSignature(2, 3),
    "EXP": _FunctionSignature(1, 1),
    "SQRT": _FunctionSignature(1, 1),
    "LOG": _FunctionSignature(1, 1),
    "INV": _FunctionSignature(1, 1),
    "POW": _FunctionSignature(2, 2),
    "FLOOR": _FunctionSignature(1, 1),
    "TS_ZSCORE": _FunctionSignature(1, 2),
    "ZSCORE": _FunctionSignature(1, 1),
    "SCALE": _FunctionSignature(1, 2),
    "TS_MAD": _FunctionSignature(1, 2),
    "TS_QUANTILE": _FunctionSignature(1, 3),
    "TS_PCTCHANGE": _FunctionSignature(1, 2),
    "ADD": _FunctionSignature(2, 2),
    "SUBTRACT": _FunctionSignature(2, 2),
    "MULTIPLY": _FunctionSignature(2, 2),
    "DIVIDE": _FunctionSignature(2, 2),
    "AND": _FunctionSignature(2, 2),
    "OR": _FunctionSignature(2, 2),
    "MACD": _FunctionSignature(1, 3),
    "RSI": _FunctionSignature(1, 2),
    "BB_MIDDLE": _FunctionSignature(2, 2),
    "BB_UPPER": _FunctionSignature(2, 2),
    "BB_LOWER": _FunctionSignature(2, 2),
}


# The system factor zoo predates the executable all-uppercase DSL and stores a
# small Qlib-style surface.  Keep these aliases explicit and case-sensitive:
# notably ``MEAN(A)`` is cross-sectional while legacy ``Mean(A, n)`` is rolling.
_LEGACY_FUNCTION_ALIASES: dict[str, tuple[str, _FunctionSignature]] = {
    "Mean": ("TS_MEAN", _FunctionSignature(2, 2)),
    "Std": ("TS_STD", _FunctionSignature(2, 2)),
    "Ref": ("DELAY", _FunctionSignature(2, 2)),
    "Rank": ("RANK", _FunctionSignature(1, 1)),
}


# Function name -> ((positional argument index, runtime default), ...).
_ROLLING_WINDOW_SPECS: dict[str, tuple[tuple[int, int], ...]] = {
    "TS_RANK": ((1, 5),),
    "TS_MAX": ((1, 5),),
    "TS_MIN": ((1, 5),),
    "TS_MEAN": ((1, 5),),
    "TS_MEDIAN": ((1, 5),),
    "TS_SUM": ((1, 5),),
    "TS_ARGMAX": ((1, 5),),
    "TS_ARGMIN": ((1, 5),),
    "TS_CORR": ((2, 5),),
    "TS_COVARIANCE": ((2, 5),),
    "TS_STD": ((1, 20),),
    "TS_VAR": ((1, 5),),
    "WMA": ((1, 20),),
    "COUNT": ((1, 20),),
    "SUMIF": ((1, 0),),
    "PROD": ((1, 5),),
    "DECAYLINEAR": ((1, 5),),
    "HIGHDAY": ((1, 5),),
    "LOWDAY": ((1, 5),),
    "SUMAC": ((1, 10),),
    "REGBETA": ((2, 5),),
    "REGRESI": ((2, 5),),
    "TS_ZSCORE": ((1, 5),),
    "TS_MAD": ((1, 5),),
    "TS_QUANTILE": ((1, 5),),
    "PERCENTILE": ((2, 0),),
    "BB_MIDDLE": ((1, 0),),
    "BB_UPPER": ((1, 0),),
    "BB_LOWER": ((1, 0),),
}

_LAG_SPECS: dict[str, tuple[int, int]] = {
    "DELTA": (1, 1),
    "DELAY": (1, 1),
    "TS_PCTCHANGE": (1, 1),
}

_SEQUENCE_PARENT_FUNCTIONS = {
    "TS_CORR",
    "TS_COVARIANCE",
    "REGBETA",
    "REGRESI",
}


def _function_name(
    node: FunctionNode, *, allow_legacy_aliases: bool
) -> str:
    raw_name = str(node.name)
    if raw_name.startswith("$"):
        raise ExpressionSemanticError(
            f"Function names cannot use the variable prefix: {raw_name}.",
            code="invalid_function_name",
        )
    if allow_legacy_aliases and raw_name in _LEGACY_FUNCTION_ALIASES:
        return _LEGACY_FUNCTION_ALIASES[raw_name][0]
    # Runtime evaluation imports exact, upper-case names from function_lib.py.
    # Do not normalize arbitrary casing: accepting ``mean(...)`` here would
    # only defer the failure to eval(), where no such callable exists.
    return raw_name


def _integer_literal(node: Node, *, function_name: str, argument_name: str) -> int:
    if not isinstance(node, NumberNode):
        raise ExpressionSemanticError(
            f"{function_name} {argument_name} must be a literal integer.",
            code="invalid_integer_argument",
        )
    value = float(node.value)
    if not math.isfinite(value) or not value.is_integer():
        raise ExpressionSemanticError(
            f"{function_name} {argument_name} must be a finite integer; got {node.value}.",
            code="invalid_integer_argument",
        )
    return int(value)


def _positional_integer(
    node: FunctionNode,
    *,
    function_name: str,
    index: int,
    default: int,
    argument_name: str,
) -> int:
    if index < len(node.args):
        return _integer_literal(
            node.args[index],
            function_name=function_name,
            argument_name=argument_name,
        )
    return int(default)


def _validate_arity(
    node: FunctionNode,
    function_name: str,
    *,
    allow_legacy_aliases: bool,
) -> None:
    raw_name = str(node.name)
    legacy = (
        _LEGACY_FUNCTION_ALIASES.get(raw_name)
        if allow_legacy_aliases
        else None
    )
    signature = (
        legacy[1]
        if legacy is not None
        else _FUNCTION_SIGNATURES.get(function_name)
    )
    if signature is None:
        raise ExpressionSemanticError(
            f"Unknown factor function: {function_name}.",
            code="unknown_function",
        )
    count = len(node.args)
    if not signature.min_args <= count <= signature.max_args:
        if signature.min_args == signature.max_args:
            noun = "argument" if signature.min_args == 1 else "arguments"
            expected = f"exactly {signature.min_args} {noun}"
        else:
            expected = f"{signature.min_args} to {signature.max_args} arguments"
        raise ExpressionSemanticError(
            f"{raw_name} expects {expected}; got {count}.",
            code="invalid_arity",
        )


def _combine_temporal(analyses: list[TemporalAnalysis]) -> TemporalAnalysis:
    if any(item.lookback_kind == UNBOUNDED_CAUSAL for item in analyses):
        return TemporalAnalysis.unbounded_causal()
    return TemporalAnalysis.finite(
        max((item.lookback or 0 for item in analyses), default=0)
    )


def _add_finite_lookback(
    analysis: TemporalAnalysis, additional: int
) -> TemporalAnalysis:
    if analysis.lookback_kind == UNBOUNDED_CAUSAL:
        return analysis
    return TemporalAnalysis.finite((analysis.lookback or 0) + additional)


def _validate_window(
    window: int,
    *,
    function_name: str,
    policy: TemporalValidationPolicy,
) -> None:
    if window < 1:
        raise ExpressionSemanticError(
            f"{function_name} window must be positive; got {window}.",
            code="invalid_window",
        )
    if window < policy.min_window or (
        policy.max_window is not None and window > policy.max_window
    ):
        upper = "unbounded" if policy.max_window is None else str(policy.max_window)
        raise ExpressionSemanticError(
            f"{function_name} window must be in [{policy.min_window}, {upper}]; got {window}.",
            code="window_out_of_policy",
        )


def validate_expression_semantics(
    expression: str | Node,
    *,
    policy: TemporalValidationPolicy | None = None,
    allow_legacy_aliases: bool = False,
) -> TemporalAnalysis:
    """Validate the function surface and causal semantics of an expression.

    A rolling window of ``n`` observes the current value plus ``n - 1`` prior
    values.  Lags and differences add their full period to the oldest input
    timestamp.  EWM-based functions remain causal but use unbounded history.
    Runtime validation is case-sensitive by default; callers that read legacy
    Qlib factor zoos may opt into the four explicit compatibility aliases.
    """
    resolved_policy = policy if policy is not None else TemporalValidationPolicy()
    if not isinstance(resolved_policy, TemporalValidationPolicy):
        raise TypeError("policy must be a TemporalValidationPolicy instance.")
    if not isinstance(allow_legacy_aliases, bool):
        raise TypeError("allow_legacy_aliases must be a boolean.")
    try:
        root = parse_expression(expression) if isinstance(expression, str) else expression
    except ValueError as exc:
        raise ExpressionSemanticError(str(exc), code="syntax_error") from exc

    def visit(
        node: Node,
        *,
        parent_function: str | None = None,
        argument_index: int | None = None,
    ) -> TemporalAnalysis:
        if isinstance(node, (NumberNode, VarNode)):
            return TemporalAnalysis.finite()
        if isinstance(node, BinaryOpNode):
            return _combine_temporal([visit(node.left), visit(node.right)])
        if isinstance(node, ConditionalNode):
            return _combine_temporal(
                [
                    visit(node.condition),
                    visit(node.true_expr),
                    visit(node.false_expr),
                ]
            )
        if not isinstance(node, FunctionNode):
            return TemporalAnalysis.finite()

        name = _function_name(
            node, allow_legacy_aliases=allow_legacy_aliases
        )
        _validate_arity(
            node,
            name,
            allow_legacy_aliases=allow_legacy_aliases,
        )
        child_analysis = _combine_temporal(
            [
                visit(arg, parent_function=name, argument_index=index)
                for index, arg in enumerate(node.args)
            ]
        )

        if name in _LAG_SPECS:
            index, default = _LAG_SPECS[name]
            lag = _positional_integer(
                node,
                function_name=name,
                index=index,
                default=default,
                argument_name="lag",
            )
            if lag < 0:
                raise ExpressionSemanticError(
                    f"{name} lag must be non-negative; got {lag}.",
                    code="future_looking_lag",
                )
            return _add_finite_lookback(child_analysis, lag)

        if name == "SEQUENCE":
            if (
                parent_function not in _SEQUENCE_PARENT_FUNCTIONS
                or argument_index != 1
            ):
                allowed = ", ".join(sorted(_SEQUENCE_PARENT_FUNCTIONS))
                raise ExpressionSemanticError(
                    "SEQUENCE may only be used as the direct second argument "
                    f"of: {allowed}.",
                    code="invalid_sequence_context",
                )
            length = _positional_integer(
                node,
                function_name=name,
                index=0,
                default=0,
                argument_name="length",
            )
            _validate_window(length, function_name=name, policy=resolved_policy)
            # SEQUENCE is a fixed regressor, not an additional market-data lookback.
            return child_analysis

        if name == "PERCENTILE" and len(node.args) < 3:
            raise ExpressionSemanticError(
                "PERCENTILE without a rolling window uses the instrument's full "
                "history and is not causal.",
                code="noncausal_percentile",
            )

        if name == "SMA":
            window = _positional_integer(
                node,
                function_name=name,
                index=1,
                default=0,
                argument_name="window",
            )
            _validate_window(window, function_name=name, policy=resolved_policy)
            if len(node.args) == 3:
                return TemporalAnalysis.unbounded_causal()
            return _add_finite_lookback(child_analysis, window - 1)

        if name == "EMA":
            window = _positional_integer(
                node,
                function_name=name,
                index=1,
                default=0,
                argument_name="window",
            )
            _validate_window(window, function_name=name, policy=resolved_policy)
            return TemporalAnalysis.unbounded_causal()

        if name == "MACD":
            for index, default in ((1, 12), (2, 26)):
                window = _positional_integer(
                    node,
                    function_name=name,
                    index=index,
                    default=default,
                    argument_name="window",
                )
                _validate_window(window, function_name=name, policy=resolved_policy)
            return TemporalAnalysis.unbounded_causal()

        if name == "RSI":
            window = _positional_integer(
                node,
                function_name=name,
                index=1,
                default=14,
                argument_name="window",
            )
            _validate_window(window, function_name=name, policy=resolved_policy)
            return TemporalAnalysis.unbounded_causal()

        specs = _ROLLING_WINDOW_SPECS.get(name)
        if specs is None:
            return child_analysis

        windows: list[int] = []
        for index, default in specs:
            window = _positional_integer(
                node,
                function_name=name,
                index=index,
                default=default,
                argument_name="window",
            )
            _validate_window(window, function_name=name, policy=resolved_policy)
            windows.append(window)

        # The runtime replaces TS_CORR/TS_COVARIANCE's explicit or default
        # window with len(SEQUENCE(n)) when the second operand is that fixed
        # ndarray.  Analyze the window that will actually execute, while still
        # validating any supplied p above as part of the public DSL contract.
        if name in {"TS_CORR", "TS_COVARIANCE"}:
            sequence_arg = node.args[1]
            if (
                isinstance(sequence_arg, FunctionNode)
                and _function_name(
                    sequence_arg,
                    allow_legacy_aliases=allow_legacy_aliases,
                )
                == "SEQUENCE"
            ):
                windows = [
                    _positional_integer(
                        sequence_arg,
                        function_name="SEQUENCE",
                        index=0,
                        default=0,
                        argument_name="length",
                    )
                ]
        return _add_finite_lookback(child_analysis, max(windows) - 1)

    analysis = visit(root)
    if analysis.lookback_kind == UNBOUNDED_CAUSAL:
        if not resolved_policy.allow_unbounded_causal:
            raise ExpressionSemanticError(
                "Expression uses causal operators with unbounded historical memory.",
                code="unbounded_lookback",
            )
        return analysis
    if (
        resolved_policy.max_lookback is not None
        and (analysis.lookback or 0) > resolved_policy.max_lookback
    ):
        raise ExpressionSemanticError(
            f"Cumulative lookback {analysis.lookback} exceeds the maximum "
            f"{resolved_policy.max_lookback}.",
            code="lookback_out_of_policy",
        )
    return analysis
    
    
    
    
    
    
def are_nodes_equal(node1: Node, node2: Node) -> bool:
    """比较两个节点是否相等"""
    if type(node1) != type(node2):
        return False
        
    if isinstance(node1, NumberNode):
        return node1.value == node2.value
    elif isinstance(node1, VarNode):
        return node1.name == node2.name
    elif isinstance(node1, FunctionNode):
        return node1.name == node2.name and len(node1.args) == len(node2.args)
    elif isinstance(node1, BinaryOpNode):
        return node1.op == node2.op
    elif isinstance(node1, ConditionalNode):
        return True  # 条件节点本身相等，子节点会在递归中比较
    return False

@dataclass
class SubtreeMatch:
    root1: Node  # 第一个树中的子树根节点
    root2: Node  # 第二个树中的子树根节点
    size: int    # 子树大小（节点数）
    
    def __str__(self):
        return f"Match(size={self.size}):\n  Tree1: {str(root1)}\n  Tree2: {str(root2)}"

def find_largest_common_subtree(root1: Node, root2: Node) -> Opt[SubtreeMatch]:
    """查找两棵树之间的最大公共子树"""
    
    def get_subtree_size(node: Node) -> int:
        """计算以给定节点为根的子树大小"""
        if isinstance(node, (NumberNode, VarNode)):
            return 1
        elif isinstance(node, FunctionNode):
            return 1 + sum(get_subtree_size(arg) for arg in node.args)
        elif isinstance(node, BinaryOpNode):
            return 1 + get_subtree_size(node.left) + get_subtree_size(node.right)
        elif isinstance(node, ConditionalNode):
            return 1 + get_subtree_size(node.condition) + \
                   get_subtree_size(node.true_expr) + \
                   get_subtree_size(node.false_expr)
        return 0

    def get_all_subtrees(root: Node) -> List[Node]:
        """获取树中的所有子树根节点"""
        result = [root]
        if isinstance(root, FunctionNode):
            for arg in root.args:
                result.extend(get_all_subtrees(arg))
        elif isinstance(root, BinaryOpNode):
            result.extend(get_all_subtrees(root.left))
            result.extend(get_all_subtrees(root.right))
        elif isinstance(root, ConditionalNode):
            result.extend(get_all_subtrees(root.condition))
            result.extend(get_all_subtrees(root.true_expr))
            result.extend(get_all_subtrees(root.false_expr))
        return result

    def is_commutative_op(op: str) -> bool:
        """判断是否为可交换操作符"""
        return op in {'+', '*', '==', '!=', '&', '&&', '|', '||'}

    def are_subtrees_equal(node1: Node, node2: Node) -> bool:
        """递归比较两个子树是否完全相等，考虑可交换操作"""
        if not are_nodes_equal(node1, node2):
            return False
            
        if isinstance(node1, (NumberNode, VarNode)):
            return True
        elif isinstance(node1, FunctionNode):
            return all(are_subtrees_equal(arg1, arg2) 
                      for arg1, arg2 in zip(node1.args, node2.args))
        elif isinstance(node1, BinaryOpNode):
            # 对于可交换操作符，尝试两种顺序
            if is_commutative_op(node1.op):
                return (are_subtrees_equal(node1.left, node2.left) and 
                        are_subtrees_equal(node1.right, node2.right)) or \
                       (are_subtrees_equal(node1.left, node2.right) and 
                        are_subtrees_equal(node1.right, node2.left))
            else:
                return are_subtrees_equal(node1.left, node2.left) and \
                       are_subtrees_equal(node1.right, node2.right)
        elif isinstance(node1, ConditionalNode):
            return are_subtrees_equal(node1.condition, node2.condition) and \
                   are_subtrees_equal(node1.true_expr, node2.true_expr) and \
                   are_subtrees_equal(node1.false_expr, node2.false_expr)
        return False

    # 获取所有可能的子树
    subtrees1 = get_all_subtrees(root1)
    subtrees2 = get_all_subtrees(root2)
    
    # 找到最大的公共子树
    max_match = None
    max_size = 0
    
    for st1 in subtrees1:
        size1 = get_subtree_size(st1)
        if size1 <= max_size:
            continue
            
        for st2 in subtrees2:
            size2 = get_subtree_size(st2)
            if size2 != size1 or size2 <= max_size:
                continue
                
            if are_subtrees_equal(st1, st2):
                max_size = size1
                max_match = SubtreeMatch(st1, st2, size1)
    
    return max_match

def compare_expressions(expr1: str, expr2: str) -> Opt[SubtreeMatch]:
    """Compare two expressions and return their largest common subtree"""
    tree1 = parse_expression(expr1)
    tree2 = parse_expression(expr2)
    return find_largest_common_subtree(tree1, tree2)
    
    
    
def match_alphazoo(prop_expr, factor_df):
    max_size = 0
    matched_subtree = None
    matched_alpha = None
    if factor_df is None or len(factor_df) == 0:
        return max_size, matched_subtree, matched_alpha
    # Defensive: the row unpacking below expects exactly (name, expression).
    # Select the two canonical columns so extra columns never break dedup.
    if {"factor_name", "factor_expression"}.issubset(factor_df.columns):
        factor_df = factor_df[["factor_name", "factor_expression"]]
    for index, (name, alpha_expr) in factor_df.iterrows():
        try:
            match = compare_expressions(prop_expr, alpha_expr)
            if match is not None and match.size > max_size:
                 max_size = match.size
                 matched_subtree = match.root1
                 matched_alpha = alpha_expr
        except Exception as e:
            print(f"Error comparing alpha \"{alpha_expr}\": \n {e}")
    return max_size, matched_subtree, matched_alpha
    


def count_free_args(expr: str) -> int:
    """
    Count the number of NumberNode instances (numeric constants) in the given expression.
    
    Args:
        expr: A string representing a mathematical expression
        
    Returns:
        int: The number of numeric constants in the expression
    """
    tree = parse_expression(expr)
    return count_number_nodes(tree)

def count_number_nodes(node: Node) -> int:
    """
    Recursively count the number of NumberNode instances in an AST.
    
    Args:
        node: The root node of the AST or sub-tree
        
    Returns:
        int: The number of NumberNode instances in the tree
    """
    if isinstance(node, NumberNode):
        return 1
    elif isinstance(node, VarNode):
        return 0
    elif isinstance(node, FunctionNode):
        return sum(count_number_nodes(arg) for arg in node.args)
    elif isinstance(node, BinaryOpNode):
        return count_number_nodes(node.left) + count_number_nodes(node.right)
    elif isinstance(node, ConditionalNode):
        return (count_number_nodes(node.condition) + 
                count_number_nodes(node.true_expr) + 
                count_number_nodes(node.false_expr))
    return 0



def count_unique_vars(expr: str) -> int:
    """
    Count the number of unique variable names in the given expression.
    
    Args:
        expr: A string representing a mathematical expression
        
    Returns:
        int: The number of unique variable names in the expression
    """
    tree = parse_expression(expr)
    unique_vars = set()
    collect_unique_vars(tree, unique_vars)
    return len(unique_vars)

def collect_unique_vars(node: Node, unique_vars: set) -> None:
    """
    Recursively collect unique variable names from an AST.
    
    Args:
        node: The root node of the AST or sub-tree
        unique_vars: A set to collect unique variable names
    """
    if isinstance(node, VarNode):
        # Only add actual data variables, not function names
        if node.name.startswith('$'):
            unique_vars.add(node.name)
    elif isinstance(node, NumberNode):
        pass  # No variables in number nodes
    elif isinstance(node, FunctionNode):
        # Don't add the function name itself as a variable
        for arg in node.args:
            collect_unique_vars(arg, unique_vars)
    elif isinstance(node, BinaryOpNode):
        collect_unique_vars(node.left, unique_vars)
        collect_unique_vars(node.right, unique_vars)
    elif isinstance(node, ConditionalNode):
        collect_unique_vars(node.condition, unique_vars)
        collect_unique_vars(node.true_expr, unique_vars)
        collect_unique_vars(node.false_expr, unique_vars)


def count_all_nodes(expr: str) -> int:
    """
    Count the number of Node instances (numeric constants) in the given expression.
    
    Args:
        expr: A string representing a mathematical expression
        
    Returns:
        int: The number of numeric constants in the expression
    """
    tree = parse_expression(expr)
    return count_nodes(tree)


def count_nodes(node: Node) -> int:
    """
    Recursively count the number of Node instances in an AST.
    
    Args:
        node: The root node of the AST or sub-tree
        
    Returns:
        int: The number of Node instances in the tree
    """
    if isinstance(node, (NumberNode, VarNode)):
        return 1
    elif isinstance(node, FunctionNode):
        return 1 + sum(count_nodes(arg) for arg in node.args)
    elif isinstance(node, BinaryOpNode):
        return 1 + count_nodes(node.left) + count_nodes(node.right)
    elif isinstance(node, ConditionalNode):
        return 1 + (count_nodes(node.condition) + 
                    count_nodes(node.true_expr) + 
                    count_nodes(node.false_expr))
    return 0


# Example usage:
if __name__ == "__main__":
    expr1 = "(($close - TS_MIN($low, 14)) / (TS_MAX($high, 14) - TS_MIN($low, 14) + 1e-8))"
    count = count_free_args(expr1)
    print(f"Number of NumberNode instances in expression: {count}")  # Should print 3 (14, 1e-8, and 100)
    count = count_unique_vars(expr1)
    print(f"Number of unique variables in expression: {count}")  
    count = count_all_nodes(expr1)
    print(f"Number of Node instances in expression: {count}") 

# if __name__ == "__main__":
#     # Test cases
#     expr1 = "(($close - TS_MIN($low, 14)) / (TS_MAX($high, 14) - TS_MIN($low, 14) + 1e-8)) * 100"
#     expr2 = "(TS_MAX($high, 14) - TS_MIN($low, 14)) * STD($close, 20) / MEAN($volume, 10)"
#     match = compare_expressions(expr1, expr2)
#     factor_df = pd.read_csv("factor_zoo/alpha101.csv", index_col=None)
    
    
#     max_size = 0
#     matched_subtree = None
#     matched_alpha = None
#     for index, (name, alpha_expr) in factor_df.iterrows():
#         try:
#             match = compare_expressions(expr1, alpha_expr)
#             if match is not None and match.size > max_size:
#                  max_size = match.size
#                  matched_subtree = match.root1
#                  matched_alpha = alpha_expr
#         except Exception as e:
#             print(f"Error comparing alpha \"{alpha_expr}\": \n {e}")
            

                 
#     print(max_size)
#     print(matched_subtree)
#     print(matched_alpha)
