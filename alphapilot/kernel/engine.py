"""MainEngine: the central kernel that holds systems and modules.

Inspired by vnpy's ``MainEngine`` but service-oriented (not event-driven)
since AlphaPilot is a batch research pipeline. The engine:

* owns a single :class:`~alphapilot.kernel.config.AppConfig` + ``Context``;
* registers the four systems (data / factor / model / backtest);
* loads built-in modules and discovers third-party ones via entry points;
* lets modules reach systems exclusively through the ``Context``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alphapilot.kernel.config import AppConfig
from alphapilot.kernel.context import Context
from alphapilot.kernel.registry import (
    MODULE_ENTRY_POINT_GROUP,
    SYSTEM_ENTRY_POINT_GROUP,
    discover_entry_point_classes,
    iter_builtin_modules,
    iter_builtin_systems,
)

if TYPE_CHECKING:
    from alphapilot.kernel.base import BaseModule, BaseSystem


class MainEngine:
    """Central registry + orchestrator for systems and modules."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.load()
        self.context = Context(engine=self, config=self.config)
        self._systems: dict[str, "BaseSystem"] = {}
        self._modules: dict[str, "BaseModule"] = {}

    # ---- Systems ----

    def add_system(self, system: "BaseSystem") -> "BaseSystem":
        if not system.name:
            raise ValueError(f"System {type(system).__name__} must define a name.")
        system.setup(self.context)
        self._systems[system.name] = system
        return system

    def get_system(self, name: str) -> "BaseSystem":
        if name not in self._systems:
            raise KeyError(
                f"System {name!r} not loaded. Available: {sorted(self._systems)}"
            )
        return self._systems[name]

    def has_system(self, name: str) -> bool:
        return name in self._systems

    # ---- Modules ----

    def add_module(self, module: "BaseModule") -> "BaseModule":
        if not module.name:
            raise ValueError(f"Module {type(module).__name__} must define a name.")
        module.setup(self.context)
        self._modules[module.name] = module
        return module

    def get_module(self, name: str) -> "BaseModule":
        if name not in self._modules:
            raise KeyError(
                f"Module {name!r} not loaded. Available: {sorted(self._modules)}"
            )
        return self._modules[name]

    @property
    def modules(self) -> dict[str, "BaseModule"]:
        return dict(self._modules)

    @property
    def systems(self) -> dict[str, "BaseSystem"]:
        return dict(self._systems)

    # ---- Bootstrapping ----

    def load_builtin(self) -> "MainEngine":
        """Instantiate and attach all built-in systems + modules."""
        for name, system_cls in iter_builtin_systems():
            if name not in self._systems:
                self.add_system(system_cls())
        for name, module_cls in iter_builtin_modules():
            if name not in self._modules:
                self.add_module(module_cls())
        return self

    def discover_plugins(self) -> "MainEngine":
        """Discover and attach out-of-tree systems/modules via entry points."""
        for name, system_cls in discover_entry_point_classes(SYSTEM_ENTRY_POINT_GROUP):
            if name not in self._systems:
                self.add_system(system_cls())
        for name, module_cls in discover_entry_point_classes(MODULE_ENTRY_POINT_GROUP):
            if name not in self._modules:
                self.add_module(module_cls())
        return self

    def collect_commands(self) -> dict[str, object]:
        """Aggregate CLI subcommands contributed by all loaded modules."""
        commands: dict[str, object] = {}
        for module in self._modules.values():
            for cmd_name, fn in module.commands().items():
                commands[cmd_name] = fn
        return commands

    def shutdown(self) -> None:
        for system in self._systems.values():
            system.shutdown()


def build_engine(*, discover: bool = True) -> MainEngine:
    """Create a fully-loaded engine (built-ins + optional plugin discovery)."""
    engine = MainEngine().load_builtin()
    if discover:
        engine.discover_plugins()
    return engine
