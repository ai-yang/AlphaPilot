"""Single-stock data management: delete / trim / re-sync across storage layers.

A single A-share symbol spans several on-disk layers:

* raw CSV per adjust mode (``raw_data_{no,forward,back}_adjust/{stem}.csv``)
* adjust-factor CSV (``adjust_factors/{stem}.csv``)
* Qlib binary features (``features/{stem}/*.day.bin``)
* universe files (``instruments/all.txt`` *and* the named ``instruments/{market}.txt``)
* derived ``daily_pv_*.h5`` (combined, no incremental mode)

CSV is the source of truth. ``delete`` is naturally per-symbol safe (drop the
``features/{stem}`` dir + strip the ``instruments`` lines). For ``trim`` /
``refresh`` (CSV content changes) the Qlib binary is re-dumped for *just* that
symbol via the project's own ``dump_bin`` tooling. The combined h5 has no
incremental mode, so callers receive ``h5_stale=True`` to drive a deferred
rebuild via :func:`~alphapilot.systems.data.generate_h5.generate_daily_pv_h5`.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from alphapilot.core.path_safety import ensure_child_path
from alphapilot.log import logger
from alphapilot.systems.data.data_paths import (
    BAOSTOCK_SOURCE,
    TUSHARE_SOURCE,
    existing_baostock_factor_dir,
    existing_baostock_qlib_dir,
    existing_baostock_raw_dir,
    existing_tushare_factor_dir,
    existing_tushare_qlib_dir,
    existing_tushare_raw_dir,
)
from alphapilot.systems.data.prepare_cn import normalize_adjust_mode
from alphapilot.systems.data.qlib_convert import DEFAULT_INCLUDE_FIELDS
from alphapilot.systems.data.stock_list import (
    baostock_to_csv_stem,
    baostock_to_qlib_instrument,
    normalize_to_baostock,
)

INSTRUMENTS_SEP = "\t"
_ADJUST_MODES = ("none", "forward", "backward")


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve_codes(symbol: str) -> tuple[str, str, str]:
    """Return ``(baostock_code, csv_stem, qlib_instrument_id)`` for *symbol*."""
    code = normalize_to_baostock(symbol)
    if not code:
        raise ValueError(f"无法解析股票代码: {symbol!r}")
    return code, baostock_to_csv_stem(code), baostock_to_qlib_instrument(code)


def _resolve_source(source: str | None = None) -> str:
    text = (source or BAOSTOCK_SOURCE).strip().lower()
    if text in {"baostock", BAOSTOCK_SOURCE}:
        return BAOSTOCK_SOURCE
    if text in {"tushare", TUSHARE_SOURCE}:
        return TUSHARE_SOURCE
    raise ValueError(f"不支持的数据源: {source!r}。请使用 baostock_cn 或 tushare_cn。")


def _resolve_adjust_modes(value: str | Iterable[str] | None) -> list[str]:
    """Normalize an adjust-mode selector to a deduped list of modes.

    ``None`` / ``"all"`` / ``""`` -> every known mode; a list/tuple expands and
    dedupes; any other value is normalized via :func:`normalize_adjust_mode`.
    """
    if value is None:
        return list(_ADJUST_MODES)
    if isinstance(value, (list, tuple, set)):
        seen: set[str] = set()
        out: list[str] = []
        for item in value:
            for mode in _resolve_adjust_modes(item):
                if mode not in seen:
                    seen.add(mode)
                    out.append(mode)
        return out
    text = str(value).strip().lower()
    if text in ("", "all"):
        return list(_ADJUST_MODES)
    return [normalize_adjust_mode(text)]


# Public alias for use by the data system service layer.
resolve_adjust_modes = _resolve_adjust_modes


def existing_raw_dir_for_source(mode: str, source: str | None = None) -> Path:
    normalized_mode = normalize_adjust_mode(mode)
    resolved_source = _resolve_source(source)
    if resolved_source == TUSHARE_SOURCE:
        return existing_tushare_raw_dir(normalized_mode)
    return existing_baostock_raw_dir(normalized_mode)


def existing_factor_dir_for_source(source: str | None = None) -> Path:
    if _resolve_source(source) == TUSHARE_SOURCE:
        return existing_tushare_factor_dir()
    return existing_baostock_factor_dir()


def existing_qlib_dir_for_source(source: str | None = None) -> Path:
    if _resolve_source(source) == TUSHARE_SOURCE:
        return existing_tushare_qlib_dir()
    return existing_baostock_qlib_dir()


def _raw_dir(mode: str, source: str | None = None) -> Path:
    return existing_raw_dir_for_source(mode, source)


def _instruments_dir(qlib_dir: str | Path) -> Path:
    return Path(qlib_dir).expanduser() / "instruments"


def _parse_drop_dates(drop_dates: str | Iterable[str] | None) -> set[pd.Timestamp]:
    if not drop_dates:
        return set()
    raw: Iterable[str]
    raw = drop_dates.split(",") if isinstance(drop_dates, str) else drop_dates
    out: set[pd.Timestamp] = set()
    for item in raw:
        ts = pd.to_datetime(str(item).strip(), errors="coerce")
        if not pd.isna(ts):
            out.add(ts.normalize())
    return out


# ---------------------------------------------------------------------------
# Instrument file (universe) helpers
# ---------------------------------------------------------------------------


def _read_instrument_rows(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(line.split(INSTRUMENTS_SEP))
    return rows


def _write_instrument_rows(path: Path, rows: list[list[str]]) -> None:
    path.write_text(
        "".join(INSTRUMENTS_SEP.join(r) + "\n" for r in rows), encoding="utf-8"
    )


def strip_instrument(
    qlib_dir: str | Path, qlib_id: str, *, dry_run: bool = False
) -> list[str]:
    """Remove *qlib_id* from every ``instruments/*.txt`` (all.txt + named pools)."""
    inst_dir = _instruments_dir(qlib_dir)
    if not inst_dir.is_dir():
        return []
    target = qlib_id.upper()
    updated: list[str] = []
    for txt in sorted(inst_dir.glob("*.txt")):
        ensure_child_path(inst_dir, txt)
        rows = _read_instrument_rows(txt)
        kept = [r for r in rows if not (r and r[0].strip().upper() == target)]
        if len(kept) != len(rows):
            updated.append(txt.name)
            if not dry_run:
                _write_instrument_rows(txt, kept)
    return updated


def upsert_instrument(
    qlib_dir: str | Path,
    qlib_id: str,
    start: str,
    end: str,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Correct the ``[start, end]`` range of *qlib_id* in any file that lists it.

    Only updates existing rows — it never injects the symbol into a pool it was
    not already a member of (so re-dumping one stock can't pollute other
    universes). ``all.txt`` is also covered here for consistency.
    """
    inst_dir = _instruments_dir(qlib_dir)
    if not inst_dir.is_dir():
        return []
    target = qlib_id.upper()
    updated: list[str] = []
    for txt in sorted(inst_dir.glob("*.txt")):
        ensure_child_path(inst_dir, txt)
        rows = _read_instrument_rows(txt)
        changed = False
        for r in rows:
            if r and r[0].strip().upper() == target:
                new_row = [target, start, end]
                if r != new_row:
                    r[:] = new_row
                    changed = True
        if changed:
            updated.append(txt.name)
            if not dry_run:
                _write_instrument_rows(txt, rows)
    return updated


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_symbols(
    adjust_mode: str | Iterable[str] | None = None,
    *,
    source: str | None = None,
) -> dict[str, list[str]]:
    """Return ``{mode: [stem, ...]}`` for raw CSVs that exist on disk."""
    result: dict[str, list[str]] = {}
    for mode in _resolve_adjust_modes(adjust_mode):
        root = _raw_dir(mode, source)
        if root.is_dir():
            result[mode] = sorted(p.stem for p in root.glob("*.csv") if p.is_file())
    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def _safe_unlink(target: Path, root: Path, report: dict[str, Any], *, dry_run: bool) -> None:
    if target.is_file():
        ensure_child_path(root, target)
        if not dry_run:
            target.unlink()
        report["deleted"].append(str(target))
    else:
        report["missing"].append(str(target))


def delete_symbol(
    symbol: str,
    *,
    qlib_dir: str | Path,
    factor_dir: str | Path | None = None,
    adjust_modes: str | Iterable[str] | None = None,
    source: str | None = None,
    remove_factor: bool = True,
    remove_qlib_features: bool = True,
    remove_from_instruments: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete one stock across raw CSVs, factor CSV, Qlib features and universe.

    Returns a report; ``h5_stale=True`` always (the combined daily_pv h5 still
    references the removed stock until rebuilt).
    """
    code, stem, qlib_id = _resolve_codes(symbol)
    qlib_dir = Path(qlib_dir).expanduser()
    report: dict[str, Any] = {
        "symbol": code,
        "source": _resolve_source(source),
        "stem": stem,
        "qlib_id": qlib_id,
        "deleted": [],
        "missing": [],
        "instruments_updated": [],
        "dry_run": dry_run,
        "h5_stale": True,
    }

    for mode in _resolve_adjust_modes(adjust_modes):
        root = _raw_dir(mode, source)
        _safe_unlink(root / f"{stem}.csv", root, report, dry_run=dry_run)

    if remove_factor:
        fdir = Path(factor_dir).expanduser() if factor_dir else existing_factor_dir_for_source(source)
        _safe_unlink(fdir / f"{stem}.csv", fdir, report, dry_run=dry_run)

    if remove_qlib_features:
        features_root = qlib_dir / "features"
        feat = features_root / stem
        if feat.is_dir():
            ensure_child_path(features_root, feat)
            if not dry_run:
                shutil.rmtree(feat)
            report["deleted"].append(str(feat))
        else:
            report["missing"].append(str(feat))

    if remove_from_instruments:
        report["instruments_updated"] = strip_instrument(qlib_dir, qlib_id, dry_run=dry_run)

    logger.info(f"删除股票 {code} ({stem}){' [dry-run]' if dry_run else ''}: "
        f"删除 {len(report['deleted'])} 项，缺失 {len(report['missing'])} 项，"
        f"instruments 更新 {report['instruments_updated']}"
    )
    return report


# ---------------------------------------------------------------------------
# Apply adjust (unadjusted CSV + factor -> forward/backward CSV)
# ---------------------------------------------------------------------------


def apply_adjust_symbol(
    symbol: str,
    *,
    target_mode: str = "forward",
    source: str | None = None,
    raw_dir: str | Path | None = None,
    factor_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synthesize one stock's forward/backward CSV from unadjusted bars + factors."""
    from alphapilot.systems.data.adjust_prices import apply_adjust_to_frame

    code, stem, _ = _resolve_codes(symbol)
    mode = normalize_adjust_mode(target_mode)
    if mode == "none":
        raise ValueError("target_mode 须为 forward 或 backward")

    raw_root = Path(raw_dir).expanduser() if raw_dir else _raw_dir("none", source)
    factor_root = Path(factor_dir).expanduser() if factor_dir else existing_factor_dir_for_source(source)
    out_root = Path(output_dir).expanduser() if output_dir else _raw_dir(mode, source)
    csv = raw_root / f"{stem}.csv"
    factor_csv = factor_root / f"{stem}.csv"

    if not csv.is_file():
        raise FileNotFoundError(f"未找到除权 CSV: {csv}")
    if not factor_csv.is_file():
        raise FileNotFoundError(f"未找到复权因子 CSV: {factor_csv}")

    price_df = pd.read_csv(csv)
    factor_df = pd.read_csv(factor_csv)
    adjusted = apply_adjust_to_frame(price_df, factor_df, mode, symbol=stem)
    out_path = out_root / f"{stem}.csv"

    report: dict[str, Any] = {
        "symbol": code,
        "source": _resolve_source(source),
        "stem": stem,
        "target_mode": mode,
        "rows": len(adjusted),
        "output": str(out_path),
        "dry_run": dry_run,
    }
    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)
        adjusted.to_csv(out_path, index=False, encoding="utf-8")
        logger.info(f"单股复权 {code} ({stem}) -> {mode}: {out_path} ({len(adjusted)} 行)")
    return report


# ---------------------------------------------------------------------------
# Trim (local CSV edit)
# ---------------------------------------------------------------------------


def trim_symbol(
    symbol: str,
    *,
    adjust_modes: str | Iterable[str] | None = None,
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
    drop_dates: str | Iterable[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Trim one stock's CSV(s) to ``[start, end]`` and/or drop specific dates.

    Purely local (no network). Per-mode before/after counts are returned;
    ``h5_stale=True`` and the Qlib binary still needs a re-dump afterwards.
    """
    code, stem, _ = _resolve_codes(symbol)
    if start is None and end is None and not drop_dates:
        raise ValueError("裁剪需要至少提供 start / end / drop_dates 之一")

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    drop = _parse_drop_dates(drop_dates)

    report: dict[str, Any] = {
        "symbol": code,
        "source": _resolve_source(source),
        "stem": stem,
        "modes": {},
        "dry_run": dry_run,
        "h5_stale": True,
    }

    for mode in _resolve_adjust_modes(adjust_modes):
        root = _raw_dir(mode, source)
        csv = root / f"{stem}.csv"
        if not csv.is_file():
            report["modes"][mode] = {"status": "missing"}
            continue
        ensure_child_path(root, csv)
        df = pd.read_csv(csv)
        if "date" not in df.columns:
            report["modes"][mode] = {"status": "no_date_column"}
            continue
        dt = pd.to_datetime(df["date"], errors="coerce")
        mask = dt.notna()
        if start_ts is not None:
            mask &= dt >= start_ts
        if end_ts is not None:
            mask &= dt <= end_ts
        if drop:
            mask &= ~dt.dt.normalize().isin(drop)

        before = len(df)
        new_df = df[mask].copy()
        after = len(new_df)
        report["modes"][mode] = {
            "status": "trimmed",
            "before": before,
            "after": after,
            "removed": before - after,
        }
        if not dry_run and after != before:
            new_df["date"] = pd.to_datetime(new_df["date"]).dt.strftime("%Y-%m-%d")
            new_df.to_csv(csv, index=False, encoding="utf-8")

    logger.info(f"裁剪股票 {code} ({stem}){' [dry-run]' if dry_run else ''}: {report['modes']}")
    return report


# ---------------------------------------------------------------------------
# Re-sync edited CSV into the Qlib binary (single symbol)
# ---------------------------------------------------------------------------


def resync_symbol_to_qlib(
    symbol: str,
    *,
    raw_dir: str | Path,
    qlib_dir: str | Path,
    op: str = "trim",
    include_fields: str = DEFAULT_INCLUDE_FIELDS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Re-dump a single symbol's Qlib binary from its (edited) CSV under *raw_dir*.

    * ``op="trim"`` -> :class:`DumpDataFix` (overwrite features against the
      existing calendar; for shrunk/edited data).
    * ``op="refresh"`` -> :class:`DumpDataUpdate` (extend the calendar and append
      new dates).

    The named ``instruments/{market}.txt`` range is corrected from the CSV's
    actual min/max afterwards (``all.txt`` is handled by the dumper). Requires
    an existing ``instruments/all.txt`` + ``calendars/day.txt``; otherwise raises
    with a hint to run the full ``prepare_data convert``.
    """
    code, stem, qlib_id = _resolve_codes(symbol)
    raw_dir = Path(raw_dir).expanduser()
    qlib_dir = Path(qlib_dir).expanduser()
    csv = raw_dir / f"{stem}.csv"

    report: dict[str, Any] = {"symbol": code, "stem": stem, "op": op, "dry_run": dry_run}
    if not csv.is_file():
        raise FileNotFoundError(
            f"重 dump 失败：找不到 {csv}（请确认该复权类型已 download / apply_adjust）"
        )

    all_txt = _instruments_dir(qlib_dir) / "all.txt"
    day_txt = qlib_dir / "calendars" / "day.txt"
    if not all_txt.is_file() or not day_txt.is_file():
        raise FileNotFoundError(
            f"缺少 {all_txt} 或 {day_txt}，无法对单只股票增量 dump。"
            "请改跑全量 `alphapilot prepare_data convert`。"
        )

    dates = pd.to_datetime(pd.read_csv(csv, usecols=["date"])["date"], errors="coerce").dropna()
    if dates.empty:
        raise ValueError(f"{csv} 无有效日期，无法 dump")
    new_start = dates.min().strftime("%Y-%m-%d")
    new_end = dates.max().strftime("%Y-%m-%d")
    report.update(start=new_start, end=new_end)

    if dry_run:
        report["status"] = "dry_run"
        return report

    from alphapilot.systems.data.qlib_dump.dump_bin import DumpDataFix, DumpDataUpdate

    dumper_cls = DumpDataUpdate if op == "refresh" else DumpDataFix
    with tempfile.TemporaryDirectory(prefix="ap_resync_") as tmp:
        shutil.copy2(csv, Path(tmp) / f"{stem}.csv")
        dumper = dumper_cls(
            data_path=str(tmp),
            qlib_dir=str(qlib_dir),
            include_fields=include_fields,
            date_field_name="date",
            symbol_field_name="code",
            max_workers=1,
        )
        dumper.dump()

    report["instruments_updated"] = upsert_instrument(qlib_dir, qlib_id, new_start, new_end)
    report["status"] = "resynced"
    logger.info(f"单股重 dump {code} ({stem}) op={op}: {new_start}~{new_end}")
    return report
