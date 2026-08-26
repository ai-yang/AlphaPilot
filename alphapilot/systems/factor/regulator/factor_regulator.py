"""Factor originality regulator for the factor system layer."""

from __future__ import annotations

import contextlib
import io
from typing import Optional

import numpy as np
import pandas as pd

from alphapilot.components.coder.factor_coder.expr_parser import parse_expression
from alphapilot.components.coder.factor_coder.factor_ast import (
    ExpressionSemanticError,
    TemporalValidationPolicy,
    count_all_nodes,
    count_free_args,
    count_unique_vars,
    match_alphazoo,
    parse_expression as parse_expression_ast,
    validate_expression_semantics,
)
from alphapilot.core.evaluation import Evaluator
from alphapilot.log import logger
from alphapilot.systems.factor.types import (
    OK_CODE,
    REJECT_EMPTY_EXPRESSION,
    REJECT_EVALUATION_FAILED,
    REJECT_INSUFFICIENT_VARIABLES,
    REJECT_INVALID_RATIOS,
    REJECT_PARSE_ERROR,
    REJECT_TOO_MANY_LITERALS,
    REJECT_TOO_SIMILAR,
    FactorValidationResult,
)

_STRUCTURAL_EVAL_MESSAGE = "Expression failed structural evaluation (duplicate / AST analysis)."


