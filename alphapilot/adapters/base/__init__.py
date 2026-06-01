"""Adapter abstract base classes + DTOs."""

from alphapilot.adapters.base.backtest import (
    BacktestRequest,
    BacktestResult,
    BaseBacktestEngine,
)
from alphapilot.adapters.base.data_source import (
    BaseDataSourceAdapter,
    DataDownloadRequest,
    DataDownloadResult,
)
from alphapilot.adapters.base.llm import (
    BaseLLMAdapter,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
)

__all__ = [
    "BacktestRequest",
    "BacktestResult",
    "BaseBacktestEngine",
    "BaseDataSourceAdapter",
    "BaseLLMAdapter",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "DataDownloadRequest",
    "DataDownloadResult",
    "EmbeddingResponse",
]
