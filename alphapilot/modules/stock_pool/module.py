"""Stock pool (股票池) management CLI commands.

Pools are named baskets of stocks persisted as JSON under
``important_data/stock_pools/`` and mirrored to Qlib instruments so backtest /
mining can select them by name. All commands return JSON-serializable dicts so
they are reused as-is by the portal via ``/api/modules/run``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.data.stock_pool import StockPoolRepository

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class StockPoolModule(BaseModule):
    """Manage named stock pools (create / query / modify / delete)."""

    name = "stock_pool"

    def setup(self, context: "Context") -> None:
        self.context = context

    def _repo(self) -> StockPoolRepository:
        return StockPoolRepository(self.context.config.data)

    @staticmethod
    def _collect(symbols: Any, stock_csv: str | None) -> list[str]:
        """Merge raw codes from a CSV/TXT file and/or an inline symbols arg."""
        codes: list[str] = []
        if stock_csv:
            from alphapilot.systems.data.stock_list import load_stocks_from_file

            codes.extend(load_stocks_from_file(stock_csv))
        if symbols is not None:
            codes.extend(StockPoolRepository._coerce_symbols(symbols))
        return codes

    # ------------------------------------------------------------------ CRUD
    def pool_create(
        self,
        name: str,
        stock_csv: str | None = None,
        symbols: Any = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a stock pool from a CSV/TXT file and/or inline ``symbols``.

        ``symbols`` accepts a comma/space-separated string (e.g.
        ``"600519.SH,000001.SZ"``). Fails if the pool already exists.
        """
        codes = self._collect(symbols, stock_csv)
        return self._repo().save_pool(name, codes, description, replace=False)

    def pool_save(
        self,
        name: str,
        stock_csv: str | None = None,
        symbols: Any = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create or overwrite a stock pool with the given members."""
        codes = self._collect(symbols, stock_csv)
        return self._repo().save_pool(name, codes, description, replace=True)

    def pool_list(self) -> list[dict[str, Any]]:
        """List all stock pools with their member counts."""
        return self._repo().list_pools()

    def pool_show(self, name: str) -> dict[str, Any]:
        """Show a single pool's metadata and full member list."""
        return self._repo().get_pool(name)

    def pool_add(
        self,
        name: str,
        symbols: Any = None,
        stock_csv: str | None = None,
    ) -> dict[str, Any]:
        """Batch-add stocks to an existing pool (deduped against current members)."""
        codes = self._collect(symbols, stock_csv)
        return self._repo().add_symbols(name, codes)

    def pool_remove(self, name: str, symbols: Any) -> dict[str, Any]:
        """Remove one or more stocks from a pool."""
        return self._repo().remove_symbols(name, symbols)

    def pool_rename(self, name: str, new_name: str) -> dict[str, Any]:
        """Rename a pool (moves both the JSON and the Qlib instruments file)."""
        return self._repo().rename_pool(name, new_name)

    def pool_set_description(self, name: str, description: str) -> dict[str, Any]:
        """Update a pool's description without touching its members."""
        return self._repo().update_description(name, description)

    def pool_delete(self, name: str, dry_run: bool = False) -> dict[str, Any]:
        """Delete a pool (JSON + Qlib instruments). Use ``dry_run`` to preview."""
        return self._repo().delete_pool(name, dry_run=dry_run)

    def pool_export(self, name: str, output: str) -> dict[str, Any]:
        """Export a pool's members to a CSV file at ``output``."""
        path = self._repo().export_pool(name, output)
        return {"name": name, "output": str(path)}

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "pool_create": self.pool_create,
            "pool_save": self.pool_save,
            "pool_list": self.pool_list,
            "pool_show": self.pool_show,
            "pool_add": self.pool_add,
            "pool_remove": self.pool_remove,
            "pool_rename": self.pool_rename,
            "pool_set_description": self.pool_set_description,
            "pool_delete": self.pool_delete,
            "pool_export": self.pool_export,
        }
