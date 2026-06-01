"""Kernel base classes: systems and modules.

A *system* is a long-lived capability provider (data / factor / model /
backtest). A *module* is a pluggable feature that orchestrates the
systems (e.g. the AlphaPilot factor-mining loop).

Both are wired through the :class:`~alphapilot.kernel.engine.MainEngine`
and receive a :class:`~alphapilot.kernel.context.Context` in ``setup``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class BaseSystem(ABC):
    """A capability provider registered on the engine.

    Subclasses must set a unique :attr:`name`. ``setup`` is called once
    when the system is attached to the engine; ``shutdown`` on teardown.
    """

    name: str = ""

    def setup(self, context: "Context") -> None:  # noqa: B027 - optional hook
        """Bind the system to the engine context. Override if needed."""
        self.context = context

    def shutdown(self) -> None:  # noqa: B027 - optional hook
        """Release resources. Override if needed."""


class BaseModule(ABC):
    """A pluggable feature orchestrating one or more systems."""

    name: str = ""

    def setup(self, context: "Context") -> None:  # noqa: B027 - optional hook
        """Bind the module to the engine context. Override if needed."""
        self.context = context

    def commands(self) -> dict[str, Callable[..., Any]]:
        """Return CLI subcommands contributed by this module.

        Maps command name -> callable. Default: no commands.
        """
        return {}
