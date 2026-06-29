"""Typed requests for the data system API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DataDownloadCommand:
    """Download raw market data via a configurable data-source adapter."""

    start_date: str
    end_date: str | None = None
    symbols: list[str] | None = None
    source: str | None = None
    output_dir: str | Path | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataConvertCommand:
    """Convert downloaded raw data into qlib binary store."""

    adjust_mode: str = "backward"
    stock_csv: str | Path | None = None
    qlib_dir: str | Path | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataPipelineCommand:
    """Run full download -> adjust -> convert pipeline."""

    start_date: str = "2005-01-01"
    end_date: str | None = None
    adjust_mode: str = "backward"
    stock_csv: str | Path | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataActionCommand:
    """Legacy-compatible action dispatch request for prepare_data CLI."""

    action: str
    start_date: str = "2005-01-01"
    end_date: str | None = None
    stock_csv: str | Path | None = None
    adjust_mode: str = "backward"
    market: str | None = None
    qlib_dir: str | Path | None = None
    output_dir: str | Path | None = None
    options: dict[str, Any] = field(default_factory=dict)
