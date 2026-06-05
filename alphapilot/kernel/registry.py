"""Registries for kernel systems and modules.

Two mechanisms are supported:

1. **In-tree registration** via :func:`register_system` / :func:`register_module`
   (or class-path strings), used by the built-in systems and modules.
2. **Out-of-tree discovery** via Python entry points, so third-party pip
   packages can contribute systems/modules without touching this repo
   (the vnpy-style plugin model). See :func:`discover_entry_point_classes`.

Entry point groups:
    - ``alphapilot.systems`` -> ``BaseSystem`` subclasses
    - ``alphapilot.modules`` -> ``BaseModule`` subclasses
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from alphapilot.kernel.base import BaseModule, BaseSystem

SYSTEM_ENTRY_POINT_GROUP = "alphapilot.systems"
MODULE_ENTRY_POINT_GROUP = "alphapilot.modules"


# In-tree registries: name -> class path or class.
_SYSTEM_CLASSES: dict[str, object] = {}
_MODULE_CLASSES: dict[str, object] = {}


def register_system(name: str, cls_or_path: object) -> None:
    _SYSTEM_CLASSES[name] = cls_or_path


def register_module(name: str, cls_or_path: object) -> None:
    _MODULE_CLASSES[name] = cls_or_path


def _resolve(cls_or_path: object) -> type:
    """Resolve a class object or ``pkg.mod.Cls`` string to a class."""
    if isinstance(cls_or_path, str):
        module_path, cls_name = cls_or_path.rsplit(".", 1)
        return getattr(import_module(module_path), cls_name)
    return cls_or_path  # type: ignore[return-value]


def iter_builtin_systems() -> Iterator[tuple[str, type["BaseSystem"]]]:
    for name, ref in _SYSTEM_CLASSES.items():
        yield name, _resolve(ref)


def iter_builtin_modules() -> Iterator[tuple[str, type["BaseModule"]]]:
    for name, ref in _MODULE_CLASSES.items():
        yield name, _resolve(ref)


def discover_entry_point_classes(group: str) -> Iterator[tuple[str, type]]:
    """Yield ``(name, class)`` for every entry point in *group*.

    Failures to import a single plugin are skipped (best-effort), so one
    broken third-party package does not break engine startup.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - py<3.8 fallback
        return

    try:
        eps = entry_points(group=group)
    except TypeError:  # pragma: no cover - older API returns a dict
        eps = entry_points().get(group, [])  # type: ignore[attr-defined]

    for ep in eps:
        try:
            yield ep.name, ep.load()
        except Exception:  # noqa: BLE001 - best-effort discovery
            continue


def _register_builtin_defaults() -> None:
    """Register the four built-in systems + the alpha_mining module.

    Uses class-path strings so importing this module stays cheap and does
    not pull qlib/baostock until a system is actually instantiated.
    """
    register_system("data", "alphapilot.systems.data.service.QlibDataSystem")
    register_system("factor", "alphapilot.systems.factor.service.FactorSystem")
    register_system("strategy", "alphapilot.systems.strategy.service.StrategySystem")
    register_system("backtest", "alphapilot.systems.backtest.service.QlibBacktestSystem")
    register_module(
        "alpha_mining",
        "alphapilot.modules.alpha_mining.module.AlphaMiningModule",
    )
    register_module(
        "platform",
        "alphapilot.modules.platform.module.PlatformModule",
    )
    register_module(
        "data_viz",
        "alphapilot.modules.data_viz.module.DataVizModule",
    )
    register_module(
        "portal",
        "alphapilot.modules.portal.module.PortalModule",
    )
    register_module(
        "backtest_viz",
        "alphapilot.modules.backtest_viz.module.BacktestVizModule",
    )


_register_builtin_defaults()
