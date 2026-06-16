"""Central application configuration for the kernel.

This consolidates paths and runtime knobs that used to be hardcoded across
``systems/data``, ``modules/alpha_mining/qlib`` and ``core/conf``. It is intentionally
dependency-light (plain dataclass + env overrides) so the kernel can be
imported without pydantic / qlib being installed.

Precedence (low -> high): dataclass defaults -> environment variables.
Each system reads the paths it needs from a single :class:`AppConfig`
instance, which makes relocation and二开 far less error-prone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from alphapilot.kernel.paths import factor_zoo_dir, strategy_zoo_dir

# Defaults aligned with alphapilot.core.pickle_cache (env names must stay in sync).
def _default_pickle_cache_dir_mine() -> Path:
    from alphapilot.core.pickle_cache import default_pickle_cache_dir_mine

    return default_pickle_cache_dir_mine()


def _default_pickle_cache_dir_backtest() -> Path:
    from alphapilot.core.pickle_cache import default_pickle_cache_dir_backtest

    return default_pickle_cache_dir_backtest()


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_str_legacy(name: str, legacy_name: str, default: str) -> str:
    return os.getenv(name) or os.getenv(legacy_name, default)


def _env_path_legacy(name: str, legacy_name: str, default: Path) -> Path:
    value = os.getenv(name) or os.getenv(legacy_name)
    return Path(value).expanduser() if value else default


from alphapilot.systems.data.data_paths import (
    existing_baostock_factor_dir,
    existing_baostock_qlib_dir,
    existing_baostock_raw_dir,
)


def _default_qlib_data_dir() -> Path:
    return _env_path("ALPHAPILOT_QLIB_DATA_DIR", existing_baostock_qlib_dir())


def _default_raw_data_dir() -> Path:
    return _env_path("ALPHAPILOT_RAW_DATA_DIR", existing_baostock_raw_dir("backward"))


def _default_factor_dir() -> Path:
    return _env_path("ALPHAPILOT_ADJUST_FACTOR_DIR", existing_baostock_factor_dir())


@dataclass
class DataConfig:
    """Locations for raw / converted / derived market data."""

    qlib_data_dir: Path = field(default_factory=_default_qlib_data_dir)
    raw_data_dir: Path = field(default_factory=_default_raw_data_dir)
    factor_dir: Path = field(default_factory=_default_factor_dir)
    region: str = field(default_factory=lambda: _env_str("ALPHAPILOT_REGION", "cn"))


@dataclass
class BacktestConfig:
    """Backtest artifact paths and runtime options (Qlib execution lives in systems/backtest)."""

    use_local: bool = field(
        default_factory=lambda: os.getenv("USE_LOCAL", "True").lower() in ("true", "1")
    )
    workspace_root: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_WORKSPACE_ROOT",
            Path.cwd() / "git_ignore_folder" / "RD-Agent_workspace",
        )
    )
    pickle_cache_dir_mine: Path = field(default_factory=_default_pickle_cache_dir_mine)
    pickle_cache_dir_backtest: Path = field(default_factory=_default_pickle_cache_dir_backtest)
    pickle_cache_enabled: bool = field(
        default_factory=lambda: os.getenv("ALPHAPILOT_PICKLE_CACHE_ENABLED", "true").lower()
        in ("true", "1", "yes")
    )


@dataclass
class FactorConfig:
    """Factor database / zoo location + selection."""

    database_backend: str = field(
        default_factory=lambda: _env_str("ALPHAPILOT_FACTOR_DB_BACKEND", "file")
    )
    zoo_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_FACTOR_ZOO_DIR",
            factor_zoo_dir(),
        )
    )


@dataclass
class StrategyConfig:
    """Strategy param database location + selection."""

    database_backend: str = field(
        default_factory=lambda: _env_str_legacy(
            "ALPHAPILOT_STRATEGY_DB_BACKEND",
            "ALPHAPILOT_MODEL_DB_BACKEND",
            "file",
        )
    )
    param_dir: Path = field(
        default_factory=lambda: _env_path_legacy(
            "ALPHAPILOT_STRATEGY_PARAM_DIR",
            "ALPHAPILOT_MODEL_PARAM_DIR",
            strategy_zoo_dir(),
        )
    )


@dataclass
class LLMConfig:
    """LLM provider selection (delegates credentials to oai/llm_conf)."""

    provider: str = field(default_factory=lambda: _env_str("ALPHAPILOT_LLM_PROVIDER", "openai"))


@dataclass
class AppConfig:
    """Top-level config object held by :class:`MainEngine`."""

    data: DataConfig = field(default_factory=DataConfig)
    factor: FactorConfig = field(default_factory=FactorConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    log_dir: Path = field(
        default_factory=lambda: _env_path("ALPHAPILOT_LOG_DIR", Path.cwd() / "log")
    )

    @classmethod
    def load(cls) -> "AppConfig":
        """Build config from defaults + environment variables."""
        return cls()

    def summary(self) -> str:
        """Human-readable resolved config (for startup diagnostics)."""
        return (
            "AppConfig(\n"
            f"  data.qlib_data_dir={self.data.qlib_data_dir}\n"
            f"  data.raw_data_dir={self.data.raw_data_dir}\n"
            f"  factor.zoo_dir={self.factor.zoo_dir}\n"
            f"  strategy.param_dir={self.strategy.param_dir}\n"
            f"  backtest.use_local={self.backtest.use_local}\n"
            f"  backtest.workspace_root={self.backtest.workspace_root}\n"
            f"  backtest.pickle_cache_dir_mine={self.backtest.pickle_cache_dir_mine}\n"
            f"  backtest.pickle_cache_dir_backtest={self.backtest.pickle_cache_dir_backtest}\n"
            f"  backtest.pickle_cache_enabled={self.backtest.pickle_cache_enabled}\n"
            f"  llm.provider={self.llm.provider}\n"
            f"  log_dir={self.log_dir}\n"
            ")"
        )
