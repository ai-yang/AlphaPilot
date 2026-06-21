"""AlphaPilot: LLM-driven alpha factor mining with Qlib backtesting."""

# Restore NumPy-2-removed aliases before any dependency (dask via lightgbm/qlib)
# that still references them gets imported. Must run first; no-op on NumPy 1.x.
from alphapilot import _numpy_compat as _numpy_compat  # noqa: F401  (side-effecting import)

__all__ = ["__version__"]

try:
    from importlib.metadata import version

    __version__ = version("alphapilot")
except Exception:  # noqa: BLE001 - optional when running from source tree
    __version__ = "0.0.0"
