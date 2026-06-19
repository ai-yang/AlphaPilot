"""Factor management system interface.

Provides factor import (from expressions / CSV / JSON / PDF), a factor
database (zoo), and expression utilities. The default implementation
reuses the existing DSL and ``FactorRegulator``.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from alphapilot.kernel.base import BaseSystem


class BaseFactorSystem(BaseSystem):
    """Import / store / evaluate factors."""

    name = "factor"

    @abstractmethod
    def import_factors(self, source: Any, *, kind: str = "csv") -> Any:
        """Import factors from a source. ``kind`` in {csv, json, pdf, dict}."""

    @abstractmethod
    def is_acceptable(self, expression: str) -> bool:
        """Whether a factor expression is parsable and original enough."""

    @abstractmethod
    def evaluate_expression(self, expression: str) -> Any:
        """Parse/evaluate a factor expression (DSL)."""

    @abstractmethod
    def list_factors(self) -> list[dict[str, Any]]:
        """List all factors in the zoo (each carries a ``categories`` list)."""

    @abstractmethod
    def delete_factor(self, factor_name: str, *, save: bool = True) -> bool:
        """Remove a factor by name from the zoo."""

    @property
    @abstractmethod
    def database(self) -> Any:
        """Return the factor database (zoo)."""

    # ---- Category registry (delegates to the database backend) ----

    @property
    def supports_categories(self) -> bool:
        return getattr(self.database, "supports_categories", False)

    def list_categories(self) -> list[str]:
        """Return all category names in the registry."""
        return self.database.list_categories()

    def create_category(self, name: str) -> bool:
        """Create an (initially empty) category; return True if newly created."""
        return self.database.create_category(name)

    def rename_category(self, old_name: str, new_name: str) -> bool:
        return self.database.rename_category(old_name, new_name)

    def delete_category(self, name: str, *, save: bool = True) -> bool:
        removed = self.database.delete_category(name)
        if removed and save:
            self.database.save()
        return removed

    def set_factor_categories(
        self, factor_name: str, categories: list[str], *, save: bool = True
    ) -> bool:
        """Replace the category set of *factor_name* with *categories*."""
        ok = self.database.set_factor_categories(factor_name, categories)
        if ok and save:
            self.database.save()
        return ok

    def add_factors_to_category(
        self, factor_names: list[str], category: str, *, save: bool = True
    ) -> dict[str, Any]:
        """Add *category* to multiple factors without replacing existing categories."""
        summary = self.database.add_factors_to_category(factor_names, category)
        if summary.get("changed") and save:
            self.database.save()
        return summary

    def remove_factors_from_category(
        self, factor_names: list[str], category: str, *, save: bool = True
    ) -> dict[str, Any]:
        """Remove *category* from multiple factors while preserving other categories."""
        summary = self.database.remove_factors_from_category(factor_names, category)
        if summary.get("changed") and save:
            self.database.save()
        return summary

    def factors_in_category(self, name: str) -> list[dict[str, Any]]:
        return self.database.factors_in_category(name)

    def export_category_csv(self, name: str, output_path: Any) -> int:
        """Export a category's factors to a 2-column CSV; return the row count."""
        return self.database.export_category_csv(name, output_path)
