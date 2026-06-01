"""Factor originality regulator for the factor system layer."""

from __future__ import annotations

import contextlib
import io
from typing import Optional

import numpy as np
import pandas as pd

from alphapilot.components.coder.factor_coder.expr_parser import parse_expression
from alphapilot.components.coder.factor_coder.factor_ast import parse_expression as parse_expression_ast
from alphapilot.components.coder.factor_coder.factor_ast import (
    count_all_nodes,
    count_free_args,
    count_unique_vars,
    match_alphazoo,
)
from alphapilot.core.evaluation import Evaluator
from alphapilot.log import logger


class FactorRegulator(Evaluator):
    """Evaluate factor expressions for parsability and duplication."""

    def __init__(self, factor_zoo_path: str | None = None, duplication_threshold: int = 8):
        super().__init__(None)
        self.factor_zoo_path = factor_zoo_path
        self.alphazoo = pd.read_csv(factor_zoo_path, index_col=None) if factor_zoo_path else pd.DataFrame()
        self.duplication_threshold = duplication_threshold
        self.new_factors: list[tuple[str, str]] = []

    def is_parsable(self, expression: str) -> bool:
        ok, _, _ = self.check_expression(expression)
        return ok

    def check_expression(self, expression: str) -> tuple[bool, dict | None, str | None]:
        """Validate syntax (lenient + strict AST) and run evaluate.

        Returns (True, eval_dict, None) when ready for duplication checks, or
        (False, None, error_message) with a reason suitable for LLM feedback.
        """
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                parse_expression(expression)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            logger.error(f"Failed to parse expression: {expression}. Error: {msg}")
            return False, None, msg

        try:
            parse_expression_ast(expression)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if msg.startswith("Failed to parse expression:"):
                msg = msg[len("Failed to parse expression:") :].strip()
            logger.error(f"Failed to parse expression (AST): {expression}. Error: {msg}")
            return False, None, msg

        success, eval_dict = self.evaluate(expression)
        if not success or eval_dict is None:
            return False, None, "Expression failed structural evaluation (duplicate / AST analysis)."
        return True, eval_dict, None

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

    def is_expression_acceptable(self, eval_dict: dict) -> bool:
        cond1 = eval_dict["duplicated_subtree_size"] <= self.duplication_threshold

        num_free_args = eval_dict["num_free_args"]
        num_unique_vars = eval_dict["num_unique_vars"]
        num_all_nodes = eval_dict["num_all_nodes"]

        if num_all_nodes == 0:
            logger.warning(f"Expression has no nodes: {eval_dict['expr']}")
            return False

        free_args_ratio = float(num_free_args) / float(num_all_nodes)
        unique_vars_ratio = float(num_unique_vars) / float(num_all_nodes)
        if free_args_ratio >= 1 or unique_vars_ratio >= 1:
            logger.warning(
                f"Invalid ratio detected: free_args_ratio={free_args_ratio}, "
                f"unique_vars_ratio={unique_vars_ratio}"
            )
            return False

        cond2 = -np.log(1 - free_args_ratio) < 0.693
        cond3 = -np.log(1 - unique_vars_ratio) < 0.693
        return cond1 and cond2 and cond3

    def add_factor(self, factor_name: str, factor_expression: str) -> bool:
        new_factor = pd.DataFrame(
            {
                "factor_name": factor_name,
                "factor_expression": factor_expression,
            }
        )
        self.alphazoo = pd.concat([self.alphazoo, new_factor])
        self.new_factors.append((factor_name, factor_expression))
        logger.info(f"Added new factor: {factor_name} with expression: {factor_expression}")
        return True

    def save_factor_zoo(self, output_path: Optional[str] = None) -> None:
        save_path = output_path if output_path else self.factor_zoo_path
        self.alphazoo.to_csv(save_path, index=False)
        logger.info(f"Saved updated factor zoo to {save_path}")

    def get_new_factors(self) -> list[tuple[str, str]]:
        return self.new_factors
