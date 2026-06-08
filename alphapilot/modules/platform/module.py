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
            "ui": self.ui,
            "backtest_ui": self.backtest_ui,
            "modules": self.modules,
        }
