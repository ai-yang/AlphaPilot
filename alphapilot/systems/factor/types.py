"""Structured results for factor expression validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

REJECT_PARSE_ERROR = "parse_error"
REJECT_EVALUATION_FAILED = "evaluation_failed"
REJECT_EMPTY_EXPRESSION = "empty_expression"
REJECT_TOO_SIMILAR = "too_similar"
REJECT_TOO_MANY_LITERALS = "too_many_literals"
REJECT_INSUFFICIENT_VARIABLES = "insufficient_variables"
REJECT_INVALID_RATIOS = "invalid_ratios"
REJECT_MISSING_NAME = "missing_name"
REJECT_DUPLICATE_NAME = "duplicate_name"
REJECT_DUPLICATE_EXPRESSION = "duplicate_expression"
OK_CODE = "ok"


@dataclass
class FactorValidationResult:
    """Outcome of validating a factor expression (or add attempt)."""

    acceptable: bool
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
