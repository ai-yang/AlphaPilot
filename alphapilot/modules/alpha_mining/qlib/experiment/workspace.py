"""Compatibility wrapper for qlib workspace location.

Canonical implementation moved to
``alphapilot.systems.backtest.workspace`` so module/adapters import a
single backtest-system owned implementation.
"""

from alphapilot.systems.backtest.workspace import QlibFBWorkspace

__all__ = ["QlibFBWorkspace"]
