"""Built-in adapter implementations.

Importing this package registers the default LLM and data source
adapters so that :func:`alphapilot.adapters.get_*` works out of the box.
"""

from alphapilot.adapters.builtin.data_source.baostock_cn import (
    BaostockDataSourceAdapter,
)
from alphapilot.adapters.builtin.data_source.tushare_cn import (
    TushareDataSourceAdapter,
)
from alphapilot.adapters.builtin.llm.openai import APIBackendLLMAdapter

__all__ = [
    "APIBackendLLMAdapter",
    "BaostockDataSourceAdapter",
    "TushareDataSourceAdapter",
]
