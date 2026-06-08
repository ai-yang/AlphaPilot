"""Data management system interface.

Responsible for the full market-data lifecycle: download, adjustment,
conversion to the backtest store (Qlib binary), and derived artifacts
(``daily_pv.h5``) consumed by factor calculation. Storage paths come from
:class:`~alphapilot.kernel.config.DataConfig` instead of hardcoded values.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from alphapilot.kernel.base import BaseSystem
from alphapilot.systems.data.types import (
    DataActionCommand,
    DataBuildH5Command,
    DataConvertCommand,
    DataDownloadCommand,
    DataPipelineCommand,
)


class BaseDataSystem(BaseSystem):
    """Download / convert / store market data."""

    name = "data"

    @abstractmethod
    def download(
        self,
        start_date: str,
        end_date: str | None = None,
        *,
        symbols: list[str] | None = None,
        **options: Any,
    ) -> Any:
        """Download raw market data via the configured data-source provider."""

    @abstractmethod
    def convert(self, **options: Any) -> Any:
        """Convert raw CSV into the backtest data store (e.g. Qlib binary)."""

    @abstractmethod
    def build_h5(self, **options: Any) -> Any:
        """Build the derived ``daily_pv`` h5 used by factor calculation."""

    @abstractmethod
    def get_universe(self, **options: Any) -> Any:
        """Return the configured stock universe / pool."""

    @abstractmethod
    def run_action(self, action: str, **options: Any) -> Any:
        """Run a named prepare-data action through a unified entrypoint."""

    # ---- Single-stock management ----

    @abstractmethod
    def list_symbols(self, adjust_mode: Any = None) -> Any:
        """List the stock symbols present on disk (optionally per adjust mode)."""

    @abstractmethod
    def delete_symbol(self, symbol: str, **options: Any) -> Any:
        """Delete one stock across raw CSVs, factor CSV, Qlib features and universe."""

    @abstractmethod
    def trim_symbol(self, symbol: str, **options: Any) -> Any:
        """Trim one stock's CSV to a date range / drop bad rows, then re-sync Qlib."""

    @abstractmethod
    def refresh_symbol(self, symbol: str, **options: Any) -> Any:
        """Re-download one stock from the data source, then re-sync the Qlib binary."""

    @abstractmethod
    def rebuild_h5(self, **options: Any) -> Any:
        """Rebuild the combined ``daily_pv`` h5 (no incremental mode)."""

    @property
    @abstractmethod
    def storage(self) -> Any:
        """Return the :class:`DataStorage` (path resolver) for this system."""

    # ---- Typed request wrappers (preferred in new code) ----

    def run_download(self, command: DataDownloadCommand) -> Any:
        """Preferred typed wrapper for :meth:`download`."""
        options = dict(command.options)
        if command.source is not None:
            options["source"] = command.source
        if command.output_dir is not None:
            options["output_dir"] = command.output_dir
        return self.download(
            start_date=command.start_date,
            end_date=command.end_date,
            symbols=command.symbols,
            **options,
        )

    def run_convert(self, command: DataConvertCommand) -> Any:
        """Preferred typed wrapper for :meth:`convert`."""
        options = dict(command.options)
        options.setdefault("adjust_mode", command.adjust_mode)
        if command.stock_csv is not None:
            options["stock_csv"] = command.stock_csv
        if command.qlib_dir is not None:
            options["qlib_dir"] = command.qlib_dir
        return self.convert(**options)

    def run_build_h5(self, command: DataBuildH5Command) -> Any:
        """Preferred typed wrapper for :meth:`build_h5`."""
        options = dict(command.options)
        if command.qlib_dir is not None:
            options["qlib_dir"] = command.qlib_dir
        if command.output_dir is not None:
            options["output_dir"] = command.output_dir
        if command.market is not None:
            options["market"] = command.market
        return self.build_h5(**options)

    def run_pipeline(self, command: DataPipelineCommand) -> Any:
        """Preferred typed wrapper for :meth:`pipeline`."""
        options = dict(command.options)
        options.setdefault("start_date", command.start_date)
        options.setdefault("end_date", command.end_date)
        options.setdefault("adjust_mode", command.adjust_mode)
        if command.stock_csv is not None:
            options["stock_csv"] = command.stock_csv
        return self.pipeline(**options)

    def dispatch_action(self, command: DataActionCommand) -> Any:
        """Preferred typed wrapper for :meth:`run_action`."""
        options = dict(command.options)
        options.update(
            {
                "start_date": command.start_date,
                "end_date": command.end_date,
                "adjust_mode": command.adjust_mode,
            }
        )
        if command.stock_csv is not None:
            options["stock_csv"] = command.stock_csv
        if command.market is not None:
            options["market"] = command.market
        if command.qlib_dir is not None:
            options["qlib_dir"] = command.qlib_dir
        if command.output_dir is not None:
            options["output_dir"] = command.output_dir
        return self.run_action(command.action, **options)
