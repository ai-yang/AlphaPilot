"""Expose the existing DSL validator without applying library novelty gates."""
from __future__ import annotations

from .common import json_value


def validate_expression(system, expression: str) -> dict:
    normalized = expression.strip()
    regulator = system.database.regulator
    valid, analysis, message, code = regulator.check_expression_detailed(normalized)
    admission = system.validate_expression(normalized)
    return {"expression": expression, "normalized_expression": normalized,
            "normalization": "whitespace_trim", "valid": valid,
            "syntax_valid": valid or code not in {"parse_error", "empty_expression"},
            "temporal_valid": valid, "analysis": json_value(analysis),
            "issues": [] if valid else [{"code": code or "validation_failed", "message": message or "Invalid expression"}],
            "library_admission": json_value(admission)}
