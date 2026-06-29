"""Named stock pools (股票池): JSON source-of-truth + Qlib instruments sync.

A *stock pool* is persisted as ``important_data/stock_pools/{name}.json`` (the
editable source of truth, with metadata) and mirrored to the Qlib instruments
file ``{qlib_data_dir}/instruments/{name}.txt`` so backtest / mining can consume
it via ``D.instruments(market=name)``. The JSON is authoritative; every mutating
operation rewrites the JSON and re-syncs the derived instruments file.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from alphapilot.kernel.paths import stock_pools_dir
from alphapilot.systems.data.stock_list import (
    baostock_to_csv_stem,
    normalize_to_baostock,
    write_qlib_instruments,
)

if TYPE_CHECKING:
    from alphapilot.kernel.config import DataConfig

# Pool names double as Qlib instruments filenames; keep them filesystem-safe.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Reserved Qlib instrument-set names a pool must never overwrite.
_RESERVED_NAMES = frozenset({"all"})


class StockPoolError(ValueError):
    """Invalid stock-pool operation (bad name, missing pool, no valid codes...)."""


class StockPoolRepository:
    """CRUD for named stock pools, persisted as JSON + synced to Qlib instruments."""

    def __init__(self, config: "DataConfig") -> None:
        self.config = config

    # ------------------------------------------------------------------ paths
    @property
    def pools_dir(self) -> Path:
        d = stock_pools_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pool_path(self, name: str) -> Path:
        return self.pools_dir / f"{name}.json"

    @property
    def _qlib_dir(self) -> Path:
        return Path(self.config.qlib_data_dir).expanduser()

    @property
    def _raw_dir(self) -> Path:
        return Path(self.config.raw_data_dir).expanduser()

    def _instruments_path(self, name: str) -> Path:
        return self._qlib_dir / "instruments" / f"{name}.txt"

    # ------------------------------------------------------------- validation
    @staticmethod
    def _check_name(name: str) -> str:
        cleaned = (name or "").strip()
        if not cleaned:
            raise StockPoolError("股票池名称不能为空")
        if not _NAME_RE.match(cleaned):
            raise StockPoolError(
                f"股票池名称仅支持字母、数字、下划线和连字符: {name!r}"
            )
        if cleaned in _RESERVED_NAMES:
            raise StockPoolError(f"{cleaned!r} 是保留名称，不能用作股票池名")
        return cleaned

    @staticmethod
    def _coerce_symbols(symbols: Any) -> list[str]:
        """Accept a list/tuple or a comma/space/semicolon-separated string."""
        if symbols is None:
            return []
        if isinstance(symbols, str):
            parts: list[Any] = re.split(r"[\s,;]+", symbols.strip())
        elif isinstance(symbols, (list, tuple, set)):
            parts = list(symbols)
        else:  # scalar (e.g. fire-parsed int)
            parts = [symbols]
        return [str(p).strip() for p in parts if str(p).strip()]

    def _normalize(self, raw: Iterable[str]) -> tuple[list[str], list[str]]:
        """Return ``(valid_baostock_codes_deduped, invalid_raw_inputs)``."""
        valid: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for code in raw:
            norm = normalize_to_baostock(code)
            if norm is None:
                invalid.append(str(code))
                continue
            if norm not in seen:
                seen.add(norm)
                valid.append(norm)
        return valid, invalid

    def _missing_data(self, symbols: Iterable[str]) -> list[str]:
        """Symbols lacking a local raw CSV (no downloaded market data yet)."""
        raw_dir = self._raw_dir
        missing: list[str] = []
        for code in symbols:
            csv = raw_dir / f"{baostock_to_csv_stem(code)}.csv"
            if not csv.is_file():
                missing.append(code)
        return missing

    # ------------------------------------------------------------------ reads
    def exists(self, name: str) -> bool:
        return self._pool_path((name or "").strip()).is_file()

    def list_pools(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self.pools_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append(
                {
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "count": len(data.get("symbols", [])),
                    "updated_at": data.get("updated_at", ""),
                }
            )
        return out

    def get_pool(self, name: str) -> dict[str, Any]:
        path = self._pool_path((name or "").strip())
        if not path.is_file():
            raise StockPoolError(f"股票池不存在: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    # -------------------------------------------------------------- internals
    def _write_json(
        self,
        name: str,
        symbols: list[str],
        description: str,
        created_at: str,
    ) -> dict[str, Any]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "name": name,
            "description": description or "",
            "created_at": created_at or now,
            "updated_at": now,
            "symbols": symbols,
        }
        self._pool_path(name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    def _sync_instruments(self, name: str, symbols: list[str]) -> Path | None:
        """Rewrite ``instruments/{name}.txt`` from *symbols* (or drop it if empty)."""
        inst_path = self._instruments_path(name)
        if not symbols:
            inst_path.unlink(missing_ok=True)
            return None
        return write_qlib_instruments(
            symbols,
            self._qlib_dir,
            market=name,
            data_dir=self._raw_dir,
            keep_missing=True,
        )

    def _delete_files(self, name: str) -> None:
        self._pool_path(name).unlink(missing_ok=True)
        self._instruments_path(name).unlink(missing_ok=True)

    @staticmethod
    def _report(
        name: str,
        valid: list[str],
        invalid: list[str],
        missing: list[str],
        inst_path: Path | None,
        total: int,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "total": total,
            "valid": valid,
            "valid_count": len(valid),
            "invalid": invalid,
            "missing_data": missing,
            "instruments_path": str(inst_path) if inst_path else None,
        }

    # ------------------------------------------------------------------ writes
    def save_pool(
        self,
        name: str,
        symbols: Any,
        description: str = "",
        *,
        replace: bool = True,
    ) -> dict[str, Any]:
        """Create or replace a pool. Returns a validation report."""
        name = self._check_name(name)
        created_at = ""
        if self.exists(name):
            if not replace:
                raise StockPoolError(f"股票池已存在: {name}")
            created_at = self.get_pool(name).get("created_at", "")
        valid, invalid = self._normalize(self._coerce_symbols(symbols))
        if not valid:
            raise StockPoolError("没有有效的股票代码可保存")
        self._write_json(name, valid, description, created_at)
        inst_path = self._sync_instruments(name, valid)
        missing = self._missing_data(valid)
        return self._report(name, valid, invalid, missing, inst_path, total=len(valid))

    def add_symbols(self, name: str, symbols: Any) -> dict[str, Any]:
        pool = self.get_pool(name)
        existing: list[str] = list(pool.get("symbols", []))
        valid, invalid = self._normalize(self._coerce_symbols(symbols))
        present = set(existing)
        added = [c for c in valid if c not in present]
        merged = existing + added
        self._write_json(
            pool["name"], merged, pool.get("description", ""), pool.get("created_at", "")
        )
        inst_path = self._sync_instruments(pool["name"], merged)
        missing = self._missing_data(added)
        report = self._report(
            pool["name"], valid, invalid, missing, inst_path, total=len(merged)
        )
        report["added"] = added
        report["added_count"] = len(added)
        return report

    def remove_symbols(self, name: str, symbols: Any) -> dict[str, Any]:
        pool = self.get_pool(name)
        existing: list[str] = list(pool.get("symbols", []))
        targets, invalid = self._normalize(self._coerce_symbols(symbols))
        remove_set = set(targets)
        removed = [c for c in existing if c in remove_set]
        remaining = [c for c in existing if c not in remove_set]
        self._write_json(
            pool["name"], remaining, pool.get("description", ""), pool.get("created_at", "")
        )
        inst_path = self._sync_instruments(pool["name"], remaining)
        return {
            "name": pool["name"],
            "removed": removed,
            "removed_count": len(removed),
            "invalid": invalid,
            "total": len(remaining),
            "instruments_path": str(inst_path) if inst_path else None,
        }

    def rename_pool(self, name: str, new_name: str) -> dict[str, Any]:
        pool = self.get_pool(name)
        new_name = self._check_name(new_name)
        old_name = pool["name"]
        if new_name == old_name:
            raise StockPoolError("新名称与原名称相同")
        if self.exists(new_name):
            raise StockPoolError(f"目标名称已存在: {new_name}")
        symbols = list(pool.get("symbols", []))
        self._write_json(
            new_name, symbols, pool.get("description", ""), pool.get("created_at", "")
        )
        inst_path = self._sync_instruments(new_name, symbols)
        self._delete_files(old_name)
        return {
            "name": new_name,
            "old_name": old_name,
            "total": len(symbols),
            "instruments_path": str(inst_path) if inst_path else None,
        }

    def update_description(self, name: str, description: str) -> dict[str, Any]:
        pool = self.get_pool(name)
        symbols = list(pool.get("symbols", []))
        self._write_json(pool["name"], symbols, description, pool.get("created_at", ""))
        return {"name": pool["name"], "description": description, "total": len(symbols)}

    def delete_pool(self, name: str, *, dry_run: bool = False) -> dict[str, Any]:
        name = (name or "").strip()
        if not self.exists(name):
            raise StockPoolError(f"股票池不存在: {name}")
        targets = [str(self._pool_path(name))]
        inst_path = self._instruments_path(name)
        if inst_path.is_file():
            targets.append(str(inst_path))
        if dry_run:
            return {"name": name, "deleted": False, "would_delete": targets}
        self._delete_files(name)
        return {"name": name, "deleted": True, "removed_paths": targets}

    def export_pool(self, name: str, output: str | Path) -> Path:
        pool = self.get_pool(name)
        out = Path(output).expanduser()
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        import pandas as pd

        pd.DataFrame({"code": pool.get("symbols", [])}).to_csv(out, index=False)
        return out
