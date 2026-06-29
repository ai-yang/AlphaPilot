"""Platform module commands (web/UI/data utilities)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class PlatformModule(BaseModule):
    """Operational module that contributes platform-level CLI commands."""

    name = "platform"

    def setup(self, context: "Context") -> None:
        self.context = context

    def prepare_data(
        self,
        action: str = "pipeline",
        start_date: str = "2015-01-01",
        end_date: str | None = None,
        stock_csv: str | None = None,
        adjust_mode: str = "backward",
        market: str | None = None,
        qlib_dir: str | None = None,
        output_dir: str | None = None,
        **options: Any,
    ) -> Any:
        """Run prepare-data actions through the data system entrypoint."""
        from alphapilot.systems.data.types import DataActionCommand

        data = self.context.data()
        command = DataActionCommand(
            action=action,
            start_date=start_date,
            end_date=end_date,
            stock_csv=stock_csv,
            adjust_mode=adjust_mode,
            market=market,
            qlib_dir=qlib_dir,
            output_dir=output_dir,
            options=dict(options),
        )
        return data.dispatch_action(command)

    # ---- Single-stock data management ----

    def list_stocks(
        self,
        adjust_mode: str | None = None,
        source: str = "baostock_cn",
    ) -> dict[str, Any]:
        """List local stock symbols (optionally for one adjust mode)."""
        return self.context.data().list_symbols(adjust_mode, source=source)

    def delete_stock(
        self,
        symbol: str,
        adjust_mode: str = "all",
        source: str = "baostock_cn",
        dry_run: bool = False,
    ) -> Any:
        """Delete one stock across raw CSVs, factor, Qlib features and instruments.

        ``adjust_mode`` defaults to ``all`` (delete every adjust-mode CSV).
        Factor h5 caches are regenerated automatically by later factor/backtest tasks.
        """
        return self.context.data().delete_symbol(
            symbol, adjust_mode=adjust_mode, source=source, dry_run=dry_run
        )

    def trim_stock(
        self,
        symbol: str,
        adjust_mode: str = "all",
        source: str = "baostock_cn",
        start_date: str | None = None,
        end_date: str | None = None,
        drop_dates: str | None = None,
        qlib_adjust_mode: str = "backward",
        resync_qlib: bool = True,
        dry_run: bool = False,
    ) -> Any:
        """Trim one stock's CSV to ``[start_date, end_date]`` / drop ``drop_dates``.

        Re-dumps that symbol's Qlib binary when ``resync_qlib`` is true.
        """
        data = self.context.data()
        return data.trim_symbol(
            symbol,
            adjust_mode=adjust_mode,
            source=source,
            start=start_date,
            end=end_date,
            drop_dates=drop_dates,
            resync_qlib=resync_qlib,
            qlib_adjust_mode=qlib_adjust_mode,
            dry_run=dry_run,
        )

    def refresh_stock(
        self,
        symbol: str,
        adjust_mode: str = "backward",
        source: str = "baostock_cn",
        start_date: str = "2016-12-31",
        end_date: str | None = None,
        qlib_adjust_mode: str = "backward",
        resync_qlib: bool = True,
    ) -> Any:
        """Re-download one stock (incremental) and re-sync its Qlib binary."""
        data = self.context.data()
        return data.refresh_symbol(
            symbol,
            adjust_mode=adjust_mode,
            source=source,
            start_date=start_date,
            end_date=end_date,
            resync_qlib=resync_qlib,
            qlib_adjust_mode=qlib_adjust_mode,
        )

    def clean_logs(self, log_dir: str | None = None, execute: bool = False) -> dict[str, object]:
        """Clean empty/stub AlphaPilot log directories.

        Defaults to preview mode. Pass ``execute=True`` to actually delete the
        directories reported by the same cleanup rules.
        """
        from alphapilot.log.cleanup import clean_log_dirs

        root = log_dir or str(self.context.config.log_dir)
        return clean_log_dirs(root, execute=execute).as_dict()

    @staticmethod
    def _print_portal_deprecation(command: str, tab_hint: str) -> None:
        print(
            f"\n[已弃用] `alphapilot {command}` 已整合进统一门户。\n"
            f"请使用：\n"
            f"  alphapilot portal --port 19901\n"
            f"浏览器打开 http://localhost:19901 ，进入「{tab_hint}」标签页。\n"
        )

    def ui(self, port: int = 19899, log_dir: str = "./log", debug: bool = False) -> None:
        """Deprecated: use ``alphapilot portal`` → Mining Log tab."""
        del port, log_dir, debug
        self._print_portal_deprecation("ui", "挖掘日志")

    def backtest_ui(
        self,
        port: int = 19900,
        workspace_root: str | None = None,
        log_dir: str = "./log",
    ) -> None:
        """Deprecated: use ``alphapilot portal`` → Backtest → Backtest Detail tab."""
        del port, workspace_root, log_dir
        self._print_portal_deprecation("backtest_ui", "回测 → 回测详情")

    def modules(self) -> dict[str, Any]:
        """List loaded modules with their command names."""
        info: dict[str, Any] = {}
        for module_name, module in self.context.engine.modules.items():
            info[module_name] = sorted(module.commands().keys())
        return info

    def commands(self) -> dict[str, Callable[..., Any] | Any]:
        return {
            "prepare_data": self.prepare_data,
            "list_stocks": self.list_stocks,
            "delete_stock": self.delete_stock,
            "trim_stock": self.trim_stock,
            "refresh_stock": self.refresh_stock,
            "clean_logs": self.clean_logs,
            "ui": self.ui,
            "backtest_ui": self.backtest_ui,
            "modules": self.modules,
        }
