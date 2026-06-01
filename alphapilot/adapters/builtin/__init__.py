"""Built-in adapter implementations.

Importing this package registers the default LLM / data source /
backtest engines so that :func:`alphapilot.adapters.get_*` works out
of the box.
"""

from alphapilot.adapters.builtin.data_source.baostock_cn import (
    BaostockDataSourceAdapter,
)
from alphapilot.adapters.builtin.llm.openai import APIBackendLLMAdapter
from alphapilot.adapters.builtin.backtest.qlib import QlibBacktestEngine

__all__ = [
    "APIBackendLLMAdapter",
    "BaostockDataSourceAdapter",
    "QlibBacktestEngine",
]
