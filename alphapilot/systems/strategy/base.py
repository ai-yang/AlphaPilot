"""Strategy management system interface.

Provides strategy import (from PDFs / dicts), a strategy parameter database,
and backtest execution (delegated to the backtest system's qlib training path).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from alphapilot.kernel.base import BaseSystem


class BaseStrategySystem(BaseSystem):
    """Import / store params / run strategy backtests."""

    name = "strategy"

    @abstractmethod
    def import_strategy(self, source: Any, *, kind: str = "pdf") -> Any:
        """Import a strategy definition from a source (pdf / dict)."""

    @abstractmethod
    def train(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        """Train / backtest an experiment via the backtest system."""

    @property
    @abstractmethod
    def param_database(self) -> Any:
        """Return the strategy parameter database."""
