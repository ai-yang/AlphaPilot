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

    # ---- Single-stock management ----

    def list_symbols(self, adjust_mode: Any = None) -> dict[str, list[str]]:
        from alphapilot.systems.data import manage

        return manage.list_symbols(adjust_mode)

    def delete_symbol(
        self,
        symbol: str,
        *,
        adjust_mode: Any = None,
        remove_factor: bool = True,
        remove_qlib_features: bool = True,
        remove_from_instruments: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage

        report = manage.delete_symbol(
            symbol,
            qlib_dir=self._storage.qlib_data_dir,
            factor_dir=self._storage.factor_dir,
            adjust_modes=adjust_mode,
            remove_factor=remove_factor,
            remove_qlib_features=remove_qlib_features,
            remove_from_instruments=remove_from_instruments,
            dry_run=dry_run,
        )
        self._warn_h5_stale(report)
        return report

    def trim_symbol(
        self,
        symbol: str,
        *,
        adjust_mode: Any = None,
        start: str | None = None,
        end: str | None = None,
        drop_dates: Any = None,
        resync_qlib: bool = True,
        qlib_adjust_mode: str = "backward",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage
        from alphapilot.systems.data.prepare_cn import existing_raw_dir

        report = manage.trim_symbol(
            symbol,
            adjust_modes=adjust_mode,
            start=start,
            end=end,
            drop_dates=drop_dates,
            dry_run=dry_run,
        )
        if resync_qlib:
            report["resync"] = manage.resync_symbol_to_qlib(
                symbol,
                raw_dir=existing_raw_dir(qlib_adjust_mode),
                qlib_dir=self._storage.qlib_data_dir,
                op="trim",
                dry_run=dry_run,
            )
        self._warn_h5_stale(report)
        return report

    def refresh_symbol(
        self,
        symbol: str,
        *,
        adjust_mode: Any = None,
        start_date: str = "2016-12-31",
        end_date: str | None = None,
        resync_qlib: bool = True,
        qlib_adjust_mode: str = "backward",
        **options: Any,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage
        from alphapilot.systems.data.prepare_cn import existing_raw_dir

        modes = manage.resolve_adjust_modes(adjust_mode if adjust_mode is not None else "backward")
        downloads: dict[str, Any] = {}
        for mode in modes:
            downloads[mode] = self.download(
                start_date=start_date,
                end_date=end_date,
                symbols=[symbol],
                adjust_mode=mode,
                **options,
            )
        report: dict[str, Any] = {"symbol": symbol, "downloaded_modes": list(modes), "h5_stale": True}
        if resync_qlib:
            report["resync"] = manage.resync_symbol_to_qlib(
                symbol,
                raw_dir=existing_raw_dir(qlib_adjust_mode),
                qlib_dir=self._storage.qlib_data_dir,
                op="refresh",
            )
        self._warn_h5_stale(report)
        return report

    def rebuild_h5(self, **options: Any) -> Any:
        return self.build_h5(**options)

    @staticmethod
    def _warn_h5_stale(report: dict[str, Any]) -> None:
        if report.get("h5_stale"):
            from alphapilot.log import logger

            logger.warning(
                "daily_pv h5 已过期：请运行 `alphapilot prepare_data h5`"
                "（或 Portal「重建 daily_pv h5」按钮 / 传 --rebuild_h5 True）以同步因子数据。"
            )

    @property
    def storage(self) -> DataStorage:
        return self._storage
