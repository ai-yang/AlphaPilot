#!/usr/bin/env python3
"""
对比「因子窗口探测」与「补行情后始终全量拉因子」的下载耗时。

不修改项目源码：通过 monkeypatch 在探测版 /  legacy 版之间切换因子处理逻辑。
在临时目录中复制样本股的行情与因子 CSV，避免污染 ~/.qlib 生产数据。

用法（在仓库根目录）::

    python tests/benchmark_factor_probe_download.py \\
        --stock_csv important_data/stock_lists/main_stock_2026_4_27.csv \\
        --end_date 2026-06-12 \\
        --sample_size 20

需要网络与 baostock 可用；建议 sample_size 取 10~30，过大耗时较长。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

# 保证可从仓库根目录直接运行
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from alphapilot.systems.data.prepare_cn import (  # noqa: E402
    _download_adjust_factors,
    _factor_file_path,
    _load_local_factor_df,
    _maybe_download_adjust_factors,
    default_raw_dir,
    download_stock_data,
    factor_covers_price_history,
    resolve_factor_dir,
)
from alphapilot.systems.data.stock_list import load_stocks_from_file, normalize_to_baostock


def _read_last_date_str(csv_path: Path) -> str | None:
    from alphapilot.systems.data.prepare_cn import _read_price_csv_last_date

    last = _read_price_csv_last_date(csv_path)
    return last.strftime("%Y-%m-%d") if last is not None else None


def _select_stocks_needing_update(
    codes: list[str],
    raw_dir: Path,
    end_date: str,
) -> list[str]:
    pending: list[str] = []
    for code in codes:
        stem = code.replace(".", "")
        csv_path = raw_dir / f"{stem}.csv"
        last = _read_last_date_str(csv_path)
        if last is None or last < end_date:
            pending.append(code)
    return pending


def _copy_symbol_files(
    codes: list[str],
    src_raw: Path,
    src_factor: Path,
    dst_raw: Path,
    dst_factor: Path,
) -> None:
    dst_raw.mkdir(parents=True, exist_ok=True)
    dst_factor.mkdir(parents=True, exist_ok=True)
    for code in codes:
        stem = code.replace(".", "")
        price_src = src_raw / f"{stem}.csv"
        if price_src.exists():
            shutil.copy2(price_src, dst_raw / f"{stem}.csv")
        factor_src = src_factor / f"{stem}.csv"
        if factor_src.exists():
            shutil.copy2(factor_src, dst_factor / f"{stem}.csv")


def _legacy_always_full_adjust_factors(
    code: str,
    end_date: str,
    factor_dir: Path,
    *,
    incremental_start: str,
    price_df=None,
    stats=None,
) -> None:
    """
    旧逻辑（无窗口探测）：行情写入后，在因子文件存在且覆盖起点时仍全量拉因子。

    与当前 ``_maybe_download_adjust_factors`` 的差异仅在「有本地因子且覆盖行情」时：
    旧逻辑不探测窗口，直接 ``_download_adjust_factors``。
    """
    local_factor = _load_local_factor_df(_factor_file_path(code, factor_dir))

    if local_factor is None or local_factor.empty:
        _download_adjust_factors(code, end_date, factor_dir)
        if stats is not None:
            stats.incr("factor_refreshed")
        return

    if price_df is not None and not factor_covers_price_history(local_factor, price_df):
        _download_adjust_factors(code, end_date, factor_dir)
        if stats is not None:
            stats.incr("factor_refreshed")
        return

    _download_adjust_factors(code, end_date, factor_dir)
    if stats is not None:
        stats.incr("factor_refreshed")


@contextmanager
def _patch_factor_handler(handler: Callable) -> Iterator[None]:
    import alphapilot.systems.data.prepare_cn as prepare_cn

    original = prepare_cn._maybe_download_adjust_factors
    prepare_cn._maybe_download_adjust_factors = handler
    try:
        yield
    finally:
        prepare_cn._maybe_download_adjust_factors = original


def _run_mode(
    *,
    label: str,
    codes: list[str],
    start_date: str,
    end_date: str,
    raw_dir: Path,
    factor_dir: Path,
    max_workers: int,
    factor_handler: Callable,
) -> dict[str, float | int | str]:
    _copy_symbol_files(
        codes,
        default_raw_dir("none"),
        resolve_factor_dir(None),
        raw_dir,
        factor_dir,
    )

    with _patch_factor_handler(factor_handler):
        t0 = time.perf_counter()
        download_stock_data(
            start_date=start_date,
            end_date=end_date,
            output_dir=raw_dir,
            symbols=codes,
            adjust_mode="none",
            factor_dir=factor_dir,
            max_workers=max_workers,
        )
        elapsed = time.perf_counter() - t0

    return {
        "label": label,
        "count": len(codes),
        "elapsed_sec": elapsed,
        "per_stock_sec": elapsed / len(codes) if codes else 0.0,
    }


def _format_result(row: dict) -> str:
    return (
        f"{row['label']}: "
        f"{row['count']} 只, "
        f"总耗时 {row['elapsed_sec']:.1f}s, "
        f"平均 {row['per_stock_sec']:.2f}s/只"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="对比因子窗口探测 vs 补行情后始终全量拉因子"
    )
    parser.add_argument(
        "--stock_csv",
        type=Path,
        default=_REPO_ROOT / "important_data/stock_lists/main_stock_2026_4_27.csv",
    )
    parser.add_argument("--code_column", default=None)
    parser.add_argument("--end_date", default="2026-06-12")
    parser.add_argument("--start_date", default="2015-01-01")
    parser.add_argument(
        "--sample_size",
        type=int,
        default=20,
        help="参与对比的样本股数量（将均分为探测组 / 全量组）",
    )
    parser.add_argument("--max_workers", type=int, default=1)
    parser.add_argument(
        "--work_dir",
        type=Path,
        default=_REPO_ROOT / "tests/_benchmark_factor_probe_work",
        help="临时工作目录（存放复制的 CSV，可重复删除）",
    )
    args = parser.parse_args()

    if args.sample_size < 2 or args.sample_size % 2 != 0:
        parser.error("sample_size 须为 >= 2 的偶数，以便均分两组")

    src_raw = default_raw_dir("none")
    all_codes = load_stocks_from_file(args.stock_csv, code_column=args.code_column)
    pending = _select_stocks_needing_update(all_codes, src_raw, args.end_date)

    if len(pending) < args.sample_size:
        print(
            f"需要更新的股票仅 {len(pending)} 只（end_date={args.end_date}），"
            f"少于 sample_size={args.sample_size}。"
        )
        if len(pending) < 2:
            print("请先确保本地行情未全部更新到 end_date，或减小 sample_size。")
            return 1
        args.sample_size = len(pending) if len(pending) % 2 == 0 else len(pending) - 1
        print(f"已自动将 sample_size 调整为 {args.sample_size}")

    sample = pending[: args.sample_size]
    half = args.sample_size // 2
    probe_codes = sample[:half]
    legacy_codes = sample[half:]

    work = args.work_dir.expanduser().resolve()
    probe_raw = work / "probe" / "raw"
    probe_factor = work / "probe" / "factors"
    legacy_raw = work / "legacy" / "raw"
    legacy_factor = work / "legacy" / "factors"

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    print("=" * 60)
    print("因子探测 vs 始终全量拉因子 — 下载耗时对比")
    print("=" * 60)
    print(f"数据源行情目录: {src_raw}")
    print(f"end_date: {args.end_date}")
    print(f"待更新池: {len(pending)} 只; 本基准样本: {args.sample_size} 只")
    print(f"  探测组: {half} 只（示例 {probe_codes[:3]} ...）")
    print(f"  全量组: {half} 只（示例 {legacy_codes[:3]} ...）")
    print(f"max_workers: {args.max_workers}")
    print(f"临时目录: {work}")
    print()

    print("[1/2] 运行探测模式（_maybe_download_adjust_factors）...")
    probe_result = _run_mode(
        label="窗口探测",
        codes=probe_codes,
        start_date=args.start_date,
        end_date=args.end_date,
        raw_dir=probe_raw,
        factor_dir=probe_factor,
        max_workers=args.max_workers,
        factor_handler=_maybe_download_adjust_factors,
    )
    print(_format_result(probe_result))
    print()

    print("[2/2] 运行 legacy 模式（补行情后始终全量拉因子）...")
    legacy_result = _run_mode(
        label="始终全量",
        codes=legacy_codes,
        start_date=args.start_date,
        end_date=args.end_date,
        raw_dir=legacy_raw,
        factor_dir=legacy_factor,
        max_workers=args.max_workers,
        factor_handler=_legacy_always_full_adjust_factors,
    )
    print(_format_result(legacy_result))
    print()

    probe_per = float(probe_result["per_stock_sec"])
    legacy_per = float(legacy_result["per_stock_sec"])
    if legacy_per > 0:
        speedup = legacy_per / probe_per if probe_per > 0 else float("inf")
        saved = (legacy_per - probe_per) * half
        print("=" * 60)
        print("对比（按每只平均耗时外推同规模）:")
        print(f"  探测模式:     {probe_per:.2f}s/只")
        print(f"  始终全量模式: {legacy_per:.2f}s/只")
        if probe_per < legacy_per:
            print(f"  探测模式约快 {speedup:.2f}x（每只省 {legacy_per - probe_per:.2f}s）")
            print(f"  若 {half} 只均需补行情，约省 {saved:.0f}s")
        elif probe_per > legacy_per:
            print(
                "  本次探测模式更慢（可能窗口内除权较多，探测后仍全量拉，"
                "或多了一次探测 API）。"
            )
        else:
            print("  两者耗时接近。")
        print()
        print("说明:")
        print("  - 两组使用不同股票、相同数量，在临时目录复制数据后各自下载。")
        print("  - 行情 API 耗时两组相近；差异主要来自因子探测 vs 全量因子。")
        print("  - 若样本中近期有除权，两种模式都会全量拉因子，差距会缩小。")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
