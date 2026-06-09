"""Adapter registry + factory.

Two independent registries are exposed for LLM and data source adapters.
Each registry supports:

* ``register(name, cls)`` — explicit registration (or decorator usage).
* ``get(name)`` — instantiate by name (or class path ``pkg.mod.Cls``).
* ``set_default(name)`` — declare which adapter ``get()`` returns when
  the caller does not specify a name.

Instances are cached per ``(name, kwargs)`` to keep heavy backends
(e.g. an LLM client) from being re-created on every call.
"""

from __future__ import annotations

import threading
from importlib import import_module
from typing import Any, Generic, TypeVar

from alphapilot.adapters.base import (
    BaseDataSourceAdapter,
    BaseLLMAdapter,
)

T = TypeVar("T")


class AdapterRegistry(Generic[T]):
    """Generic adapter registry with lazy import + instance cache."""

    def __init__(self, kind: str, base_cls: type[T]) -> None:
        self._kind = kind
        self._base_cls = base_cls
        self._classes: dict[str, type[T]] = {}
        self._instances: dict[tuple, T] = {}
        self._default: str | None = None
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        cls: type[T] | None = None,
        *,
        is_default: bool = False,
    ) -> Any:
        """Register an adapter class. Usable as a decorator.

        Examples
        --------
        >>> @LLM_REGISTRY.register("my_llm")
        ... class MyLLM(BaseLLMAdapter):
        ...     ...
        """

        def _do_register(target_cls: type[T]) -> type[T]:
            if not issubclass(target_cls, self._base_cls):
                raise TypeError(
                    f"{target_cls!r} must subclass {self._base_cls.__name__}"
                )
            self._classes[name] = target_cls
            target_cls.name = name  # type: ignore[attr-defined]
            if is_default or self._default is None:
                self._default = name
            return target_cls

        if cls is not None:
            return _do_register(cls)
        return _do_register

    def set_default(self, name: str) -> None:
        if name not in self._classes:
            raise KeyError(f"Adapter {name!r} not registered for {self._kind}.")
        self._default = name

    def available(self) -> list[str]:
        return sorted(self._classes)

    def _resolve_class(self, name: str | None) -> tuple[str, type[T]]:
        if name is None:
            if self._default is None:
                raise RuntimeError(
                    f"No default {self._kind} adapter registered. "
                    f"Available: {self.available()}"
                )
            name = self._default
        if name in self._classes:
            return name, self._classes[name]
        # Allow ``pkg.mod.Cls`` style for ad-hoc / out-of-tree adapters.
        if "." in name:
            module_path, cls_name = name.rsplit(".", 1)
            cls = getattr(import_module(module_path), cls_name)
            if not isinstance(cls, type) or not issubclass(cls, self._base_cls):
                raise TypeError(
                    f"{name!r} is not a subclass of {self._base_cls.__name__}"
                )
            return name, cls
        raise KeyError(
            f"{self._kind} adapter {name!r} not found. "
            f"Available: {self.available()}"
        )

    def get(self, name: str | None = None, /, **kwargs: Any) -> T:
        """Instantiate (and cache) an adapter by name or class path."""
        resolved_name, cls = self._resolve_class(name)
        cache_key = (resolved_name, tuple(sorted(kwargs.items())))
        with self._lock:
            inst = self._instances.get(cache_key)
            if inst is None:
                inst = cls(**kwargs)
                self._instances[cache_key] = inst
            return inst

    def clear_cache(self) -> None:
        with self._lock:
            self._instances.clear()


LLM_REGISTRY: AdapterRegistry[BaseLLMAdapter] = AdapterRegistry(
    "llm", BaseLLMAdapter
)
DATA_SOURCE_REGISTRY: AdapterRegistry[BaseDataSourceAdapter] = AdapterRegistry(
    "data_source", BaseDataSourceAdapter
)
