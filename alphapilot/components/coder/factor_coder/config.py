import sys
from pathlib import Path

from pydantic import Field

from alphapilot.components.coder.CoSTEER.config import CoSTEERSettings
from alphapilot.core.conf import ExtendedSettingsConfigDict


def default_factor_python_bin() -> str:
    return sys.executable


def resolve_factor_python_bin() -> str:
    """Resolve Python for subprocess factor execution (env > explicit path > current interpreter)."""
    configured = FACTOR_COSTEER_SETTINGS.python_bin
    if configured in ("python", "python3", ""):
        return sys.executable
    path = Path(configured).expanduser()
    if path.is_file():
        return str(path.resolve())
    import shutil

    found = shutil.which(configured)
    return found if found else sys.executable


class FactorCoSTEERSettings(CoSTEERSettings):
    model_config = ExtendedSettingsConfigDict(env_prefix="FACTOR_CoSTEER_")

    data_folder: str = "git_ignore_folder/factor_implementation_source_data"
    """Path to the folder containing financial data (default is fundamental data in Qlib)"""

    data_folder_debug: str = "git_ignore_folder/factor_implementation_source_data_debug"
    """Path to the folder containing partial financial data (for debugging)"""

    simple_background: bool = True
    """Whether to use simple background information for code feedback"""

    file_based_execution_timeout: int = 1200
    """Timeout in seconds for each factor implementation execution"""

    select_method: str = "random"
    """Method for the selection of factors implementation"""

    python_bin: str = Field(default_factory=default_factor_python_bin)
    """Python binary for factor.py subprocess; defaults to the current interpreter."""


FACTOR_COSTEER_SETTINGS = FactorCoSTEERSettings()
