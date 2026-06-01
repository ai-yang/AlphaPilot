"""Pluggable adapter layer for AlphaPilot.

This package introduces a thin plugin layer around three external
boundaries that used to be hard-wired throughout the project:

* **LLM provider** (``BaseLLMAdapter``) — wraps OpenAI / Azure / local
  models. Default implementation reuses the existing ``APIBackend``.
* **Market data source** (``BaseDataSourceAdapter``) — downloads raw
  market data. Default implementation reuses the baostock A-share
  pipeline.
* **Backtest engine** (``BaseBacktestEngine``) — runs a backtest on a
  workspace. Default implementation reuses the Qlib ``qrun`` workspace.

Usage::

    from alphapilot.adapters import get_llm, get_data_source, get_backtest_engine

    llm = get_llm()                    # default: openai
    text = llm.chat_text("hello")

    ds = get_data_source("baostock_cn")
    ds.download(DataDownloadRequest(start_date="2024-01-01"))

    engine = get_backtest_engine()     # default: qlib
    engine.run(BacktestRequest(workspace_path="/tmp/ws"))

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
    BacktestRequest,
    BacktestResult,
    BaseBacktestEngine,
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
    BACKTEST_REGISTRY,
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


def get_backtest_engine(name: str | None = None, **kwargs: Any) -> BaseBacktestEngine:
    """Return a (cached) backtest engine adapter instance."""
    return BACKTEST_REGISTRY.get(name, **kwargs)


__all__ = [
    "AdapterRegistry",
    "BACKTEST_REGISTRY",
    "BacktestRequest",
    "BacktestResult",
    "BaseBacktestEngine",
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
    "get_backtest_engine",
    "get_data_source",
    "get_llm",
]
