"""Download A-share intraday (minute) K-line CSV via baostock.

baostock only provides 5/15/30/60-minute bars (no 1-minute). The minute schema
differs from daily (no ``preclose``/``turn``/``pctChg``/... and an extra intraday
``time`` column), so this lives separately from the daily ``prepare_cn`` pipeline.

Bars are fetched already adjusted via baostock ``adjustflag`` (no separate adjust-
factor synthesis). The baostock ``time`` field (``YYYYMMDDHHMMSSsss``) is folded
into the ``date`` column as ``YYYY-MM-DD HH:MM:SS`` so the existing qlib dumper
(``date_field_name="date"``) emits a high-frequency calendar/bins with no change.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import baostock as bs
import pandas as pd

from alphapilot.log import logger
from alphapilot.systems.data.data_paths import BAOSTOCK_SOURCE, baostock_minute_raw_dir
from alphapilot.systems.data.download_state import (
    DownloadStateStore,
    resolve_download_state_path,
)
from alphapilot.systems.data.frequency import FrequencySpec, get_frequency
from alphapilot.systems.data.prepare_cn import (
    DEFAULT_STOCK_CSV,
    _BAOSTOCK_ADJUST_FLAG,
    _BAOSTOCK_LOCK,
    normalize_adjust_mode,
)
from alphapilot.systems.data.stock_list import load_stocks_from_file, normalize_to_baostock


def _normalize_minute_frame(rows: list[list[str]], columns: list[str], spec: FrequencySpec) -> pd.DataFrame:
    """Turn raw baostock minute rows into the on-disk CSV schema.

    The ``date`` column becomes the full intraday timestamp (built from baostock's
    ``time``), which is what the qlib dumper keys on for high-frequency calendars.
    """
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        return df
    df["code"] = df["code"].str.replace(".", "", regex=False)
    # baostock minute ``time`` is ``YYYYMMDDHHMMSSsss`` (trailing milliseconds).
    stamp = pd.to_datetime(df["time"], format="%Y%m%d%H%M%S%f", errors="coerce")
    df["date"] = stamp.dt.strftime("%Y-%m-%d %H:%M:%S")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "close"])


def download_cn_minute_data(
    start_date: str,
    end_date: str | None = None,
    freq: str = "5min",
    data_dir: str | Path | None = None,
    stock_csv: str | Path | None = DEFAULT_STOCK_CSV,
    code_column: str | None = None,
    symbols: list[str] | None = None,
    adjust_mode: str = "backward",
    max_workers: int = 1,
    download_state_path: str | Path | None = None,
) -> list[str]:
    """Download intraday bars for *freq* into per-symbol CSV files.

    Returns the list of baostock codes that were requested (mirrors
    ``download_cn_data``). Whole-market minute download is intentionally not
    supported (data volume); pass ``symbols`` or ``stock_csv``.
    """
    spec = get_frequency(freq)
    if not spec.is_intraday:
        raise ValueError(
            f"download_cn_minute_data is for intraday freq, got {freq!r}; use download_cn_data for daily"
        )

    end_date = end_date or datetime.now().strftime("%Y-%m-%d")
    mode = normalize_adjust_mode(adjust_mode)
    adjustflag = _BAOSTOCK_ADJUST_FLAG[mode]
    raw_dir = Path(data_dir).expanduser() if data_dir else baostock_minute_raw_dir(freq)
    raw_dir.mkdir(parents=True, exist_ok=True)

    if symbols:
        codes = [c for c in (normalize_to_baostock(s) for s in symbols) if c]
    elif stock_csv:
        codes = load_stocks_from_file(stock_csv, code_column=code_column)
    else:
        codes = []
    if not codes:
        raise ValueError(
            "minute download requires resolvable symbols or stock_csv (all-market minute is unsupported)"
        )

    state_path = resolve_download_state_path(download_state_path, raw_dir)
    state_store = DownloadStateStore(state_path)
    source = BAOSTOCK_SOURCE

    logger.info(
        f"开始下载 A 股分钟数据 freq={spec.key} ({mode}): {start_date} ~ {end_date} -> {raw_dir}"
    )

    def _download_one(code: str) -> str | None:
        output_file = raw_dir / f"{code.replace('.', '')}.csv"
        with _BAOSTOCK_LOCK:
            rs = bs.query_history_k_data_plus(
                code,
                spec.csv_fields,
                start_date=start_date,
                end_date=end_date,
                frequency=spec.baostock_code,
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                logger.warning(f"获取 {code} 分钟数据失败: {rs.error_msg}")
                state_store.upsert(
                    source=source, adjust_mode=mode, code=code, raw_dir=raw_dir,
                    last_status="error", last_error=rs.error_msg,
                )
                return None
            rows = []
            fields = rs.fields
            while rs.next():
                rows.append(rs.get_row_data())

        new_df = _normalize_minute_frame(rows, fields, spec)
        if new_df.empty:
            state_store.upsert(
                source=source, adjust_mode=mode, code=code, raw_dir=raw_dir,
                checked_until=end_date, last_status="empty", last_error="", mark_success=True,
            )
            return None

        if output_file.exists():
            existing = pd.read_csv(output_file, dtype={"code": str})
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["date", "code"]).sort_values("date")
        else:
            combined = new_df.sort_values("date")

        combined.to_csv(output_file, index=False, encoding="utf-8")
        data_end = str(combined["date"].max())[:10]
        state_store.upsert(
            source=source, adjust_mode=mode, code=code, raw_dir=raw_dir,
            data_end_date=data_end, checked_until=end_date,
            last_status="updated", last_error="", mark_success=True,
        )
        logger.info(f"下载 {code} 分钟数据 {spec.key} 完成: {len(combined)} 行 -> {output_file.name}")
        return code

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    try:
        if max_workers and max_workers > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                written = [c for c in pool.map(_download_one, codes) if c]
        else:
            written = [c for c in (_download_one(code) for code in codes) if c]
    finally:
        bs.logout()

    logger.info(f"分钟数据下载完成: {len(written)}/{len(codes)} 只 -> {raw_dir}")
    return codes
