"""Typed requests/results for the backtest system API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FactorDefinition:
    """Declarative factor input for high-level backtest API."""

    factor_name: str
    factor_expression: str


@dataclass
class FactorBacktestRequest:
    """Run a factor backtest from csv path or in-memory factor definitions."""

    factor_path: str | Path | None = None
    factors: list[FactorDefinition] = field(default_factory=list)
    scenario: str = "factor_backtest"
    use_local: bool | None = None


@dataclass
class FactorBacktestResult:
    """Result returned by high-level factor backtest API."""

    experiment: Any
    metrics: Any


@dataclass
class FactorExperimentBacktestRequest:
    """Run backtest for an in-memory factor experiment object."""

    experiment: Any
    use_local: bool | None = None


@dataclass
class ModelExperimentBacktestRequest:
    """Run training/backtest for an in-memory model experiment object."""

    experiment: Any
    use_local: bool | None = None
    run_env: dict[str, str] = field(default_factory=dict)


@dataclass
class WorkspaceBacktestRequest:
    """Run qlib backtest on an existing workspace directory."""

    workspace_path: str | Path
    config_name: str = "conf.yaml"
    use_local: bool | None = None
    run_env: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkspaceBacktestResult:
    """Standardized workspace run result."""

    metrics: Any
    workspace_path: Path
    log: str | None = None
    raw: Any = None
