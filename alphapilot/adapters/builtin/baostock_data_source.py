"""Backward-compatible import path for built-in baostock adapter."""

from alphapilot.adapters.builtin.data_source.baostock_cn import (
    BaostockDataSourceAdapter,
)

__all__ = ["BaostockDataSourceAdapter"]
