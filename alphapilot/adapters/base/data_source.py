"""Abstract interface for market data sources.

A data source is responsible for fetching raw market data into a local
directory (and any auxiliary artifacts such as adjustment factors).
Downstream conversion to a specific format (e.g. Qlib binary) is the
responsibility of separate utilities, so different data sources stay
swappable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DataDownloadRequest:
    start_date: str
    end_date: str | None = None
    symbols: list[str] | None = None
    output_dir: str | Path | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataDownloadResult:
    output_dir: Path
    symbols: list[str]
    extra: dict[str, Any] = field(default_factory=dict)


class BaseDataSourceAdapter(ABC):
    """Unified interface for downloading market data."""

    name: str = ""

    @abstractmethod
    def download(self, request: DataDownloadRequest) -> DataDownloadResult:
        """Download raw data and return a description of what was written."""

    def default_output_dir(self) -> Path:
        """Default output directory. Subclasses may override."""
        return Path.home() / ".alphapilot" / "data" / (self.name or "raw")
