"""Download A-share daily CSV data via baostock with configurable adjustment."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import baostock as bs
import pandas as pd
from dateutil.relativedelta import relativedelta
from tqdm import tqdm

from alphapilot.kernel.paths import default_stock_csv_path
from alphapilot.log import logger
from alphapilot.systems.data.stock_list import load_stocks_from_file, normalize_to_baostock

AdjustMode = Literal["none", "forward", "backward"]

RAW_DIR_BY_MODE: dict[AdjustMode, Path] = {
    "backward": Path("~/.qlib/qlib_data/cn_data/raw_data_back_adjust"),
    "forward": Path("~/.qlib/qlib_data/cn_data/raw_data_forward_adjust"),
    "none": Path("~/.qlib/qlib_data/cn_data/raw_data_no_adjust"),
}
DEFAULT_RAW_DIR = RAW_DIR_BY_MODE["backward"]
DEFAULT_FACTOR_DIR = Path("~/.qlib/qlib_data/cn_data/adjust_factors")
# 复权因子需从足够早的日期拉全历史，否则早期行情会错用「区间内首条除权」的因子
FACTOR_HISTORY_START_DATE = "1990-01-01"
DEFAULT_DOWNLOAD_WORKERS = 1
DEFAULT_STOCK_CSV = default_stock_csv_path()

# baostock 同一 login 会话下 API 须串行，多线程下载时用锁保护
_BAOSTOCK_LOCK = threading.Lock()

_BAOSTOCK_ADJUST_FLAG: dict[AdjustMode, str] = {
    "none": "3",
    "forward": "2",
    "backward": "1",
}

_ADJUST_MODE_ALIASES: dict[str, AdjustMode] = {
    "none": "none",
    "no_adjust": "none",
    "不复权": "none",
    "除权": "none",
    "forward": "forward",
    "前复权": "forward",
    "backward": "backward",
    "后复权": "backward",
}


def normalize_adjust_mode(adjust_mode: str) -> AdjustMode:
    """Normalize CLI/API adjust mode to ``none`` | ``forward`` | ``backward``."""
    key = adjust_mode.strip().lower()
    if key in _ADJUST_MODE_ALIASES:
        return _ADJUST_MODE_ALIASES[key]
    raise ValueError(
        f"不支持的复权类型: {adjust_mode!r}。"
        "请使用 none/不复权/除权、forward/前复权、backward/后复权。"
    )


def default_raw_dir(adjust_mode: str = "backward") -> Path:
    return RAW_DIR_BY_MODE[normalize_adjust_mode(adjust_mode)].expanduser()


def resolve_raw_dir(data_dir: str | Path | None, adjust_mode: str) -> Path:
    if data_dir is None:
        return default_raw_dir(adjust_mode)
    return Path(data_dir).expanduser()


def resolve_factor_dir(factor_dir: str | Path | None) -> Path:
    if factor_dir is None:
        return DEFAULT_FACTOR_DIR.expanduser()
    return Path(factor_dir).expanduser()


def get_all_stocks_in_period(start_date: str, end_date: str) -> list[str]:
    all_stocks: set[str] = set()
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start
    while current <= end:
        query_date = current.strftime("%Y-%m-%d")
        stock_rs = bs.query_all_stock(query_date)
        stock_df = stock_rs.get_data()
        if not stock_df.empty:
            all_stocks.update(stock_df["code"].tolist())
        current += relativedelta(years=1)
        if current > end:
            break
    logger.info(f"共获取到 {len(all_stocks)} 只股票")
    return list(all_stocks)


@dataclass
class _DownloadStats:
    skipped_up_to_date: int = 0
    price_updated: int = 0
    factor_probed: int = 0
    factor_refreshed: int = 0
    factor_skipped: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def incr(self, name: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name) + n)


def _read_price_csv_last_date(csv_path: Path) -> datetime | None:
    """Read the last trade date from a price CSV without loading the full file."""
    if not csv_path.exists():
        return None
    try:
        with csv_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            if size == 0:
                return None
            read_size = min(size, 4096)
            handle.seek(size - read_size)
            tail_lines = handle.read().splitlines()
    except OSError:
        return None

    for raw_line in reversed(tail_lines):
        line = raw_line.decode("utf-8").strip()
        if not line or line.startswith("date"):
            continue
        date_str = line.split(",", 1)[0]
        parsed = pd.to_datetime(date_str, errors="coerce")
        if pd.isna(parsed):
            continue
        return parsed.to_pydatetime()

    return None


def factor_covers_price_history(factor_df: pd.DataFrame, price_df: pd.DataFrame) -> bool:
    """Return True if factor history extends to (or before) the first price bar."""
    if factor_df.empty or price_df.empty or "dividOperateDate" not in factor_df.columns:
        return False
    min_price = pd.to_datetime(price_df["date"], errors="coerce").min()
    first_ex = pd.to_datetime(factor_df["dividOperateDate"], errors="coerce").min()
    if pd.isna(min_price) or pd.isna(first_ex):
        return False
    return first_ex <= min_price + pd.Timedelta(days=5)


def _factor_file_path(code: str, factor_dir: Path) -> Path:
    return factor_dir / f"{code.replace('.', '')}.csv"


def _load_local_factor_df(factor_file: Path) -> pd.DataFrame | None:
    if not factor_file.exists():
        return None
    factor_df = pd.read_csv(factor_file)
    if factor_df.empty:
        return factor_df
    if "dividOperateDate" in factor_df.columns:
        factor_df["dividOperateDate"] = pd.to_datetime(
            factor_df["dividOperateDate"], errors="coerce"
        )
    return factor_df


def _has_adjust_event_in_period(code: str, start_date: str, end_date: str) -> bool:
    """
    Probe baostock for corporate-action events in ``[start_date, end_date]``.

    Uses ``query_adjust_factor`` with a narrow date range; returns True when at
    least one row exists (i.e. a 除权除息 occurred in the window).
    """
    with _BAOSTOCK_LOCK:
        rs_adj = bs.query_adjust_factor(code, start_date=start_date, end_date=end_date)
        if rs_adj.error_code != "0":
            logger.warning(f"探测 {code} 除权事件失败: {rs_adj.error_msg}")
            return True

        while rs_adj.next():
            return True

    return False


def _maybe_download_adjust_factors(
    code: str,
    end_date: str,
    factor_dir: Path,
    *,
    incremental_start: str,
    price_df: pd.DataFrame | None = None,
    stats: _DownloadStats | None = None,
) -> None:
    """
    Refresh adjust factors only when necessary.

    - No local factor file / incomplete coverage -> full history download.
    - Otherwise probe ``[incremental_start, end_date]`` (same window as new bars).
    - When events exist in the probe window -> full history download.
    """
    factor_file = _factor_file_path(code, factor_dir)
    local_factor = _load_local_factor_df(factor_file)

    if local_factor is None or local_factor.empty:
        _download_adjust_factors(code, end_date, factor_dir)
        if stats is not None:
            stats.incr("factor_refreshed")
        return

    if price_df is not None and not factor_covers_price_history(local_factor, price_df):
        logger.info(f"{code} 本地复权因子未覆盖行情起点，全量刷新因子")
        _download_adjust_factors(code, end_date, factor_dir)
        if stats is not None:
            stats.incr("factor_refreshed")
        return

    if incremental_start > end_date:
        return

    if stats is not None:
        stats.incr("factor_probed")

    if not _has_adjust_event_in_period(code, incremental_start, end_date):
        logger.debug(f"{code} {incremental_start}~{end_date} 无除权操作，跳过因子下载")
        if stats is not None:
            stats.incr("factor_skipped")
        return

    logger.info(f"{code} {incremental_start}~{end_date} 有除权操作，全量刷新因子")
    _download_adjust_factors(code, end_date, factor_dir)
    if stats is not None:
        stats.incr("factor_refreshed")


def _download_adjust_factors(
    code: str,
    end_date: str,
    factor_dir: Path,
) -> None:
    """
    Download full adjust-factor history for *code* and overwrite the local CSV.

    Called whenever bar data is updated (full or incremental) so factors stay consistent.
    """
    factor_file = _factor_file_path(code, factor_dir)

    with _BAOSTOCK_LOCK:
        rs_adj = bs.query_adjust_factor(
            code,
            start_date=FACTOR_HISTORY_START_DATE,
            end_date=end_date,
        )
        if rs_adj.error_code != "0":
            logger.warning(f"获取 {code} 复权因子失败: {rs_adj.error_msg}")
            return

        rs_list = []
        while rs_adj.next():
            rs_list.append(rs_adj.get_row_data())

    factor_dir.mkdir(parents=True, exist_ok=True)
    if not rs_list:
        pd.DataFrame(columns=rs_adj.fields).to_csv(factor_file, index=False, encoding="utf-8")
        return

    factor_df = pd.DataFrame(rs_list, columns=rs_adj.fields)
    if "dividOperateDate" in factor_df.columns:
        factor_df["dividOperateDate"] = pd.to_datetime(factor_df["dividOperateDate"])
        factor_df = factor_df.drop_duplicates(subset=["dividOperateDate"], keep="last")
        factor_df = factor_df.sort_values("dividOperateDate")
    factor_df.to_csv(factor_file, index=False, encoding="utf-8")


def refresh_adjust_factors(
    codes: list[str],
    end_date: str,
    factor_dir: str | Path,
    max_workers: int = 1,
) -> None:
    """Re-download full adjust-factor history for all *codes* (from FACTOR_HISTORY_START_DATE)."""
    factor_path = resolve_factor_dir(factor_dir)
    # baostock 同一 session 不支持多线程并发，max_workers>1 容易在十余只后卡死
    if max_workers != 1:
        logger.warning(
            f"复权因子刷新强制使用 max_workers=1（baostock 不支持并发），已忽略 {max_workers}"
        )
        max_workers = 1

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")

    try:
        logger.info(
            f"刷新复权因子: {FACTOR_HISTORY_START_DATE} ~ {end_date} -> {factor_path}"
        )

        for code in tqdm(codes, desc="复权因子"):
            try:
                _download_adjust_factors(code, end_date, factor_path)
            except Exception as exc:
                logger.warning(f"刷新 {code} 复权因子失败: {exc}")
    finally:
        bs.logout()


def refresh_adjust_factors_for_raw_dir(
    raw_dir: str | Path,
    factor_dir: str | Path,
    end_date: str,
    max_workers: int = 1,
) -> None:
    """Refresh factors for every symbol CSV under *raw_dir*."""
    raw_path = Path(raw_dir).expanduser()
    codes: list[str] = []
    for csv_file in sorted(raw_path.glob("*.csv")):
        df = pd.read_csv(csv_file, usecols=["code"], nrows=1)
        if df.empty:
            continue
        parsed = normalize_to_baostock(str(df["code"].iloc[0]))
        if parsed:
            codes.append(parsed)
    refresh_adjust_factors(codes, end_date, factor_dir, max_workers=max_workers)


def download_stock_data(
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    stock_csv_path: str | Path | None = None,
    code_column: str | None = None,
    all_market: bool = False,
    max_workers: int = DEFAULT_DOWNLOAD_WORKERS,
    adjust_mode: str = "backward",
    factor_dir: str | Path | None = None,
    symbols: list[str] | None = None,
) -> list[str]:
    """
    Download daily CSV files. Returns the list of baostock codes that were requested.

    Args:
        adjust_mode: ``none`` (不复权/除权), ``forward`` (前复权), ``backward`` (后复权).
        factor_dir: When ``adjust_mode`` is ``none``, save adjust factors under this directory.
        symbols: Explicit list of codes (any supported format). When provided, takes
            precedence over ``stock_csv_path`` / ``all_market`` (used for single-stock refresh).
    """
    mode = normalize_adjust_mode(adjust_mode)
    adjustflag = _BAOSTOCK_ADJUST_FLAG[mode]
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    factor_path = resolve_factor_dir(factor_dir) if mode == "none" else None

    if symbols:
        all_stocks = [c for c in (normalize_to_baostock(s) for s in symbols) if c]
        if not all_stocks:
            raise ValueError(f"未从 symbols 解析到有效股票代码: {symbols}")
    elif all_market:
        all_stocks = get_all_stocks_in_period(start_date, end_date)
    elif stock_csv_path:
        all_stocks = load_stocks_from_file(stock_csv_path, code_column=code_column)
    else:
        all_stocks = get_all_stocks_in_period(start_date, end_date)

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")

    stats = _DownloadStats()

    try:
        fields = (
            "date,code,open,high,low,close,preclose,volume,amount,turn,"
            "tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
        )

        def download_single_stock(code: str) -> None:
            code_clean = code.replace(".", "")
            output_file = output_path / f"{code_clean}.csv"

            last_date = _read_price_csv_last_date(output_file)
            if last_date is not None:
                last_date_str = last_date.strftime("%Y-%m-%d")
                if last_date_str >= end_date:
                    stats.incr("skipped_up_to_date")
                    return
                code_download_start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                code_download_start_date = start_date

            logger.info(
                f"下载 {code} ({mode}) ... {code_download_start_date} ~ {end_date}"
            )
            with _BAOSTOCK_LOCK:
                rs = bs.query_history_k_data_plus(
                    code,
                    fields,
                    start_date=code_download_start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag=adjustflag,
                )
                if rs.error_code != "0":
                    logger.warning(f"获取 {code} 失败: {rs.error_msg}")
                    stats.incr("errors")
                    return

                data_list = []
                while rs.next():
                    data_list.append(rs.get_row_data())

            if not data_list:
                return

            new_df = pd.DataFrame(data_list, columns=rs.fields)
            new_df["code"] = new_df["code"].str.replace(".", "", regex=False)
            new_df["date"] = pd.to_datetime(new_df["date"], errors="coerce")
            for col in new_df.columns:
                if col not in ("code", "date"):
                    new_df[col] = pd.to_numeric(new_df[col], errors="coerce")

            if output_file.exists() and last_date is not None:
                existing_df = pd.read_csv(output_file)
                existing_df["date"] = pd.to_datetime(existing_df["date"])
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=["date", "code"])
                combined_df["date"] = pd.to_datetime(combined_df["date"])
                combined_df = combined_df.sort_values("date")
            else:
                combined_df = new_df

            combined_df.to_csv(output_file, index=False, encoding="utf-8")
            stats.incr("price_updated")

            if mode == "none" and factor_path is not None:
                _maybe_download_adjust_factors(
                    code,
                    end_date,
                    factor_path,
                    incremental_start=code_download_start_date,
                    price_df=combined_df,
                    stats=stats,
                )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(download_single_stock, code) for code in all_stocks]
            for _ in tqdm(as_completed(futures), total=len(futures), desc="下载进度"):
                pass

        logger.info(
            "下载统计: "
            f"跳过(已最新)={stats.skipped_up_to_date}, "
            f"补行情={stats.price_updated}, "
            f"因子探测={stats.factor_probed}, "
            f"因子全量刷新={stats.factor_refreshed}, "
            f"因子跳过={stats.factor_skipped}, "
            f"错误={stats.errors}"
        )
    finally:
        bs.logout()

    return all_stocks


def download_cn_data(
    start_date: str = "2016-12-31",
    end_date: str | None = None,
    data_dir: str | Path | None = None,
    stock_csv: str | Path | None = DEFAULT_STOCK_CSV,
    code_column: str | None = None,
    all_market: bool = False,
    max_workers: int = DEFAULT_DOWNLOAD_WORKERS,
    adjust_mode: str = "backward",
    factor_dir: str | Path | None = None,
    symbols: list[str] | None = None,
) -> list[str]:
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    raw_dir = resolve_raw_dir(data_dir, adjust_mode)
    mode = normalize_adjust_mode(adjust_mode)
    logger.info(
        f"开始下载 A 股数据 ({mode}): {start_date} ~ {end_date} -> {raw_dir}"
    )
    if mode == "none":
        logger.info(f"复权因子目录: {resolve_factor_dir(factor_dir)}")
    codes = download_stock_data(
        start_date,
        end_date,
        raw_dir,
        stock_csv_path=stock_csv,
        code_column=code_column,
        all_market=all_market,
        max_workers=max_workers,
        adjust_mode=adjust_mode,
        factor_dir=factor_dir,
        symbols=symbols,
    )
    logger.info("CSV 下载完成。")
    return codes
