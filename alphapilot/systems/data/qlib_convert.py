"""Convert baostock CSV dumps to Qlib binary format and extend trading calendar."""

from __future__ import annotations

from pathlib import Path

from alphapilot.systems.data.qlib_dump.dump_bin import DumpDataAll
from alphapilot.systems.data.qlib_dump.future_calendar_collector import run as collect_future_calendar
from alphapilot.log import logger

from alphapilot.systems.data.data_paths import (
    existing_baostock_qlib_dir,
    existing_baostock_raw_dir,
)

DEFAULT_RAW_DIR = existing_baostock_raw_dir("backward")
DEFAULT_QLIB_DIR = existing_baostock_qlib_dir()
DEFAULT_INCLUDE_FIELDS = "open,high,low,close,preclose,volume,amount,turn,factor"


def dump_csv_to_qlib(
    data_path: str | Path = DEFAULT_RAW_DIR,
    qlib_dir: str | Path = DEFAULT_QLIB_DIR,
    include_fields: str = DEFAULT_INCLUDE_FIELDS,
    date_field_name: str = "date",
    symbol_field_name: str = "code",
    max_workers: int = 16,
    freq: str = "day",
) -> None:
    """Convert per-symbol CSV files under *data_path* to Qlib binary under *qlib_dir*."""
    data_path = Path(data_path).expanduser()
    qlib_dir = Path(qlib_dir).expanduser()

    if not data_path.is_dir() or not any(data_path.glob("*.csv")):
        raise FileNotFoundError(
            f"未在 {data_path} 找到 CSV 文件。请先运行: alphapilot prepare_data download"
        )

    logger.info(f"开始转换 CSV -> Qlib 二进制: {data_path} -> {qlib_dir}")
    dumper = DumpDataAll(
        data_path=str(data_path),
        qlib_dir=str(qlib_dir),
        include_fields=include_fields,
        date_field_name=date_field_name,
        symbol_field_name=symbol_field_name,
        max_workers=max_workers,
        freq=freq,
    )
    dumper.dump()
    logger.info("Qlib 二进制转换完成。")


def extend_future_calendar(
    qlib_dir: str | Path = DEFAULT_QLIB_DIR,
    region: str = "cn",
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Write calendars/day_future.txt using baostock trade dates."""
    qlib_dir = Path(qlib_dir).expanduser()
    calendar_path = qlib_dir / "calendars" / "day.txt"
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"交易日历不存在: {calendar_path}。请先运行: alphapilot prepare_data dump"
        )

    logger.info(f"扩展未来交易日历 (region={region}): {qlib_dir}")
    collect_future_calendar(
        qlib_dir=str(qlib_dir),
        region=region,
        start_date=start_date,
        end_date=end_date,
    )
    logger.info("未来交易日历写入完成。")
