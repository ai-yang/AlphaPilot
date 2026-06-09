"""CLI module for factor zoo validation and management."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.factor.types import FactorValidationResult

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _print_validation(result: FactorValidationResult, *, expression: str | None = None) -> None:
    if expression is not None:
        print(f"Expression: {expression}")
    status = "PASS" if result.acceptable else "FAIL"
    print(f"Status: {status}")
    print(f"Code: {result.code}")
    print(f"Message: {result.message}")
    if result.details:
        print(f"Details: {json.dumps(result.details, ensure_ascii=False, indent=2, default=str)}")


class FactorModule(BaseModule):
    """Validate and add factors via CLI."""

    name = "factor"

    def setup(self, context: "Context") -> None:
        self.context = context

    def factor_validate(self, expression: str) -> dict[str, Any]:
        """Validate a factor expression and print the rejection reason if any."""
        result = self.context.factor().validate_expression(expression)
        _print_validation(result, expression=expression)
        if not result.acceptable:
            sys.exit(1)
        return result.to_dict()

    def factor_add(self, factor_name: str, expression: str) -> dict[str, Any]:
        """Validate then add a factor to the zoo."""
        result = self.context.factor().add_factor(factor_name, expression)
        _print_validation(result, expression=expression)
        if not result.acceptable:
            sys.exit(1)
        return result.to_dict()

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "factor_validate": self.factor_validate,
            "factor_add": self.factor_add,
        }
