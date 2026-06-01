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


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass
class DataConfig:
    """Locations for raw / converted / derived market data."""

    qlib_data_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_QLIB_DATA_DIR",
            Path("~/.qlib/qlib_data/cn_data").expanduser(),
        )
    )
    raw_data_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_RAW_DATA_DIR",
            Path("~/.qlib/qlib_data/cn_data/raw_data_back_adjust").expanduser(),
        )
    )
    factor_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_ADJUST_FACTOR_DIR",
            Path("~/.qlib/qlib_data/cn_data/adjust_factors").expanduser(),
        )
    )
    region: str = field(default_factory=lambda: _env_str("ALPHAPILOT_REGION", "cn"))


@dataclass
class BacktestConfig:
    """Backtest engine selection + artifact roots."""

    engine: str = field(default_factory=lambda: _env_str("ALPHAPILOT_BACKTEST_ENGINE", "qlib"))
    use_local: bool = field(
        default_factory=lambda: os.getenv("USE_LOCAL", "True").lower() in ("true", "1")
    )
    workspace_root: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_WORKSPACE_ROOT",
            Path.cwd() / "git_ignore_folder" / "RD-Agent_workspace",
        )
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
            Path.cwd() / "git_ignore_folder" / "factor_zoo",
        )
    )


@dataclass
class ModelConfig:
    """Model param database location + selection."""

    database_backend: str = field(
        default_factory=lambda: _env_str("ALPHAPILOT_MODEL_DB_BACKEND", "file")
    )
    param_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_MODEL_PARAM_DIR",
            Path.cwd() / "git_ignore_folder" / "model_zoo",
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
    model: ModelConfig = field(default_factory=ModelConfig)
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
            f"  model.param_dir={self.model.param_dir}\n"
            f"  backtest.engine={self.backtest.engine} use_local={self.backtest.use_local}\n"
            f"  backtest.workspace_root={self.backtest.workspace_root}\n"
            f"  llm.provider={self.llm.provider}\n"
            f"  log_dir={self.log_dir}\n"
            ")"
        )
