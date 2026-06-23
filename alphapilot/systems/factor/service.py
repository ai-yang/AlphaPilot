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
        categories: list[str] | None = None,
        save: bool = True,
    ) -> FactorValidationResult:
        """Validate then add a factor; return structured result on failure.

        *categories* (optional) assigns the new factor to those categories when
        the backend supports a registry; ignored otherwise.
        """
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
        if categories and getattr(self._database, "supports_categories", False):
            self._database.set_factor_categories(name, categories)
        if save:
            self._database.save()
        return FactorValidationResult(
            acceptable=True,
            code=OK_CODE,
            message=f"Factor '{name}' added.",
            details={"factor_name": name, "categories": categories or []},
        )

    def evaluate_expression(self, expression: str) -> Any:
        from alphapilot.systems.factor.expression import parse_expression

        return parse_expression(expression)

    def list_factors(self) -> list[dict[str, Any]]:
        return self._database.list_factors()

    def delete_factor(self, factor_name: str, *, save: bool = True) -> bool:
        removed = self._database.delete(factor_name.strip())
        if removed and save:
            self._database.save()
            self._database.reload()
        return removed

    def rename_factor(
        self, factor_name: str, new_name: str, *, save: bool = True
    ) -> FactorValidationResult:
        """Rename a factor (expression and category links preserved).

        Mirrors ``add_factor``'s name checks: the new name must be non-empty and must not collide
        with an existing factor.
        """
        old = factor_name.strip()
        new = new_name.strip()
        if not new:
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_MISSING_NAME,
                message="New factor name is required.",
                details=None,
            )
        if new == old:
            return FactorValidationResult(
                acceptable=True, code=OK_CODE, message="Name unchanged.", details={"factor_name": old}
            )
        for item in self.list_factors():
            if item["factor_name"] == new:
                return FactorValidationResult(
                    acceptable=False,
                    code=REJECT_DUPLICATE_NAME,
                    message=f"Factor name '{new}' already exists in the zoo.",
                    details={"factor_name": new},
                )
        if not self._database.rename(old, new):
            return FactorValidationResult(
                acceptable=False,
                code=REJECT_MISSING_NAME,
                message=f"Factor '{old}' not found in the zoo.",
                details={"factor_name": old},
            )
        if save:
            self._database.save()
            self._database.reload()
        return FactorValidationResult(
            acceptable=True,
            code=OK_CODE,
            message=f"Factor renamed '{old}' -> '{new}'.",
            details={"factor_name": new, "previous_name": old},
        )

    @property
    def database(self) -> Any:
        return self._database