class FactorRegulator(Evaluator):
    """Evaluate factor expressions for parsability and duplication."""

    def __init__(
        self,
        factor_zoo_path: str | None = None,
        duplication_threshold: int = 8,
        temporal_policy: TemporalValidationPolicy | None = None,
        allow_legacy_aliases: bool = True,
    ) -> None:
        super().__init__(None)
        if temporal_policy is not None and not isinstance(
            temporal_policy, TemporalValidationPolicy
        ):
            raise TypeError("temporal_policy must be a TemporalValidationPolicy.")
        if not isinstance(allow_legacy_aliases, bool):
            raise TypeError("allow_legacy_aliases must be a boolean.")
        self.factor_zoo_path = factor_zoo_path
        self.alphazoo = (
            pd.read_csv(factor_zoo_path, index_col=None)
            if factor_zoo_path
            else pd.DataFrame()
        )
        self.duplication_threshold = duplication_threshold
        self.temporal_policy = (
            temporal_policy
            if temporal_policy is not None
            else TemporalValidationPolicy()
        )
        # Factor-system zoos store Qlib-style Mean/Std/Ref/Rank spellings.
        # Code generation uses the strict runtime DSL and leaves this disabled.
        self.allow_legacy_aliases = allow_legacy_aliases
        self.new_factors: list[tuple[str, str]] = []

    def is_parsable(self, expression: str) -> bool:
        ok, _, _ = self.check_expression(expression)
        return ok

    def check_expression(self, expression: str) -> tuple[bool, dict | None, str | None]:
        """Backward-compatible expression check without the structured code."""
        ok, eval_dict, message, _ = self.check_expression_detailed(expression)
        return ok, eval_dict, message

    def check_expression_detailed(
        self, expression: str
    ) -> tuple[bool, dict | None, str | None, str | None]:
        """Validate syntax, causal semantics, and structural originality.

        The fourth tuple item is a stable semantic/parse error code.  It is
        ``None`` on success and is also surfaced by :meth:`validate_expression`.
        """
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                parse_expression(expression)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            logger.error(f"Failed to parse expression: {expression}. Error: {msg}")
            return False, None, msg, REJECT_PARSE_ERROR

        try:
            expression_ast = parse_expression_ast(expression)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if msg.startswith("Failed to parse expression:"):
                msg = msg[len("Failed to parse expression:") :].strip()
            logger.error(f"Failed to parse expression (AST): {expression}. Error: {msg}")
            return False, None, msg, REJECT_PARSE_ERROR

        try:
            temporal_analysis = validate_expression_semantics(
                expression_ast,
                policy=self.temporal_policy,
                allow_legacy_aliases=self.allow_legacy_aliases,
            )
        except ExpressionSemanticError as exc:
            msg = str(exc)
            logger.error(
                f"Failed semantic validation: {expression}. "
                f"Code: {exc.code}. Error: {msg}"
            )
            return False, None, msg, exc.code

        success, eval_dict = self.evaluate(expression)
        if not success or eval_dict is None:
            return False, None, _STRUCTURAL_EVAL_MESSAGE, REJECT_EVALUATION_FAILED
        eval_dict["lookback"] = temporal_analysis.lookback
        eval_dict["lookback_kind"] = temporal_analysis.lookback_kind
        return True, eval_dict, None, None

    def evaluate(self, expression: str) -> tuple[bool, dict | None]:
        try:
            duplicated_subtree_size, duplicated_subtree, matched_alpha = match_alphazoo(expression, self.alphazoo)
            num_free_args = count_free_args(expression)
            num_unique_vars = count_unique_vars(expression)
            num_all_nodes = count_all_nodes(expression)

            logger.info(
                f"""
                        Evaluated expr: {expression}
                        Duplicated Size: {duplicated_subtree_size}
                        Duplicated Subtree: {duplicated_subtree}
                        # Free Args: {num_free_args}
                        # Unique Vars: {num_unique_vars}
                        """
            )

            eval_dict = {
                "expr": expression,
                "duplicated_subtree_size": duplicated_subtree_size,
                "duplicated_subtree": duplicated_subtree,
                "matched_alpha": matched_alpha,
                "num_free_args": num_free_args,
                "num_unique_vars": num_unique_vars,
                "num_all_nodes": num_all_nodes,
            }
            return True, eval_dict
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to evaluate expression: {expression}. Error: {str(exc)}")
            return False, None

    def explain_acceptability(self, eval_dict: dict) -> tuple[bool, str, str, dict[str, object]]:
        """Return (acceptable, code, message, details) for a successful *evaluate* dict."""
        threshold = self.duplication_threshold
        dup_size = int(eval_dict["duplicated_subtree_size"])
        num_free_args = int(eval_dict["num_free_args"])
        num_unique_vars = int(eval_dict["num_unique_vars"])
        num_all_nodes = int(eval_dict["num_all_nodes"])

        details: dict[str, object] = {
            "duplicated_subtree_size": dup_size,
            "duplication_threshold": threshold,
            "duplicated_subtree": eval_dict.get("duplicated_subtree"),
            "matched_alpha": eval_dict.get("matched_alpha"),
            "num_free_args": num_free_args,
            "num_unique_vars": num_unique_vars,
            "num_all_nodes": num_all_nodes,
            "lookback": eval_dict.get("lookback"),
            "lookback_kind": eval_dict.get("lookback_kind"),
        }

        if num_all_nodes == 0:
            return False, REJECT_EMPTY_EXPRESSION, "Expression has no AST nodes.", details

        free_args_ratio = float(num_free_args) / float(num_all_nodes)
        unique_vars_ratio = float(num_unique_vars) / float(num_all_nodes)
        details["free_args_ratio"] = round(free_args_ratio, 4)
        details["unique_vars_ratio"] = round(unique_vars_ratio, 4)

        if free_args_ratio >= 1 or unique_vars_ratio >= 1:
            return (
                False,
                REJECT_INVALID_RATIOS,
                (
                    f"Invalid expression structure: free_args_ratio={free_args_ratio:.4f}, "
                    f"unique_vars_ratio={unique_vars_ratio:.4f}."
                ),
                details,
            )

        if dup_size > threshold:
            matched = eval_dict.get("matched_alpha")
            matched_hint = f" (similar to existing factor: {matched})" if matched else ""
            return (
                False,
                REJECT_TOO_SIMILAR,
                (
                    f"Expression is too similar to the factor zoo: duplicated subtree size "
                    f"{dup_size} exceeds threshold {threshold}{matched_hint}."
                ),
                details,
            )

        if -np.log(1 - free_args_ratio) >= 0.693:
            return (
                False,
                REJECT_TOO_MANY_LITERALS,
                (
                    f"Too many numeric literals in the expression "
                    f"(literal node ratio {free_args_ratio:.2%}, max ~50%)."
                ),
                details,
            )

        if -np.log(1 - unique_vars_ratio) >= 0.693:
            return (
                False,
                REJECT_INSUFFICIENT_VARIABLES,
                (
                    f"Not enough market-data variables in the expression "
                    f"(unique variable ratio {unique_vars_ratio:.2%}, need >50%)."
                ),
                details,
            )

        return True, OK_CODE, "Expression is parsable and original enough to add.", details

    def validate_expression(self, expression: str) -> FactorValidationResult:
        """Validate *expression* and return a structured pass/fail with reason."""
        expr = (expression or "").strip()
        if not expr:
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_EMPTY_EXPRESSION,
                message="Expression is empty.",
                details=None,
            )

        ok, eval_dict, error_message, error_code = self.check_expression_detailed(expr)
        if not ok or eval_dict is None:
            return FactorValidationResult(
                acceptable=False,
                code=error_code or REJECT_PARSE_ERROR,
                message=error_message or "Expression validation failed.",
                details=None,
            )

        acceptable, code, message, details = self.explain_acceptability(eval_dict)
        return FactorValidationResult(
            acceptable=acceptable,
            code=code,
            message=message,
            details=details,
        )

    def is_expression_acceptable(self, eval_dict: dict) -> bool:
        acceptable, _, _, _ = self.explain_acceptability(eval_dict)
        if not acceptable:
            logger.warning(f"Expression not acceptable: {eval_dict.get('expr')}")
        return acceptable

    def list_factors(self) -> list[dict[str, str]]:
        if self.alphazoo.empty or "factor_name" not in self.alphazoo.columns:
            return []
        return [
            {
                "factor_name": str(row["factor_name"]),
                "factor_expression": str(row["factor_expression"]),
            }
            for _, row in self.alphazoo.iterrows()
        ]

    def add_factor(self, factor_name: str, factor_expression: str) -> bool:
        new_factor = pd.DataFrame(
            {
                "factor_name": [factor_name],
                "factor_expression": [factor_expression],
            }
        )
        self.alphazoo = pd.concat([self.alphazoo, new_factor], ignore_index=True)
        self.new_factors.append((factor_name, factor_expression))
        logger.info(f"Added new factor: {factor_name} with expression: {factor_expression}")
        return True

    def remove_factor(self, factor_name: str) -> bool:
        if self.alphazoo.empty or "factor_name" not in self.alphazoo.columns:
            return False
        mask = self.alphazoo["factor_name"].astype(str) == factor_name
        if not mask.any():
            return False
        self.alphazoo = self.alphazoo.loc[~mask].reset_index(drop=True)
        logger.info(f"Removed factor: {factor_name}")
        return True

    def rename_factor(self, old_name: str, new_name: str) -> bool:
        if self.alphazoo.empty or "factor_name" not in self.alphazoo.columns:
            return False
        mask = self.alphazoo["factor_name"].astype(str) == old_name
        if not mask.any():
            return False
        self.alphazoo.loc[mask, "factor_name"] = new_name
        logger.info(f"Renamed factor: {old_name} -> {new_name}")
        return True

    def save_factor_zoo(self, output_path: Optional[str] = None) -> None:
        save_path = output_path if output_path else self.factor_zoo_path
        self.alphazoo.to_csv(save_path, index=False)
        logger.info(f"Saved updated factor zoo to {save_path}")

    def get_new_factors(self) -> list[tuple[str, str]]:
        return self.new_factors
