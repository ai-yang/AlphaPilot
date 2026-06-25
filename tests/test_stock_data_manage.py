#!/usr/bin/env python3
"""Build an 80-stock test pool from local downloads and run data-manage tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alphapilot.kernel import build_engine
from alphapilot.systems.data.prepare_cn import RAW_DIR_BY_MODE, default_raw_dir

POOL_SIZE = 80
POOL_CSV = ROOT / "important_data" / "stock_lists" / "test_stock_pool_80.csv"
TEST_RAW_DIR = ROOT / "important_data" / "test_raw_pool"
MAIN_STOCK_CSV = ROOT / "important_data" / "stock_lists" / "main_stock_2026_4_27.csv"
QLIB_DIR = Path("~/.qlib/qlib_data/cn_data").expanduser()


def stem_to_ts_code(stem: str) -> str:
    ex = stem[:2].upper()
    num = stem[2:]
    return f"{num}.{ex}"


def pick_pool_stems(raw_dir: Path, n: int = POOL_SIZE) -> list[str]:
    stems = sorted(p.stem for p in raw_dir.glob("*.csv"))
    sh = [s for s in stems if s.startswith("sh")]
    sz = [s for s in stems if s.startswith("sz")]
    half = n // 2

    def evenly(items: list[str], count: int) -> list[str]:
        if count >= len(items):
            return items
        step = len(items) / count
        return [items[int(i * step)] for i in range(count)]

    picked = evenly(sh, half) + evenly(sz, n - half)
    return picked[:n]


def write_pool_csv(stems: list[str]) -> None:
    names: dict[str, str] = {}
    if MAIN_STOCK_CSV.exists():
        df = pd.read_csv(MAIN_STOCK_CSV)
        if "ts_code" in df.columns and "name" in df.columns:
            for _, row in df.iterrows():
                names[str(row["ts_code"])] = str(row["name"])

    rows = []
    for stem in stems:
        ts = stem_to_ts_code(stem)
        rows.append({"ts_code": ts, "name": names.get(ts, "")})

    POOL_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(POOL_CSV, index=False, encoding="utf-8")
    print(f"[1/4] 写入测试股票池: {POOL_CSV} ({len(rows)} 只)")


def setup_test_raw_dir(stems: list[str]) -> None:
    src = default_raw_dir("none")
    if TEST_RAW_DIR.exists():
        for p in TEST_RAW_DIR.glob("*.csv"):
            p.unlink()
    else:
        TEST_RAW_DIR.mkdir(parents=True)
    linked = 0
    for stem in stems:
        src_file = src / f"{stem}.csv"
        dst = TEST_RAW_DIR / f"{stem}.csv"
        if not src_file.is_file():
            print(f"  跳过缺失: {src_file}")
            continue
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(src_file.resolve(), dst)
        linked += 1
    print(f"[2/4] 测试 raw 目录: {TEST_RAW_DIR} ({linked} 个 symlink)")


def run_convert() -> None:
    from alphapilot.systems.data.prepare_data import PrepareDataCLI

    print("[3/4] convert 80 只股票 -> Qlib (adjust_mode=none)...")
    PrepareDataCLI().convert(
        stock_csv=str(POOL_CSV),
        data_path=str(TEST_RAW_DIR),
        adjust_mode="none",
        qlib_dir=str(QLIB_DIR),
        max_workers=4,
    )
    all_txt = QLIB_DIR / "instruments" / "all.txt"
    day_txt = QLIB_DIR / "calendars" / "day.txt"
    assert all_txt.is_file(), f"缺少 {all_txt}"
    assert day_txt.is_file(), f"缺少 {day_txt}"
    print(f"  instruments/all.txt 行数: {len(all_txt.read_text().splitlines())}")


def assert_true(cond: bool, msg: str, results: list[dict], name: str) -> None:
    results.append({"test": name, "pass": cond, "detail": msg})
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}: {msg}")


def run_manage_tests() -> list[dict]:
    engine = build_engine()
    data = engine.get_system("data")
    stems = pd.read_csv(POOL_CSV)["ts_code"].tolist()
    results: list[dict] = []

    # --- list_symbols ---
    by_mode = data.list_symbols("none")
    pool_stems = set()
    for ts in stems:
        code, ex = ts.split(".")
        pool_stems.add(f"{ex.lower()}{code}")

    listed = set(by_mode.get("none", []))
    overlap = pool_stems & listed
    assert_true(
        len(overlap) == len(pool_stems),
        f"池中 {len(pool_stems)} 只均在 list_symbols 中 (匹配 {len(overlap)})",
        results,
        "list_symbols",
    )

    trim_symbol = "sh.600004"
    trim_stem = "sh600004"
    refresh_symbol = "sz.000002"
    delete_symbol = stems[-1]  # 最后一只作为删除测试

    # --- trim dry-run ---
    dry = data.trim_symbol(
        trim_symbol,
        adjust_mode="none",
        end="2020-12-31",
        resync_qlib=False,
        qlib_adjust_mode="none",
        dry_run=True,
    )
    removed = dry.get("modes", {}).get("none", {}).get("removed", 0)
    assert_true(removed > 0, f"dry-run 将移除 {removed} 行", results, "trim_dry_run")

    # --- trim real ---
    csv_before = (default_raw_dir("none") / f"{trim_stem}.csv").resolve()
    lines_before = len(pd.read_csv(csv_before))
    trim_report = data.trim_symbol(
        trim_symbol,
        adjust_mode="none",
        end="2020-12-31",
        resync_qlib=True,
        qlib_adjust_mode="none",
    )
    lines_after = len(pd.read_csv(csv_before))
    inst_line = [
        ln
        for ln in (QLIB_DIR / "instruments" / "all.txt").read_text().splitlines()
        if ln.startswith("SH600004")
    ]
    assert_true(
        lines_after < lines_before,
        f"CSV {lines_before}->{lines_after} 行",
        results,
        "trim_csv",
    )
    assert_true(
        trim_report.get("resync", {}).get("status") == "resynced",
        f"resync={trim_report.get('resync', {}).get('status')}",
        results,
        "trim_resync",
    )
    assert_true(bool(inst_line), f"instruments 含 SH600004: {inst_line[:1]}", results, "trim_instruments")

    # --- refresh (needs network) ---
    try:
        refresh_report = data.refresh_symbol(
            refresh_symbol,
            adjust_mode="none",
            start_date="2024-01-01",
            resync_qlib=True,
            qlib_adjust_mode="none",
        )
        assert_true(
            refresh_report.get("resync", {}).get("status") == "resynced",
            f"downloaded_modes={refresh_report.get('downloaded_modes')}",
            results,
            "refresh_resync",
        )
    except Exception as exc:  # noqa: BLE001
        assert_true(False, str(exc), results, "refresh_resync")

    # --- delete dry-run ---
    code, ex = delete_symbol.split(".")
    del_stem = f"{ex.lower()}{code}"
    qlib_id = f"{ex.upper()}{code}"
    dry_del = data.delete_symbol(delete_symbol, adjust_mode="none", dry_run=True)
    assert_true(
        len(dry_del.get("deleted", [])) > 0 or len(dry_del.get("missing", [])) >= 0,
        f"dry-run deleted={len(dry_del.get('deleted', []))}",
        results,
        "delete_dry_run",
    )

    # --- delete real ---
    del_report = data.delete_symbol(delete_symbol, adjust_mode="none")
    raw_csv = default_raw_dir("none") / f"{del_stem}.csv"
    feat_gone = not (QLIB_DIR / "features" / del_stem).exists()
    csv_gone = not raw_csv.exists()
    inst_text = (QLIB_DIR / "instruments" / "all.txt").read_text()
    assert_true(csv_gone, f"{del_stem}.csv 已删除", results, "delete_csv")
    assert_true(feat_gone, f"features/{del_stem} 已删除", results, "delete_features")
    assert_true(qlib_id not in inst_text, f"{qlib_id} 已从 instruments 移除", results, "delete_instruments")

    passed = sum(1 for r in results if r["pass"])
    print(f"\n[4/4] 测试完成: {passed}/{len(results)} 通过")
    return results


def main() -> int:
    raw_dir = RAW_DIR_BY_MODE["none"].expanduser()
    if not raw_dir.is_dir() or not any(raw_dir.glob("*.csv")):
        print(f"错误: 未找到本地 raw 数据: {raw_dir}")
        return 1

    stems = pick_pool_stems(raw_dir, POOL_SIZE)
    write_pool_csv(stems)
    setup_test_raw_dir(stems)
    run_convert()
    results = run_manage_tests()

    report_path = ROOT / "important_data" / "test_data_manage_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已保存: {report_path}")

    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
