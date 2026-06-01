"""Execution context handed to systems and modules.

The context is the single entry point a module uses to reach the four
systems and shared services (LLM adapter, config). Modules MUST go
through the context instead of importing qlib/baostock or concrete
system classes directly, which keeps them decoupled and swappable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alphapilot.kernel.config import AppConfig
    from alphapilot.kernel.engine import MainEngine
    from alphapilot.systems.backtest.base import BaseBacktestSystem
    from alphapilot.systems.data.base import BaseDataSystem
    from alphapilot.systems.factor.base import BaseFactorSystem
    from alphapilot.systems.strategy.base import BaseStrategySystem


class Context:
    """Thin accessor over the engine's systems + shared services."""

    def __init__(self, engine: "MainEngine", config: "AppConfig") -> None:
        self.engine = engine
        self.config = config

    # ---- System accessors (typed convenience wrappers) ----

    def data(self) -> "BaseDataSystem":
        return self.engine.get_system("data")

    def factor(self) -> "BaseFactorSystem":
        return self.engine.get_system("factor")

    def strategy(self) -> "BaseStrategySystem":
        return self.engine.get_system("strategy")

    def backtest(self) -> "BaseBacktestSystem":
        return self.engine.get_system("backtest")

    def system(self, name: str) -> Any:
        return self.engine.get_system(name)

    # ---- Shared services ----

    def get_llm(self, name: str | None = None, **kwargs: Any) -> Any:
        """Return an LLM adapter (defaults to configured provider)."""
        from alphapilot.adapters import get_llm

        return get_llm(name or self.config.llm.provider, **kwargs)
