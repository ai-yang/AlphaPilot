"""Strategy management system interface.

Provides strategy import (from PDFs / dicts), a strategy parameter database,
and backtest execution (delegated to the backtest system's qlib training path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from abc import abstractmethod
from typing import Any

from alphapilot.kernel.base import BaseSystem


@dataclass
class StrategyModelSpec:
    """Model definition used by a strategy."""

    model_name: str
    hyper_params: dict[str, Any] = field(default_factory=dict)
    trained_artifact_uri: str | None = None
    fitted_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyMetrics:
    """Backtest/evaluation metrics for a strategy."""

    ic: float | None = None
    icir: float | None = None
    rank_ic: float | None = None
    rank_icir: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyRecord:
    """
    Persistable strategy snapshot.

    ``factor_formulas`` is intentionally unbounded to support single-factor and
    multi-factor strategies with arbitrary formula complexity.
    """

    strategy_name: str
    factor_formulas: list[str] = field(default_factory=list)
    model: StrategyModelSpec | None = None
    metrics: StrategyMetrics | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategySystem(BaseSystem):
    """Import / store params / run strategy backtests."""

    name = "strategy"

    @abstractmethod
    def import_strategy(self, source: Any, *, kind: str = "pdf") -> Any:
        """Import a strategy definition from a source (pdf / dict)."""

    @abstractmethod
    def train(self, experiment: Any, *, use_local: bool | None = None) -> Any:
        """Train / backtest an experiment via the backtest system."""

    @abstractmethod
    def register_strategy(self, record: StrategyRecord) -> None:
        """Persist a strategy asset record into the strategy system."""

    @abstractmethod
    def get_strategy(self, strategy_name: str) -> StrategyRecord | None:
        """Load a strategy asset record by name."""

    @abstractmethod
    def list_strategy_records(self) -> list[StrategyRecord]:
        """List all persisted strategy asset records."""

    @property
    @abstractmethod
    def param_database(self) -> Any:
        """Return the strategy parameter database."""
