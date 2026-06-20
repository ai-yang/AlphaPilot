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
    qlib_config_name: str | None = None
    qlib_template_dir: str | None = None
    use_local: bool | None = None
    run_env: dict[str, str] = field(default_factory=dict)
    mode: str = "multi_combined"
    """``multi_combined`` (default) | ``single_ic`` | ``multi_sequential`` (roadmap Phase 2/3)."""
    yaml_params: Any = None
    """Optional ``QlibYamlParams`` (or plain dict) rendered into the workspace yaml to
    override model / strategy / dataset. ``None`` keeps today's static template behavior."""
    market: str | None = None
    """Instrument-pool name for the factor h5 spec; ``None`` resolves from yaml_params/default."""
    factor_data_dir: str | Path | None = None
    """Reuse an already-built factor h5 cache dir (``<spec_hash>/``) instead of building."""
    factor_data_fingerprint: str | None = None
    """Optional fingerprint of the reused factor data (informational / cache keying)."""


@dataclass
class FactorBacktestResult:
    """Result returned by high-level factor backtest API."""

    experiment: Any
    metrics: Any
    mode: str = "multi_combined"
    per_factor: list[dict] | None = None
    """Per-factor rows for ``single_ic`` (IC/RankIC/ICIR) and ``multi_sequential``
    (per-factor portfolio metrics); ``None`` for ``multi_combined``."""


@dataclass
class FactorExperimentBacktestRequest:
    """Run backtest for an in-memory factor experiment object."""

    experiment: Any
    qlib_config_name: str | None = None
    use_local: bool | None = None
    pickle_cache_scope: str | None = "backtest"
    """``mine`` | ``backtest`` — selects separate pickle cache roots from env."""
    pickle_cache_folder: str | Path | None = None
    """Optional absolute/relative override for the pickle cache root directory."""
    yaml_params: Any = None
    """Optional ``QlibYamlParams`` (or dict) rendered into the workspace yaml; ``None`` =
    today's static template behavior."""
    market: str | None = None
    """Instrument-pool name for the factor h5 spec; ``None`` resolves from yaml_params/default."""
    factor_data_dir: str | Path | None = None
    """Reuse an already-built factor h5 cache dir (``<spec_hash>/``) instead of building."""


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


@dataclass
class SavedModelBacktestRequest:
    """Run backtest with saved model artifact + factors on target data."""

    model_pickle_path: str | Path
    factors: list[FactorDefinition] = field(default_factory=list)
    scenario: str = "factor_backtest"
    qlib_config_name: str | None = None
    qlib_template_dir: str | None = None
    qlib_data_dir: str | None = None
    use_local: bool | None = None
    options: dict[str, Any] = field(default_factory=dict)
    market: str | None = None
    """Instrument-pool name for the factor h5 spec; ``None`` resolves from yaml_params/default."""
