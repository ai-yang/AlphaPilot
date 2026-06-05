"""Default factor management system.

Wraps the factor DSL + the file-based factor zoo, and exposes the
existing JSON/PDF import loaders behind a single ``import_factors`` API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alphapilot.systems.factor.base import BaseFactorSystem
from alphapilot.systems.factor.database import build_factor_database

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
