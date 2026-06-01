"""Default Qlib/baostock-backed data management system.

Owns the unified data lifecycle entrypoints. Download goes through the
registered data-source adapter (default ``baostock_cn``); conversion /
h5 / pipeline orchestration is implemented under ``systems.data``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import pipeline as data_pipeline
from alphapilot.systems.data.base import BaseDataSystem
from alphapilot.systems.data.storage import DataStorage
from alphapilot.systems.data.types import (
    DataActionCommand,
    DataBuildH5Command,
    DataConvertCommand,
    DataDownloadCommand,
    DataPipelineCommand,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class QlibDataSystem(BaseDataSystem):
    """A-share data system: baostock download + Qlib conversion + h5."""

    def setup(self, context: "Context") -> None:
        self.context = context
        self._storage = DataStorage(context.config.data)

    def download(
        self,
        start_date: str | DataDownloadCommand,
        end_date: str | None = None,
        *,
        symbols: list[str] | None = None,
        **options: Any,
    ) -> Any:
        if isinstance(start_date, DataDownloadCommand):
            command = start_date
            options = dict(command.options)
            if command.source is not None:
                options["source"] = command.source
            if command.output_dir is not None:
                options["output_dir"] = command.output_dir
            start_date = command.start_date
            end_date = command.end_date
            symbols = command.symbols

        from alphapilot.adapters import get_data_source
        from alphapilot.adapters.base import DataDownloadRequest

        source = get_data_source(options.pop("source", None))
        request = DataDownloadRequest(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            output_dir=options.pop("output_dir", None),
            options=options,
        )
        return source.download(request)

    def convert(self, **options: Any) -> Any:
        if "command" in options and isinstance(options["command"], DataConvertCommand):
            command = options.pop("command")
            command_options = dict(command.options)
            command_options.setdefault("adjust_mode", command.adjust_mode)
            if command.stock_csv is not None:
                command_options["stock_csv"] = command.stock_csv
            if command.qlib_dir is not None:
                command_options["qlib_dir"] = command.qlib_dir
            command_options.update(options)
            options = command_options

        return data_pipeline.convert_data(**options)

    def build_h5(self, **options: Any) -> Any:
        if "command" in options and isinstance(options["command"], DataBuildH5Command):
            command = options.pop("command")
            command_options = dict(command.options)
            if command.qlib_dir is not None:
                command_options["qlib_dir"] = command.qlib_dir
            if command.output_dir is not None:
                command_options["output_dir"] = command.output_dir
            if command.market is not None:
                command_options["market"] = command.market
            command_options.update(options)
            options = command_options

        options.setdefault("qlib_dir", str(self._storage.qlib_data_dir))
        return data_pipeline.build_h5_data(**options)

    def pipeline(self, **options: Any) -> Any:
        """Run the full download -> adjust -> convert pipeline."""
        if "command" in options and isinstance(options["command"], DataPipelineCommand):
            command = options.pop("command")
            command_options = dict(command.options)
            command_options.setdefault("start_date", command.start_date)
            command_options.setdefault("end_date", command.end_date)
            command_options.setdefault("adjust_mode", command.adjust_mode)
            if command.stock_csv is not None:
                command_options["stock_csv"] = command.stock_csv
            command_options.update(options)
            options = command_options

        return data_pipeline.run_pipeline(**options)

    def get_universe(self, **options: Any) -> Any:
        return data_pipeline.load_universe(
            stock_csv=options.get("stock_csv"),
            code_column=options.get("code_column"),
        )

    def run_action(self, action: str | DataActionCommand, **options: Any) -> Any:
        """Unified dispatcher for ``alphapilot prepare_data`` actions."""
        if isinstance(action, DataActionCommand):
            command = action
            action = command.action
            merged_options = dict(command.options)
            merged_options.update(options)
            merged_options.setdefault("start_date", command.start_date)
            merged_options.setdefault("end_date", command.end_date)
            merged_options.setdefault("adjust_mode", command.adjust_mode)
            if command.stock_csv is not None:
                merged_options["stock_csv"] = command.stock_csv
            if command.market is not None:
                merged_options["market"] = command.market
            if command.qlib_dir is not None:
                merged_options["qlib_dir"] = command.qlib_dir
            if command.output_dir is not None:
                merged_options["output_dir"] = command.output_dir
            options = merged_options

        return data_pipeline.dispatch_prepare_action(
            action=action,
            download_handler=self.download,
            convert_handler=self.convert,
            build_h5_handler=self.build_h5,
            pipeline_handler=self.pipeline,
            **options,
        )

    @property
    def storage(self) -> DataStorage:
        return self._storage
