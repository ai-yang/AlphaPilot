#!/usr/bin/env python3
"""Integration check: Tushare adjust download + apply_adjust vs Baostock.

Downloads a small symbol set via Tushare, runs local apply_adjust, and compares
OHLC against Baostock unadjusted + factor CSVs on overlapping trade dates.

Required checks (exit code 1 if any fail):
  - unadjusted Tushare vs Baostock close prices
  - Tushare pro_bar vs local apply_adjust (forward/backward)
  - forward adjust cross-vendor (Tushare vs Baostock)

Advisory checks (printed but do not fail the run):
  - backward adjust cross-vendor (factor vendor semantics often differ)

Usage:
    python test_tushare_adjust_compare.py
    python test_tushare_adjust_compare.py --symbols sh.600000 sz.000001 --start-date 2024-01-01
    python test_tushare_adjust_compare.py --skip-download   # reuse files under --work-dir

Requires TUSHARE_TOKEN in the environment or .env.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from dotenv import load_dotenv

    load_dotenv(".env")
except ImportError:
    pass

from alphapilot.systems.data.prepare_cn import existing_factor_dir, existing_raw_dir
from alphapilot.systems.data.prepare_data import PrepareDataCLI
from alphapilot.systems.data.prepare_tushare import download_cn_data
from alphapilot.systems.data.stock_list import baostock_to_csv_stem, infer_date_range_from_csv

PRICE_COLS = ("open", "high", "low", "close")
DEFAULT_SYMBOLS = ("sh.600000", "sh.600004", "sh.600006", "sz.000001", "sz.000002")


@dataclass
class CompareSpec:
    label: str
    left_root: Path
    right_root: Path
    atol: float
    rtol: float
    required: bool = True


@dataclass
class CompareResult:
    label: str
    symbol: str
    rows: int
    max_abs_close: float
    max_rel_close: float
    passed: bool
    required: bool = True
    note: str = ""


def _stem(symbol: str) -> str:
    return baostock_to_csv_stem(symbol)


def _load_prices(
    csv_path: Path,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path)
    if df.empty or "date" not in df.columns:
        return pd.DataFrame(columns=["date", *PRICE_COLS])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).sort_values("date")
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]
    for col in PRICE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = ["date", *[c for c in PRICE_COLS if c in df.columns]]
    return df[keep]


def _compare_pair(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    label: str,
    symbol: str,
    atol: float,
    rtol: float,
) -> CompareResult:
    merged = left.merge(right, on="date", how="inner", suffixes=("_l", "_r"))
    if merged.empty:
        return CompareResult(label, symbol, 0, float("nan"), float("nan"), False, "no overlapping dates")

    if "close_l" not in merged.columns or "close_r" not in merged.columns:
        return CompareResult(label, symbol, 0, float("nan"), float("nan"), False, "missing close column")

    diff = (merged["close_l"] - merged["close_r"]).abs()
    denom = merged[["close_l", "close_r"]].abs().max(axis=1).clip(lower=1e-6)
    rel = diff / denom
    max_abs = float(diff.max())
    max_rel = float(rel.max())
    passed = bool(np.allclose(merged["close_l"], merged["close_r"], rtol=rtol, atol=atol, equal_nan=True))
    return CompareResult(label, symbol, len(merged), max_abs, max_rel, passed)


def _pick_symbols(
    baostock_none_dir: Path,
    baostock_factor_dir: Path,
    requested: list[str] | None,
    limit: int,
) -> list[str]:
    if requested:
        symbols = requested
    else:
        stems = sorted(p.stem for p in baostock_none_dir.glob("*.csv"))
        factor_stems = {p.stem for p in baostock_factor_dir.glob("*.csv")}
        symbols = []
        for stem in stems:
            if stem not in factor_stems:
                continue
            exchange = stem[:2]
            code = stem[2:]
            symbols.append(f"{exchange}.{code}")
            if len(symbols) >= limit:
                break
    out: list[str] = []
    for symbol in symbols:
        stem = _stem(symbol)
        if (baostock_none_dir / f"{stem}.csv").is_file() and (baostock_factor_dir / f"{stem}.csv").is_file():
            out.append(symbol)
        else:
            print(f"[skip] Baostock 缺少 {symbol} 的除权或因子文件", file=sys.stderr)
    if not out:
        raise SystemExit("未找到可用于对比的股票（需要 Baostock 除权 CSV + 因子 CSV）。")
    return out[:limit]


def _overlap_window(symbols: list[str], baostock_none_dir: Path) -> tuple[str, str]:
    starts: list[str] = []
    ends: list[str] = []
    for symbol in symbols:
        stem = _stem(symbol)
        date_range = infer_date_range_from_csv(baostock_none_dir / f"{stem}.csv")
        if date_range is None:
            continue
        starts.append(date_range[0])
        ends.append(date_range[1])
    if not starts:
        raise SystemExit("无法从 Baostock CSV 推断日期范围。")
    return max(starts), min(ends)


def _copy_baostock_subset(
    symbols: list[str],
    *,
    src_none: Path,
    src_factor: Path,
    dst_none: Path,
    dst_factor: Path,
) -> None:
    dst_none.mkdir(parents=True, exist_ok=True)
    dst_factor.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        stem = _stem(symbol)
        shutil.copy2(src_none / f"{stem}.csv", dst_none / f"{stem}.csv")
        shutil.copy2(src_factor / f"{stem}.csv", dst_factor / f"{stem}.csv")


def _run_apply_adjust(
    *,
    mode: str,
    raw_dir: Path,
    factor_dir: Path,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    PrepareDataCLI().apply_adjust(
        adjust_mode=mode,
        raw_dir=str(raw_dir),
        factor_dir=str(factor_dir),
        output_dir=str(output_dir),
    )


def _download_tushare(
    symbols: list[str],
    *,
    start_date: str,
    end_date: str,
    adjust_mode: str,
    output_dir: Path,
    factor_dir: Path | None,
    state_path: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {
        "start_date": start_date,
        "end_date": end_date,
        "data_dir": output_dir,
        "symbols": symbols,
        "adjust_mode": adjust_mode,
        "download_state_path": state_path,
    }
    if factor_dir is not None:
        factor_dir.mkdir(parents=True, exist_ok=True)
        kwargs["factor_dir"] = factor_dir
    download_cn_data(**kwargs)


def _print_results(results: list[CompareResult]) -> int:
    width = max(len(r.label) for r in results) if results else 10
    failed_required = 0
    failed_optional = 0
    print("\nComparison summary")
    print("-" * 96)
    print(
        f"{'check':<{width}}  {'symbol':<12}  {'rows':>5}  {'max|dclose|':>11}  "
        f"{'max_rel':>8}  tier     pass"
    )
    print("-" * 96)
    for row in results:
        tier = "required" if row.required else "advisory"
        status = "OK" if row.passed else "FAIL"
        if not row.passed:
            if row.required:
                failed_required += 1
            else:
                failed_optional += 1
        note = f"  ({row.note})" if row.note else ""
        print(
            f"{row.label:<{width}}  {row.symbol:<12}  {row.rows:>5}  "
            f"{row.max_abs_close:>11.6f}  {row.max_rel_close:>8.4%}  {tier:<8}  {status}{note}"
        )
    print("-" * 96)
    required_total = sum(1 for row in results if row.required)
    required_passed = required_total - failed_required
    print(f"required passed {required_passed}/{required_total}")
    if any(not row.required for row in results):
        optional_total = len(results) - required_total
        optional_passed = optional_total - failed_optional
        print(f"advisory passed {optional_passed}/{optional_total} (backward cross-vendor may differ by design)")
    return 1 if failed_required else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=None, help="Baostock codes, e.g. sh.600000")
    parser.add_argument("--count", type=int, default=5, help="Auto-pick symbol count (default: 5)")
    parser.add_argument("--start-date", default=None, help="Download/compare start (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Download/compare end (YYYY-MM-DD)")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("git_ignore_folder") / "tushare_adjust_test",
        help="Scratch directory for Tushare downloads and local apply_adjust outputs",
    )
    parser.add_argument("--skip-download", action="store_true", help="Reuse CSVs already under --work-dir")
    parser.add_argument("--atol-none", type=float, default=0.02, help="Abs tolerance for unadjusted close")
    parser.add_argument("--rtol-none", type=float, default=0.002, help="Rel tolerance for unadjusted close")
    parser.add_argument("--atol-adj", type=float, default=0.05, help="Abs tolerance for adjusted close")
    parser.add_argument("--rtol-adj", type=float, default=0.01, help="Rel tolerance for adjusted close")
    parser.add_argument(
        "--atol-ts-internal",
        type=float,
        default=0.02,
        help="Abs tolerance for Tushare internal checks",
    )
    parser.add_argument(
        "--rtol-ts-internal",
        type=float,
        default=0.001,
        help="Rel tolerance for Tushare internal checks",
    )
    args = parser.parse_args(argv)

    baostock_none = existing_raw_dir("none")
    baostock_factor = existing_factor_dir()
    symbols = _pick_symbols(baostock_none, baostock_factor, args.symbols, args.count)
    auto_start, auto_end = _overlap_window(symbols, baostock_none)
    start_date = args.start_date or auto_start
    end_date = args.end_date or auto_end
    if start_date > end_date:
        raise SystemExit(f"无效日期窗口: {start_date} > {end_date}")

    work = args.work_dir.expanduser().resolve()
    paths = {
        "baostock_none": work / "baostock" / "raw_data_no_adjust",
        "baostock_factor": work / "baostock" / "adjust_factors",
        "baostock_fwd": work / "baostock" / "raw_data_forward_adjust",
        "baostock_bwd": work / "baostock" / "raw_data_back_adjust",
        "ts_none": work / "tushare" / "raw_data_no_adjust",
        "ts_factor": work / "tushare" / "adjust_factors",
        "ts_apply_fwd": work / "tushare" / "apply_forward",
        "ts_apply_bwd": work / "tushare" / "apply_backward",
        "ts_dl_fwd": work / "tushare" / "raw_data_forward_adjust",
        "ts_dl_bwd": work / "tushare" / "raw_data_back_adjust",
        "state": work / "download_state.csv",
    }

    print("Tushare adjust integration test")
    print(f"  symbols     : {', '.join(symbols)}")
    print(f"  date window : {start_date} ~ {end_date}")
    print(f"  work dir    : {work}")
    print(f"  baostock src: {baostock_none}")

    if not args.skip_download:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        _copy_baostock_subset(
            symbols,
            src_none=baostock_none,
            src_factor=baostock_factor,
            dst_none=paths["baostock_none"],
            dst_factor=paths["baostock_factor"],
        )
        print("\n[1/5] Tushare download: none + adj_factor ...")
        _download_tushare(
            symbols,
            start_date=start_date,
            end_date=end_date,
            adjust_mode="none",
            output_dir=paths["ts_none"],
            factor_dir=paths["ts_factor"],
            state_path=paths["state"],
        )
        print("[2/5] Tushare download: forward (pro_bar qfq) ...")
        _download_tushare(
            symbols,
            start_date=start_date,
            end_date=end_date,
            adjust_mode="forward",
            output_dir=paths["ts_dl_fwd"],
            factor_dir=None,
            state_path=paths["state"],
        )
        print("[3/5] Tushare download: backward (pro_bar hfq) ...")
        _download_tushare(
            symbols,
            start_date=start_date,
            end_date=end_date,
            adjust_mode="backward",
            output_dir=paths["ts_dl_bwd"],
            factor_dir=None,
            state_path=paths["state"],
        )
    else:
        for key in ("baostock_none", "ts_none", "ts_dl_fwd", "ts_dl_bwd"):
            if not paths[key].is_dir():
                raise SystemExit(f"--skip-download 但缺少目录: {paths[key]}")

    print("[4/5] Local apply_adjust ...")
    _run_apply_adjust(
        mode="forward",
        raw_dir=paths["baostock_none"],
        factor_dir=paths["baostock_factor"],
        output_dir=paths["baostock_fwd"],
    )
    _run_apply_adjust(
        mode="backward",
        raw_dir=paths["baostock_none"],
        factor_dir=paths["baostock_factor"],
        output_dir=paths["baostock_bwd"],
    )
    _run_apply_adjust(
        mode="forward",
        raw_dir=paths["ts_none"],
        factor_dir=paths["ts_factor"],
        output_dir=paths["ts_apply_fwd"],
    )
    _run_apply_adjust(
        mode="backward",
        raw_dir=paths["ts_none"],
        factor_dir=paths["ts_factor"],
        output_dir=paths["ts_apply_bwd"],
    )

    print("[5/5] Compare overlapping OHLC ...")
    results: list[CompareResult] = []
    compare_specs = [
        CompareSpec("none: tushare vs baostock", paths["ts_none"], paths["baostock_none"], args.atol_none, args.rtol_none),
        CompareSpec(
            "fwd: ts pro_bar vs ts apply",
            paths["ts_dl_fwd"],
            paths["ts_apply_fwd"],
            args.atol_ts_internal,
            args.rtol_ts_internal,
        ),
        CompareSpec(
            "bwd: ts pro_bar vs ts apply",
            paths["ts_dl_bwd"],
            paths["ts_apply_bwd"],
            args.atol_ts_internal,
            args.rtol_ts_internal,
        ),
        CompareSpec(
            "fwd: ts apply vs baostock apply",
            paths["ts_apply_fwd"],
            paths["baostock_fwd"],
            args.atol_adj,
            args.rtol_adj,
        ),
        CompareSpec(
            "fwd: ts pro_bar vs baostock apply",
            paths["ts_dl_fwd"],
            paths["baostock_fwd"],
            args.atol_adj,
            args.rtol_adj,
        ),
        CompareSpec(
            "bwd: ts apply vs baostock apply",
            paths["ts_apply_bwd"],
            paths["baostock_bwd"],
            args.atol_adj,
            args.rtol_adj,
            required=False,
        ),
        CompareSpec(
            "bwd: ts pro_bar vs baostock apply",
            paths["ts_dl_bwd"],
            paths["baostock_bwd"],
            args.atol_adj,
            args.rtol_adj,
            required=False,
        ),
    ]
    for spec in compare_specs:
        for symbol in symbols:
            stem = _stem(symbol)
            left_path = spec.left_root / f"{stem}.csv"
            right_path = spec.right_root / f"{stem}.csv"
            if not left_path.is_file() or not right_path.is_file():
                missing = []
                if not left_path.is_file():
                    missing.append(str(left_path))
                if not right_path.is_file():
                    missing.append(str(right_path))
                results.append(
                    CompareResult(
                        spec.label,
                        symbol,
                        0,
                        float("nan"),
                        float("nan"),
                        False,
                        required=spec.required,
                        note=f"missing: {', '.join(missing)}",
                    )
                )
                continue
            left = _load_prices(left_path, start=start_date, end=end_date)
            right = _load_prices(right_path, start=start_date, end=end_date)
            row = _compare_pair(left, right, label=spec.label, symbol=symbol, atol=spec.atol, rtol=spec.rtol)
            results.append(
                CompareResult(
                    row.label,
                    row.symbol,
                    row.rows,
                    row.max_abs_close,
                    row.max_rel_close,
                    row.passed,
                    required=spec.required,
                    note=row.note,
                )
            )

    return _print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
