"""Market-data loading for timing strategies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.systems.data.data_paths import baostock_minute_raw_dir
from alphapilot.systems.data.frequency import get_frequency
from alphapilot.systems.data.stock_list import (
    baostock_to_csv_stem,
    baostock_to_qlib_instrument,
    load_stocks_from_file,
    normalize_to_baostock,
)

BAR_COLUMNS = ["datetime", "instrument", "open", "high", "low", "close", "volume", "amount"]


def parse_symbols(symbols: list[str] | str | None) -> list[str]:
    if symbols is None:
        return []
    raw = symbols if isinstance(symbols, list) else str(symbols).split(",")
    out: list[str] = []
    for item in raw:
        parsed = normalize_to_baostock(str(item).strip())
        if parsed:
            out.append(parsed)
    return list(dict.fromkeys(out))


def resolve_symbols(
    *,
    symbols: list[str] | str | None = None,
    stock_csv: str | Path | None = None,
    code_column: str | None = None,
    data_dir: str | Path | None = None,
) -> list[str]:
    parsed = parse_symbols(symbols)
    if parsed:
        return parsed
    if stock_csv:
        return load_stocks_from_file(stock_csv, code_column=code_column)
    if data_dir:
        codes: list[str] = []
        for csv_file in sorted(Path(data_dir).expanduser().glob("*.csv")):
            stem = csv_file.stem
            if len(stem) >= 8 and stem[:2].lower() in {"sh", "sz", "bj"}:
                codes.append(f"{stem[:2].lower()}.{stem[2:8]}")
        return codes
    return []


def default_data_dir(context: Any, *, freq: str = "day", adjust_mode: str = "backward") -> Path:
    spec = get_frequency(freq)
    if spec.is_intraday:
        return baostock_minute_raw_dir(freq)
    data_system = context.data() if hasattr(context, "data") else context.engine.get_system("data")
    return data_system.storage.raw_dir_for_mode(adjust_mode)


def _read_one(csv_path: Path, code: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"code": str})
    if df.empty or "date" not in df.columns:
        return pd.DataFrame(columns=BAR_COLUMNS)
    out = pd.DataFrame()
    out["datetime"] = pd.to_datetime(df["date"], errors="coerce")
    out["instrument"] = baostock_to_qlib_instrument(code)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        out[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.NA
    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    return out[BAR_COLUMNS]


def load_bars(
    context: Any,
    *,
    symbols: list[str] | str | None = None,
    stock_csv: str | Path | None = None,
    code_column: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    freq: str = "day",
    data_dir: str | Path | None = None,
    adjust_mode: str = "backward",
) -> pd.DataFrame:
    data_root = Path(data_dir).expanduser() if data_dir else default_data_dir(
        context, freq=freq, adjust_mode=adjust_mode
    )
    codes = resolve_symbols(
        symbols=symbols,
        stock_csv=stock_csv,
        code_column=code_column,
        data_dir=data_root,
    )
    if not codes:
        raise ValueError("timing requires symbols, stock_csv, or CSV files under data_dir")

    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for code in codes:
        csv_path = data_root / f"{baostock_to_csv_stem(code)}.csv"
        if not csv_path.is_file():
            missing.append(code)
            continue
        frame = _read_one(csv_path, code)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"no timing CSV data found in {data_root}; missing={missing[:5]}")

    bars = pd.concat(frames, ignore_index=True).sort_values(["datetime", "instrument"])
    if start_date:
        bars = bars[bars["datetime"] >= pd.Timestamp(start_date)]
    if end_date:
        # Date-only end dates include the full session.
        end = pd.Timestamp(end_date)
        if end.time() == pd.Timestamp(end.date()).time():
            end = end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        bars = bars[bars["datetime"] <= end]
    if bars.empty:
        raise ValueError(
            f"no bars after date filtering: start={start_date} end={end_date} data_dir={data_root}"
        )
    return bars.reset_index(drop=True)
