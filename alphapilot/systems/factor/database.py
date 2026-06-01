"""Factor database (factor zoo) abstraction.

Provides a small storage-agnostic facade over the existing
``FactorRegulator`` + CSV factor zoo. The default backend is file-based
(CSV); a SQLite backend can be added later behind the same interface
without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseFactorDatabase(ABC):
    """Store / dedup / query mined factor expressions."""

    @abstractmethod
    def is_acceptable(self, expression: str) -> bool:
        """Whether *expression* is parsable and original enough to keep."""

    @abstractmethod
    def add(self, factor_name: str, factor_expression: str) -> bool:
        """Add a factor to the zoo; return True if added."""

    @abstractmethod
    def save(self, output_path: str | None = None) -> None:
        """Persist the zoo to disk."""


class FileFactorDatabase(BaseFactorDatabase):
    """CSV-backed factor zoo wrapping the legacy ``FactorRegulator``."""

    def __init__(self, zoo_dir: Path, duplication_threshold: int = 8) -> None:
        self.zoo_dir = Path(zoo_dir)
        self.zoo_path = self.zoo_dir / "factor_zoo.csv"
        self._regulator: Any | None = None
        self._duplication_threshold = duplication_threshold

    @property
    def regulator(self) -> Any:
        if self._regulator is None:
            from alphapilot.systems.factor.regulator.factor_regulator import FactorRegulator

            zoo_path = str(self.zoo_path) if self.zoo_path.exists() else None
            self._regulator = FactorRegulator(
                factor_zoo_path=zoo_path,
                duplication_threshold=self._duplication_threshold,
            )
        return self._regulator

    def is_acceptable(self, expression: str) -> bool:
        reg = self.regulator
        if not reg.is_parsable(expression):
            return False
        ok, eval_dict = reg.evaluate(expression)
        if not ok or eval_dict is None:
            return False
        return reg.is_expression_acceptable(eval_dict)

    def add(self, factor_name: str, factor_expression: str) -> bool:
        return self.regulator.add_factor(factor_name, factor_expression)

    def save(self, output_path: str | None = None) -> None:
        self.zoo_dir.mkdir(parents=True, exist_ok=True)
        self.regulator.save_factor_zoo(output_path or str(self.zoo_path))


def build_factor_database(backend: str, zoo_dir: Path) -> BaseFactorDatabase:
    """Factory: build a factor database for the configured backend."""
    if backend == "file":
        return FileFactorDatabase(zoo_dir)
    raise ValueError(f"Unsupported factor database backend: {backend!r}")
