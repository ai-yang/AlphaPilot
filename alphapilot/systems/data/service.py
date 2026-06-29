"""Default Qlib/baostock-backed data management system.

Owns the unified data lifecycle entrypoints. Download goes through the
registered data-source adapter (default ``baostock_cn``); conversion and
pipeline orchestration is implemented under ``systems.data``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import pipeline as data_pipeline
from alphapilot.systems.data.base import BaseDataSystem
from alphapilot.systems.data.storage import DataStorage
from alphapilot.systems.data.types import (
    DataActionCommand,
    DataConvertCommand,
    DataDownloadCommand,
    DataPipelineCommand,
)

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class QlibDataSystem(BaseDataSystem):
    """A-share data system: baostock download + Qlib conversion."""

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

    def apply_adjust(self, **options: Any) -> Any:
        """Synthesize forward/backward CSVs from unadjusted bars + adjust factors.

        ``source`` (``baostock_cn`` / ``tushare_cn``) selects which source's directories to
        read from and write to. For the default baostock source the CLI's own dir defaults
        apply; for other sources we resolve the source-specific raw / factor / output dirs (only
        when not explicitly overridden). ``source`` is consumed here and never forwarded to the
        CLI, which does not accept it.
        """
        source = options.pop("source", None)
        if source not in (None, "", "baostock", "baostock_cn"):
            target_mode = options.get("target_mode") or options.get("adjust_mode") or "forward"
            options.setdefault("raw_dir", str(self._source_raw_dir("none", source)))
            options.setdefault("factor_dir", str(self._source_factor_dir(source)))
            options.setdefault("output_dir", str(self._source_raw_dir(target_mode, source)))
        return self.run_action("apply_adjust", **options)

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
            pipeline_handler=self.pipeline,
            **options,
        )

    # ---- Single-stock management ----

    def _source_qlib_dir(self, source: str | None = None) -> Any:
        from alphapilot.systems.data import manage

        if source in (None, "", "baostock", "baostock_cn"):
            return self._storage.qlib_data_dir
        return manage.existing_qlib_dir_for_source(source)

    def _source_factor_dir(self, source: str | None = None) -> Any:
        from alphapilot.systems.data import manage

        if source in (None, "", "baostock", "baostock_cn"):
            return self._storage.factor_dir
        return manage.existing_factor_dir_for_source(source)

    def _source_raw_dir(self, adjust_mode: str, source: str | None = None) -> Any:
        from alphapilot.systems.data import manage

        if source in (None, "", "baostock", "baostock_cn"):
            return self._storage.raw_dir_for_mode(adjust_mode)
        return manage.existing_raw_dir_for_source(adjust_mode, source)

    def list_symbols(self, adjust_mode: Any = None, *, source: str | None = None) -> dict[str, list[str]]:
        from alphapilot.systems.data import manage

        return manage.list_symbols(adjust_mode, source=source)

    def delete_symbol(
        self,
        symbol: str,
        *,
        adjust_mode: Any = None,
        source: str | None = None,
        remove_factor: bool = True,
        remove_qlib_features: bool = True,
        remove_from_instruments: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage

        report = manage.delete_symbol(
            symbol,
            qlib_dir=self._source_qlib_dir(source),
            factor_dir=self._source_factor_dir(source),
            adjust_modes=adjust_mode,
            source=source,
            remove_factor=remove_factor,
            remove_qlib_features=remove_qlib_features,
            remove_from_instruments=remove_from_instruments,
            dry_run=dry_run,
        )
        self._warn_h5_stale(report)
        return report

    def apply_adjust_symbol(
        self,
        symbol: str,
        *,
        target_mode: str = "forward",
        source: str | None = None,
        raw_dir: str | None = None,
        factor_dir: str | None = None,
        output_dir: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage

        return manage.apply_adjust_symbol(
            symbol,
            target_mode=target_mode,
            source=source,
            raw_dir=raw_dir,
            factor_dir=factor_dir,
            output_dir=output_dir,
            dry_run=dry_run,
        )

    def trim_symbol(
        self,
        symbol: str,
        *,
        adjust_mode: Any = None,
        source: str | None = None,
        start: str | None = None,
        end: str | None = None,
        drop_dates: Any = None,
        resync_qlib: bool = True,
        qlib_adjust_mode: str = "backward",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage

        report = manage.trim_symbol(
            symbol,
            adjust_modes=adjust_mode,
            source=source,
            start=start,
            end=end,
            drop_dates=drop_dates,
            dry_run=dry_run,
        )
        if resync_qlib:
            report["resync"] = manage.resync_symbol_to_qlib(
                symbol,
                raw_dir=self._source_raw_dir(qlib_adjust_mode, source),
                qlib_dir=self._source_qlib_dir(source),
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
        source: str | None = None,
        start_date: str = "2016-12-31",
        end_date: str | None = None,
        resync_qlib: bool = True,
        qlib_adjust_mode: str = "backward",
        **options: Any,
    ) -> dict[str, Any]:
        from alphapilot.systems.data import manage

        modes = manage.resolve_adjust_modes(adjust_mode if adjust_mode is not None else "backward")
        downloads: dict[str, Any] = {}
        for mode in modes:
            downloads[mode] = self.download(
                start_date=start_date,
                end_date=end_date,
                symbols=[symbol],
                adjust_mode=mode,
                source=source,
                **options,
            )
        report: dict[str, Any] = {
            "symbol": symbol,
            "source": source or "baostock_cn",
            "downloaded_modes": list(modes),
            "downloads": downloads,
            "h5_stale": True,
        }
        if resync_qlib:
            report["resync"] = manage.resync_symbol_to_qlib(
                symbol,
                raw_dir=self._source_raw_dir(qlib_adjust_mode, source),
                qlib_dir=self._source_qlib_dir(source),
                op="refresh",
            )
        self._warn_h5_stale(report)
        return report

    @staticmethod
    def _warn_h5_stale(report: dict[str, Any]) -> None:
        if report.get("h5_stale"):
            from alphapilot.log import logger

            logger.warning(
                "因子 h5 cache 可能已过期：后续回测/挖掘会按当前股票池自动生成或复用 h5 cache。"
            )

    @property
    def storage(self) -> DataStorage:
        return self._storage
