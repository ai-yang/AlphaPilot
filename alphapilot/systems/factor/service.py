"""Default factor management system.

Wraps the factor DSL + the file-based factor zoo, and exposes the
existing JSON/PDF import loaders behind a single ``import_factors`` API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphapilot.systems.factor.base import BaseFactorSystem
from alphapilot.systems.factor.database import build_factor_database
from alphapilot.systems.factor.types import (
    OK_CODE,
    REJECT_DUPLICATE_EXPRESSION,
    REJECT_DUPLICATE_NAME,
    REJECT_MISSING_NAME,
    FactorValidationResult,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class FactorSystem(BaseFactorSystem):
    """Factor import + zoo + expression evaluation."""

    def setup(self, context: "Context") -> None:
        self.context = context
        cfg = context.config.factor
        self._database = build_factor_database(cfg.database_backend, cfg.zoo_dir)

    def import_factors(self, source: Any, *, kind: str = "csv") -> Any:
        if kind in ("csv", "json", "dict"):
            from alphapilot.systems.factor.loaders.json_loader import (
                FactorExperimentLoaderFromDict,
            )

            if kind == "dict":
                return FactorExperimentLoaderFromDict().load(source)
            import pandas as pd

            records = (
                pd.read_csv(source).to_dict(orient="records")
                if kind == "csv"
                else source
            )
            return FactorExperimentLoaderFromDict().load(records)
        if kind == "pdf":
            from alphapilot.systems.factor.loaders.pdf_loader import (
                FactorExperimentLoaderFromPDFfiles,
            )

            return FactorExperimentLoaderFromPDFfiles().load(source)
        raise ValueError(f"Unsupported factor import kind: {kind!r}")

    def is_acceptable(self, expression: str) -> bool:
        return self._database.is_acceptable(expression)

    def validate_expression(self, expression: str) -> FactorValidationResult:
        return self._database.validate(expression)

    def add_factor(
        self,
        factor_name: str,
        factor_expression: str,
        *,
        save: bool = True,
    ) -> FactorValidationResult:
        """Validate then add a factor; return structured result on failure."""
        name = factor_name.strip()
        expr = factor_expression.strip()
        if not name:
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_MISSING_NAME,
                message="Factor name is required.",
                details=None,
            )

        for item in self.list_factors():
            if item["factor_name"] == name:
                return FactorValidationResult(
                    acceptable=False,
                    code=REJECT_DUPLICATE_NAME,
                    message=f"Factor name '{name}' already exists in the zoo.",
                    details={"factor_name": name},
                )

        validation = self.validate_expression(expr)
        if not validation.acceptable:
            return validation

        for item in self.list_factors():
            if item["factor_expression"].strip() == expr:
                return FactorValidationResult(
                    acceptable=False,
                    code=REJECT_DUPLICATE_EXPRESSION,
                    message="An identical factor expression already exists in the zoo.",
                    details={"factor_name": item["factor_name"]},
                )

        self._database.add(name, expr)
        if save:
            self._database.save()
        return FactorValidationResult(
            acceptable=True,
            code=OK_CODE,
            message=f"Factor '{name}' added.",
            details={"factor_name": name},
        )

    def evaluate_expression(self, expression: str) -> Any:
        from alphapilot.systems.factor.expression import parse_expression

        return parse_expression(expression)

    def list_factors(self) -> list[dict[str, str]]:
        return self._database.list_factors()

    def delete_factor(self, factor_name: str, *, save: bool = True) -> bool:
        removed = self._database.delete(factor_name.strip())
        if removed and save:
            self._database.save()
            self._database.reload()
        return removed

    @property
    def database(self) -> Any:
        return self._database
