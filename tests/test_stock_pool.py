"""Tests for the stock pool (股票池) module and repository."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alphapilot.systems.data.stock_pool import StockPoolError, StockPoolRepository


def _write_raw_csv(raw_dir: Path, csv_stem: str, start: str, end: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{csv_stem}.csv").write_text(
        f"date,close\n{start},10.0\n{end},11.0\n", encoding="utf-8"
    )


def test_stock_pool_module_registered(engine) -> None:
    module = engine.get_module("stock_pool")
    assert module is not None
    assert module.name == "stock_pool"
    assert "pool_create" in module.commands()


def test_create_normalizes_dedupes_and_syncs_instruments(engine, isolated_env) -> None:
    module = engine.get_module("stock_pool")
    # mixed formats + a duplicate (sz.000001 == 000001.SZ)
    report = module.pool_create(
        name="my_pool",
        symbols="600519.SH, sz.000001, 000001.SZ, 300750",
        description="测试池",
    )
    assert report["name"] == "my_pool"
    assert report["valid_count"] == 3  # duplicate collapsed
    assert set(report["valid"]) == {"sh.600519", "sz.000001", "sz.300750"}
    assert not report["invalid"]

    # JSON source-of-truth written
    pool_json = isolated_env.important / "stock_pools" / "my_pool.json"
    assert pool_json.is_file()
    data = json.loads(pool_json.read_text(encoding="utf-8"))
    assert data["description"] == "测试池"
    assert len(data["symbols"]) == 3

    # Qlib instruments synced (qlib instrument id format: SH600519)
    inst = isolated_env.qlib_dir / "instruments" / "my_pool.txt"
    assert inst.is_file()
    body = inst.read_text(encoding="utf-8")
    assert "SH600519" in body and "SZ000001" in body


def test_create_reports_invalid_and_missing_data(engine, isolated_env) -> None:
    # one symbol has a local CSV, the others do not
    _write_raw_csv(isolated_env.raw_data, "sh600519", "2017-01-03", "2020-12-31")
    module = engine.get_module("stock_pool")
    report = module.pool_create(
        name="mixed", symbols="600519.SH, sz.000001, not-a-code"
    )
    assert report["invalid"] == ["not-a-code"]
    # sz.000001 lacks a CSV -> reported as missing, but still written (keep_missing)
    assert "sz.000001" in report["missing_data"]
    assert "sh.600519" not in report["missing_data"]
    inst = isolated_env.qlib_dir / "instruments" / "mixed.txt"
    lines = inst.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # both valid symbols kept


def test_create_duplicate_pool_rejected(engine) -> None:
    module = engine.get_module("stock_pool")
    module.pool_create(name="dup", symbols="600519.SH")
    with pytest.raises(StockPoolError):
        module.pool_create(name="dup", symbols="000001.SZ")


def test_add_and_remove_members(engine) -> None:
    module = engine.get_module("stock_pool")
    module.pool_create(name="edit", symbols="600519.SH")
    add = module.pool_add(name="edit", symbols="000001.SZ, 600519.SH")  # dup ignored
    assert add["added_count"] == 1
    assert add["total"] == 2

    rm = module.pool_remove(name="edit", symbols="sz.000001")
    assert rm["removed_count"] == 1
    assert rm["total"] == 1
    assert module.pool_show("edit")["symbols"] == ["sh.600519"]


def test_rename_moves_json_and_instruments(engine, isolated_env) -> None:
    module = engine.get_module("stock_pool")
    module.pool_create(name="old", symbols="600519.SH")
    module.pool_rename(name="old", new_name="renamed")

    pools_dir = isolated_env.important / "stock_pools"
    assert not (pools_dir / "old.json").exists()
    assert (pools_dir / "renamed.json").is_file()
    inst_dir = isolated_env.qlib_dir / "instruments"
    assert not (inst_dir / "old.txt").exists()
    assert (inst_dir / "renamed.txt").is_file()


def test_delete_dry_run_then_real(engine, isolated_env) -> None:
    module = engine.get_module("stock_pool")
    module.pool_create(name="trash", symbols="600519.SH")
    preview = module.pool_delete(name="trash", dry_run=True)
    assert preview["deleted"] is False
    assert (isolated_env.important / "stock_pools" / "trash.json").is_file()

    result = module.pool_delete(name="trash")
    assert result["deleted"] is True
    assert not (isolated_env.important / "stock_pools" / "trash.json").exists()
    assert not (isolated_env.qlib_dir / "instruments" / "trash.txt").exists()


def test_list_pools_summary(engine) -> None:
    module = engine.get_module("stock_pool")
    module.pool_create(name="pool_a", symbols="600519.SH, 000001.SZ", description="A")
    module.pool_create(name="pool_b", symbols="300750.SZ")
    summary = {p["name"]: p for p in module.pool_list()}
    assert summary["pool_a"]["count"] == 2
    assert summary["pool_a"]["description"] == "A"
    assert summary["pool_b"]["count"] == 1


@pytest.mark.parametrize("bad", ["all", "has space", "bad/name", ""])
def test_invalid_pool_names_rejected(engine, bad) -> None:
    module = engine.get_module("stock_pool")
    with pytest.raises(StockPoolError):
        module.pool_create(name=bad, symbols="600519.SH")


def test_create_with_no_valid_codes_errors(engine) -> None:
    module = engine.get_module("stock_pool")
    with pytest.raises(StockPoolError):
        module.pool_create(name="empty", symbols="not-a-code, also-bad")


def test_repository_export(engine, isolated_env) -> None:
    repo = StockPoolRepository(engine.config.data)
    repo.save_pool("exp", "600519.SH, 000001.SZ", replace=False)
    out = isolated_env.root / "exported.csv"
    path = repo.export_pool("exp", out)
    assert Path(path).is_file()
    assert "sh.600519" in Path(path).read_text(encoding="utf-8")
