"""Model management system interface.

Provides model import (from PDFs / dicts), a model parameter database,
and training (delegated to the backtest system's qlib training path).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from alphapilot.kernel.base import BaseSystem


class BaseModelSystem(BaseSystem):
    """Import / store params / train models."""

    name = "model"

    @abstractmethod
    def import_model(self, source: Any, *, kind: str = "pdf") -> Any:
        """Import a model definition from a source (pdf / dict)."""

    @abstractmethod
    def train(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        """Train / backtest a model experiment via the backtest system."""

    @property
    @abstractmethod
    def param_database(self) -> Any:
        """Return the model parameter database."""
