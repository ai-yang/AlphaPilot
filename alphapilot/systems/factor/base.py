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
    def list_factors(self) -> list[dict[str, str]]:
        """List all factors in the zoo."""

    @abstractmethod
    def delete_factor(self, factor_name: str, *, save: bool = True) -> bool:
        """Remove a factor by name from the zoo."""

    @property
    @abstractmethod
    def database(self) -> Any:
        """Return the factor database (zoo)."""
