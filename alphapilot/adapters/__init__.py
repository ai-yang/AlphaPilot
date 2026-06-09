"""Pluggable adapter layer for AlphaPilot.

This package introduces a thin plugin layer around two external
boundaries that used to be hard-wired throughout the project:

* **LLM provider** (``BaseLLMAdapter``) — wraps OpenAI / Azure / local
  models. Default implementation reuses the existing ``APIBackend``.
* **Market data source** (``BaseDataSourceAdapter``) — downloads raw
  market data. Default implementation reuses the baostock A-share
  pipeline.

Backtesting is handled directly by :mod:`alphapilot.systems.backtest`
(Qlib ``qrun`` workspace), not through this adapter layer.

Usage::

    from alphapilot.adapters import get_llm, get_data_source

    llm = get_llm()                    # default: openai
    text = llm.chat_text("hello")

    ds = get_data_source("baostock_cn")
    ds.download(DataDownloadRequest(start_date="2024-01-01"))

A third-party adapter can be loaded by name (after ``register``) or by
fully-qualified class path::

    llm = get_llm("my_pkg.adapters.MyLLMAdapter")

See :mod:`alphapilot.adapters.base` for interface details and
``alphapilot/adapters/README.md`` for an end-to-end onboarding guide.
"""

from __future__ import annotations

from typing import Any

# Importing :mod:`builtin` triggers registration of the default adapters.
from alphapilot.adapters import builtin as _builtin  # noqa: F401
from alphapilot.adapters.base import (
    BaseDataSourceAdapter,
    BaseLLMAdapter,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DataDownloadRequest,
    DataDownloadResult,
    EmbeddingResponse,
)
from alphapilot.adapters.registry import (
    DATA_SOURCE_REGISTRY,
    LLM_REGISTRY,
    AdapterRegistry,
)


def get_llm(name: str | None = None, **kwargs: Any) -> BaseLLMAdapter:
    """Return a (cached) LLM adapter instance."""
    return LLM_REGISTRY.get(name, **kwargs)


def get_data_source(name: str | None = None, **kwargs: Any) -> BaseDataSourceAdapter:
    """Return a (cached) data source adapter instance."""
    return DATA_SOURCE_REGISTRY.get(name, **kwargs)


__all__ = [
    "AdapterRegistry",
    "BaseDataSourceAdapter",
    "BaseLLMAdapter",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "DATA_SOURCE_REGISTRY",
    "DataDownloadRequest",
    "DataDownloadResult",
    "EmbeddingResponse",
    "LLM_REGISTRY",
    "get_data_source",
    "get_llm",
]
