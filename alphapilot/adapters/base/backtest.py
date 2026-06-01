"""Abstract interface for backtest engines.

A backtest engine takes a workspace (a directory containing the factor
implementation + configuration files) and produces a standardized result
(metrics + return series).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BacktestRequest:
    workspace_path: str | Path
    config_name: str = "conf.yaml"
    run_env: dict[str, str] = field(default_factory=dict)
    use_local: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    metrics: Any
    workspace_path: Path
    log: str | None = None
    raw: Any = None


class BaseBacktestEngine(ABC):
    """Unified interface for running a backtest end-to-end."""

    name: str = ""

    @abstractmethod
    def run(self, request: BacktestRequest) -> BacktestResult:
        """Execute the backtest described by *request*."""
