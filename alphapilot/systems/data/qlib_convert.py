"""Convert baostock CSV dumps to Qlib binary format and extend trading calendar."""

from __future__ import annotations

from pathlib import Path

from alphapilot.systems.data.qlib_dump.dump_bin import DumpDataAll, DumpDataUpdate
from alphapilot.systems.data.qlib_dump.future_calendar_collector import run as collect_future_calendar
from alphapilot.log import logger

from alphapilot.systems.data.data_paths import (
    existing_baostock_qlib_dir,
    existing_baostock_raw_dir,
)

DEFAULT_RAW_DIR = existing_baostock_raw_dir("backward")
DEFAULT_QLIB_DIR = existing_baostock_qlib_dir()
DEFAULT_INCLUDE_FIELDS = "open,high,low,close,preclose,volume,amount,turn,factor"

# Backtest benchmark. The conf templates default to ``SH000905`` (中证500); qlib's
# PortAnaRecord loads the benchmark's ``$close`` from the provider data, but the
# stock download pipeline never fetches indices. ``sh.000905`` is the baostock code
# whose qlib instrument id is ``SH000905``.
DEFAULT_BENCHMARK_INDEX = "sh.000905"


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


def ensure_benchmark_index(
    qlib_dir: str | Path = DEFAULT_QLIB_DIR,
    index_code: str = DEFAULT_BENCHMARK_INDEX,
    start_date: str = "2015-01-01",
    end_date: str | None = None,
) -> None:
    """Ensure the backtest benchmark index exists in *qlib_dir*.

    The stock download pipeline only fetches individual equities, so the benchmark
    index referenced by ``conf.yaml`` (default ``SH000905`` / 中证500) is missing and
    ``qrun`` aborts with ``ValueError: The benchmark [...] does not exist``. This
    downloads the index's daily bars from baostock and dumps them via
    ``DumpDataUpdate`` -- idempotent: a brand-new instrument is dumped over the full
    calendar, an existing one only gets the new trading days appended.
    """
    import tempfile
    from datetime import datetime

    qlib_dir = Path(qlib_dir).expanduser()
    end_date = end_date or datetime.now().strftime("%Y-%m-%d")

    calendar_path = qlib_dir / "calendars" / "day.txt"
    if not calendar_path.exists():
        logger.warning(
            f"跳过基准指数写入: 交易日历不存在 {calendar_path}（请先完成 dump/convert）。"
        )
        return

    stem = index_code.replace(".", "").lower()  # sh.000905 -> sh000905
    instrument = stem.upper()  # -> SH000905

    # Repair a half-written instrument (listed in all.txt but no feature bin), so
    # DumpDataUpdate treats it as new and re-dumps the full history.
    instruments_file = qlib_dir / "instruments" / "all.txt"
    feature_close = qlib_dir / "features" / stem / "close.day.bin"
    if instruments_file.exists() and not feature_close.exists():
        lines = instruments_file.read_text(encoding="utf-8").splitlines()
        kept = [ln for ln in lines if ln.split("\t", 1)[0].strip().upper() != instrument]
        if len(kept) != len(lines):
            instruments_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
            logger.info(f"清理无特征数据的基准条目: {instrument}")

    try:
        import baostock as bs
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - dependency guard
        logger.warning(f"跳过基准指数写入: 缺少依赖 {exc}。")
        return

    fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
    logger.info(f"下载基准指数 {index_code} ({instrument}) -> {qlib_dir}")
    lg = bs.login()
    try:
        if lg.error_code != "0":
            logger.warning(f"跳过基准指数写入: baostock 登录失败 {lg.error_msg}。")
            return
        rs = bs.query_history_k_data_plus(
            index_code, fields, start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="3",  # 指数无需复权
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    finally:
        bs.logout()

    if not rows:
        logger.warning(f"跳过基准指数写入: {index_code} 未返回数据。")
        return

    df = pd.DataFrame(rows, columns=fields.split(","))
    df["code"] = stem  # 与个股 CSV 一致，dumper 经 fname_to_code 还原为 SH000905
    numeric = ["open", "high", "low", "close", "preclose", "volume", "amount"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["date", "code", *numeric]].dropna(subset=["close"])

    with tempfile.TemporaryDirectory(prefix="benchmark_") as tmp:
        df.to_csv(Path(tmp) / f"{stem}.csv", index=False, encoding="utf-8")
        DumpDataUpdate(
            data_path=tmp,
            qlib_dir=str(qlib_dir),
            include_fields="open,high,low,close,preclose,volume,amount",
            date_field_name="date",
            symbol_field_name="code",
            max_workers=1,
        ).dump()
    logger.info(
        f"基准指数写入完成: {instrument} ({len(df)} 行, {df['date'].min()} ~ {df['date'].max()})"
    )
