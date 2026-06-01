"""Load downloaded A-share daily bars from local CSV storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

AdjustMode = Literal["none", "forward", "backward"]

ADJUST_LABELS: dict[AdjustMode, str] = {
    "none": "除权 (raw_data_no_adjust)",
    "forward": "前复权 (raw_data_forward_adjust)",
    "backward": "后复权 (raw_data_back_adjust)",
}


@dataclass(frozen=True)
class DataSourceInfo:
    """A browsable on-disk data directory."""

    adjust_mode: AdjustMode
    path: Path
    label: str


def list_data_sources() -> list[DataSourceInfo]:
    """Return existing raw CSV roots (one per adjust mode that exists on disk)."""
    from alphapilot.systems.data.prepare_cn import RAW_DIR_BY_MODE

    sources: list[DataSourceInfo] = []
    for mode, path in RAW_DIR_BY_MODE.items():
        resolved = path.expanduser()
        if resolved.is_dir():
            sources.append(
                DataSourceInfo(
                    adjust_mode=mode,
                    path=resolved,
                    label=ADJUST_LABELS[mode],
                )
            )
    return sources


def list_symbols(data_dir: Path) -> list[str]:
    """List stock codes from ``{code}.csv`` files under *data_dir*."""
    root = Path(data_dir).expanduser()
    if not root.is_dir():
        return []
    symbols = sorted(p.stem for p in root.glob("*.csv") if p.is_file())
    return symbols


def _normalize_symbol(symbol: str) -> str:
    """Map user input to on-disk filename stem (e.g. ``sh.600000`` -> ``sh600000``)."""
    s = symbol.strip().lower().replace(".", "")
    if len(s) == 8 and s[:2] in ("sh", "sz") and s[2:].isdigit():
        return s
    if s.isdigit() and len(s) == 6:
        prefix = "sh" if s.startswith(("5", "6", "9")) else "sz"
        return f"{prefix}{s}"
    return s


def load_bars(
    symbol: str,
    data_dir: Path,
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Load OHLCV (+ optional fields) for one symbol, optionally filtered by date."""
    root = Path(data_dir).expanduser()
    stem = _normalize_symbol(symbol)
    csv_path = root / f"{stem}.csv"
    if not csv_path.exists():
        matches = list(root.glob(f"*{stem}*.csv"))
        if not matches:
            raise FileNotFoundError(f"未找到股票数据文件: {csv_path}")
        csv_path = matches[0]

    df = pd.read_csv(csv_path)
    if df.empty:
        return df

    if "date" not in df.columns:
        raise ValueError(f"CSV 缺少 date 列: {csv_path}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turn",
        "pctChg",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end is not None:
        df = df[df["date"] <= pd.Timestamp(end)]

    df = df.reset_index(drop=True)
    return df


def available_date_range(df: pd.DataFrame) -> tuple[date, date]:
    if df.empty:
        today = datetime.now().date()
        return today, today
    return df["date"].min().date(), df["date"].max().date()


def format_symbol_label(stem: str) -> str:
    """Display ``sh600000`` as ``sh.600000``."""
    if len(stem) >= 8 and stem[:2] in ("sh", "sz"):
        return f"{stem[:2]}.{stem[2:]}"
    return stem
