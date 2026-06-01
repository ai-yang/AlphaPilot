"""AlphaPilot factor-mining module.

This is the LLM-driven factor mining feature, repackaged as a kernel
module. It orchestrates the data / factor / backtest systems through the
engine context while reusing the existing ``AlphaPilotLoop`` internals.
"""

from alphapilot.modules.alpha_mining.module import AlphaMiningModule

__all__ = ["AlphaMiningModule"]
