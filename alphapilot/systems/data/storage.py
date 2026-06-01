"""Data storage path resolver.

Centralizes the three storage layers the project relies on so that the
previously hardcoded ``~/.qlib/...`` locations all flow from
:class:`~alphapilot.kernel.config.DataConfig`:

* qlib binary store (``provider_uri``)
* raw CSV directory (per adjust mode)
* derived h5 (``daily_pv.h5``)
"""

from __future__ import annotations

from pathlib import Path

from alphapilot.kernel.config import DataConfig


class DataStorage:
    """Resolve data locations from :class:`DataConfig`."""

    def __init__(self, config: DataConfig) -> None:
        self.config = config

    @property
    def qlib_data_dir(self) -> Path:
        return self.config.qlib_data_dir

    @property
    def raw_data_dir(self) -> Path:
        return self.config.raw_data_dir

    @property
    def factor_dir(self) -> Path:
        return self.config.factor_dir

    def raw_dir_for_mode(self, adjust_mode: str = "backward") -> Path:
        """Resolve the raw CSV dir for an adjust mode via the legacy helper."""
        from alphapilot.systems.data.prepare_cn import default_raw_dir

        return default_raw_dir(adjust_mode)
