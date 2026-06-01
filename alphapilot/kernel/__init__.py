"""AlphaPilot kernel: vnpy-style pluggable engine.

Public API::

    from alphapilot.kernel import MainEngine, build_engine

    engine = build_engine()                 # built-ins + plugin discovery
    data = engine.get_system("data")
    engine.get_module("alpha_mining")
"""

from alphapilot.kernel.base import BaseModule, BaseSystem
from alphapilot.kernel.config import AppConfig
from alphapilot.kernel.context import Context
from alphapilot.kernel.engine import MainEngine, build_engine
from alphapilot.kernel.registry import register_module, register_system

__all__ = [
    "AppConfig",
    "BaseModule",
    "BaseSystem",
    "Context",
    "MainEngine",
    "build_engine",
    "register_module",
    "register_system",
]
