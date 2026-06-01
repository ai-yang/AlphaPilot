"""AlphaPilot: LLM-driven alpha factor mining with Qlib backtesting."""

__all__ = ["__version__"]

try:
    from importlib.metadata import version

    __version__ = version("alphapilot")
except Exception:  # noqa: BLE001 - optional when running from source tree
    __version__ = "0.0.0"
