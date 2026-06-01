"""Factor expression DSL surface.

Re-exports the factor expression language (parser + function library +
AST helpers) and the factor task/workspace types under the factor system
namespace, so modules depend on ``systems.factor`` rather than reaching
into ``components.coder.factor_coder`` internals.
"""

from __future__ import annotations

from alphapilot.components.coder.factor_coder.expr_parser import (
    parse_expression,
    parse_symbol,
)
from alphapilot.components.coder.factor_coder.factor import (
    FactorFBWorkspace,
    FactorTask,
)

__all__ = [
    "FactorFBWorkspace",
    "FactorTask",
    "parse_expression",
    "parse_symbol",
]
