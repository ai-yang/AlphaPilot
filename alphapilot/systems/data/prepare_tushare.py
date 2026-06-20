"""Download A-share daily CSV data via Tushare with AlphaPilot-compatible schema."""

from __future__ import annotations

import os
import multiprocessing as mp
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from alphapilot.log import logger
from alphapilot.systems.data.download_state import (
    DownloadStateStore,
    resolve_download_state_path,
)
from alphapilot.systems.data.data_paths import (
    TUSHARE_FACTOR_DIR,
    TUSHARE_RAW_DIR_BY_MODE,
    TUSHARE_SOURCE,
    canonical_tushare_factor_dir,
    canonical_tushare_raw_dir,
)
from alphapilot.systems.data.adjust_prices import lookup_factor_for_dates
from alphapilot.systems.data.prepare_cn import (
    AdjustMode,
    normalize_adjust_mode,
)
from alphapilot.systems.data.stock_list import (
    load_stocks_from_file,
    normalize_to_baostock,
)

TUSHARE_DATA_ROOT = canonical_tushare_raw_dir("none").parent
DEFAULT_TUSHARE_WORKERS = 1
DEFAULT_TUSHARE_FACTOR_DIR = TUSHARE_FACTOR_DIR

PRICE_COLUMNS = [
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "tradestatus",
    "pctChg",
    "peTTM",
    "pbMRQ",
    "psTTM",
    "pcfNcfTTM",
    "isST",
]
FACTOR_COLUMNS = [
    "code",
    "dividOperateDate",
    "adjustFactor",
    "foreAdjustFactor",
    "backAdjustFactor",
]
_TUSHARE_ADJ_BY_MODE = {
    "none": None,
    "forward": "qfq",
    "backward": "hfq",
}

# Tushare ``daily_basic`` (每日指标) is gated behind the 2000-point tier. Its
# fields map onto the price-CSV columns ``pro.daily`` cannot fill, which the
# baostock schema already reserves (left as NA when daily_basic is disabled).
DAILY_BASIC_COLUMN_MAP: dict[str, str] = {
    "turnover_rate": "turn",
    "pe_ttm": "peTTM",
    "pb": "pbMRQ",
    "ps_ttm": "psTTM",
}
DAILY_BASIC_FIELDS = "ts_code,trade_date," + ",".join(DAILY_BASIC_COLUMN_MAP)


@dataclass
class _TushareDownloadStats:
    skipped_up_to_date: int = 0
    price_updated: int = 0
    factor_updated: int = 0
    basic_updated: int = 0
    basic_failed: int = 0
    skipped_no_trading_days: int = 0
    empty: int = 0
    errors: int = 0
    _lock: Any = field(default_factory=lambda: None, repr=False)

    def __post_init__(self) -> None:
        import threading

        self._lock = threading.Lock()

    def incr(self, name: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name) + n)


def default_tushare_raw_dir(adjust_mode: str = "none") -> Path:
    """Return the default Tushare raw-data directory for an adjust mode."""
    return canonical_tushare_raw_dir(normalize_adjust_mode(adjust_mode))


def resolve_tushare_raw_dir(data_dir: str | Path | None, adjust_mode: str) -> Path:
    if data_dir is None:
        return default_tushare_raw_dir(adjust_mode)
    return Path(data_dir).expanduser()


def default_tushare_factor_dir() -> Path:
    return canonical_tushare_factor_dir()


def resolve_tushare_factor_dir(factor_dir: str | Path | None) -> Path:
    if factor_dir is None:
        return default_tushare_factor_dir()
    return Path(factor_dir).expanduser()


def baostock_to_tushare(code: str) -> str:
    """Convert ``sz.000001`` to Tushare ``000001.SZ``."""
    parsed = normalize_to_baostock(code)
    if parsed is None:
        raise ValueError(f"无法转换为 Tushare 股票代码: {code}")
    exchange, number = parsed.split(".", 1)
    return f"{number}.{exchange.upper()}"


def tushare_to_baostock(ts_code: str) -> str:
    """Convert Tushare ``000001.SZ`` to ``sz.000001``."""
    raw = str(ts_code).strip().upper()
    if "." not in raw:
        parsed = normalize_to_baostock(raw)
        if parsed is None:
            raise ValueError(f"无法转换为 baostock 股票代码: {ts_code}")
        return parsed
    number, exchange = raw.split(".", 1)
    return f"{exchange.lower()}.{number}"


def _csv_stem(code: str) -> str:
    return normalize_to_baostock(code).replace(".", "")  # type: ignore[union-attr]


def _to_tushare_date(date_str: str) -> str:
    return pd.to_datetime(date_str).strftime("%Y%m%d")


def _next_date_str(date_str: str) -> str:
    return (pd.to_datetime(date_str) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


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


def _get_tushare_client(token: str | None = None) -> Any:
    resolved_token = token or os.getenv("TUSHARE_TOKEN")
    if not resolved_token:
        raise ValueError("未提供 Tushare token。请设置 TUSHARE_TOKEN 或传入 --token。")
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("未安装 tushare，请先安装依赖: pip install tushare") from exc
    return ts.pro_api(resolved_token)


def _query_trade_dates(
    client: Any,
    start_date: str,
    end_date: str,
) -> set[str] | None:
    """Return open trading dates in ``YYYY-MM-DD`` format, or None on probe failure."""
    if start_date > end_date:
        return set()
    try:
        calendar = client.trade_cal(
            exchange="",
            start_date=_to_tushare_date(start_date),
            end_date=_to_tushare_date(end_date),
        )
    except Exception as exc:  # noqa: BLE001 - fail open for data freshness
        logger.warning(f"Tushare 查询交易日失败: {exc}，将回退为逐股票行情查询")
        return None

    if calendar is None or calendar.empty:
        return set()
    if "cal_date" not in calendar.columns or "is_open" not in calendar.columns:
        logger.warning("Tushare 交易日结果缺少必要字段，将回退为逐股票行情查询")
        return None

    is_open = pd.to_numeric(calendar["is_open"], errors="coerce").fillna(0)
    dates = pd.to_datetime(
        calendar.loc[is_open == 1, "cal_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    ).dropna()
    return set(dates.dt.strftime("%Y-%m-%d"))


def _has_trading_day(
    trading_dates: set[str] | None,
    start_date: str,
    end_date: str,
) -> bool:
    if trading_dates is None:
        return True
    return any(start_date <= trade_date <= end_date for trade_date in trading_dates)


def _normalize_daily_frame(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """Convert Tushare daily bars to the existing AlphaPilot CSV schema."""
    if df is None or df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    code_clean = _csv_stem(code)
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(
        df["trade_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    out["code"] = code_clean
    out["open"] = pd.to_numeric(df.get("open"), errors="coerce")
    out["high"] = pd.to_numeric(df.get("high"), errors="coerce")
    out["low"] = pd.to_numeric(df.get("low"), errors="coerce")
    out["close"] = pd.to_numeric(df.get("close"), errors="coerce")
    out["preclose"] = pd.to_numeric(df.get("pre_close"), errors="coerce")
    out["volume"] = pd.to_numeric(df.get("vol"), errors="coerce")
    out["amount"] = pd.to_numeric(df.get("amount"), errors="coerce")
    out["turn"] = pd.NA
    out["tradestatus"] = 1
    out["pctChg"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")
    out["peTTM"] = pd.NA
    out["pbMRQ"] = pd.NA
    out["psTTM"] = pd.NA
    out["pcfNcfTTM"] = pd.NA
    out["isST"] = pd.NA
    out = out.dropna(subset=["date"])
    out = out.sort_values("date")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out[PRICE_COLUMNS]


def _normalize_factor_frame(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """Convert Tushare adj_factor rows to columns used by ``apply_adjust``."""
    if df is None or df.empty:
        return pd.DataFrame(columns=FACTOR_COLUMNS)

    code_clean = _csv_stem(code)
    out = pd.DataFrame()
    out["code"] = code_clean
    out["dividOperateDate"] = pd.to_datetime(
        df["trade_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    out["adjustFactor"] = pd.to_numeric(df.get("adj_factor"), errors="coerce")
    out = out.dropna(subset=["dividOperateDate", "adjustFactor"])
    if out.empty:
        return pd.DataFrame(columns=FACTOR_COLUMNS)

    out = out.sort_values("dividOperateDate")
    latest_factor = out["adjustFactor"].iloc[-1]
    if pd.isna(latest_factor) or latest_factor == 0:
        latest_factor = 1.0
    out["foreAdjustFactor"] = out["adjustFactor"] / latest_factor
    out["backAdjustFactor"] = out["adjustFactor"]
    out["dividOperateDate"] = out["dividOperateDate"].dt.strftime("%Y-%m-%d")
    return out[FACTOR_COLUMNS]


def _normalize_daily_basic_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Map Tushare ``daily_basic`` rows to price-CSV columns, keyed by ``date``."""
    columns = ["date", *DAILY_BASIC_COLUMN_MAP.values()]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(
        df["trade_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    for src, dst in DAILY_BASIC_COLUMN_MAP.items():
        out[dst] = pd.to_numeric(df.get(src), errors="coerce")
    out = out.dropna(subset=["date"])
    if out.empty:
        return pd.DataFrame(columns=columns)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.drop_duplicates(subset=["date"], keep="last")
    return out[columns]


def _apply_daily_basic(price_df: pd.DataFrame, basic_df: pd.DataFrame) -> pd.DataFrame:
    """Fill ``turn``/``peTTM``/``pbMRQ``/``psTTM`` in *price_df* from daily_basic.

    Values are merged by ``date``; existing non-null values are kept where the
    daily_basic frame has no row for that date (so a narrower fetch never wipes
    previously-saved indicators).
    """
    if basic_df is None or basic_df.empty:
        return price_df
    indexed = basic_df.set_index("date")
    for dst in DAILY_BASIC_COLUMN_MAP.values():
        if dst not in indexed.columns:
            continue
        mapped = price_df["date"].map(indexed[dst])
        existing = pd.to_numeric(price_df.get(dst), errors="coerce")
        price_df[dst] = mapped.combine_first(existing)
    return price_df


def _attach_factor_column(
    price_df: pd.DataFrame, factor_df: pd.DataFrame, mode: str
) -> pd.DataFrame:
    """为已复权的行情逐交易日附加 ``factor`` 列（与复权所用因子一致）。

    - forward (qfq): ``foreAdjustFactor`` = adj_factor / 最新 adj_factor
    - backward (hfq): ``backAdjustFactor`` = adj_factor
    """
    if price_df.empty:
        return price_df
    if factor_df is None or factor_df.empty:
        price_df["factor"] = 1.0
        return price_df

    if mode == "backward":
        col, before_first_ex = "backAdjustFactor", "unit"
    else:
        col, before_first_ex = "foreAdjustFactor", "latest"

    dates = pd.DatetimeIndex(pd.to_datetime(price_df["date"], errors="coerce"))
    factors = lookup_factor_for_dates(
        dates, factor_df, col, before_first_ex=before_first_ex
    )
    price_df["factor"] = factors.values
    return price_df


def _merge_price_csv(output_file: Path, new_df: pd.DataFrame) -> pd.DataFrame:
    if output_file.exists():
        existing_df = pd.read_csv(output_file)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df["date"] = pd.to_datetime(combined_df["date"], errors="coerce")
        combined_df = combined_df.dropna(subset=["date"])
        combined_df = combined_df.drop_duplicates(subset=["date", "code"], keep="last")
        combined_df = combined_df.sort_values("date")
    else:
        combined_df = new_df.copy()
        combined_df["date"] = pd.to_datetime(combined_df["date"], errors="coerce")
        combined_df = combined_df.dropna(subset=["date"]).sort_values("date")

    combined_df["date"] = combined_df["date"].dt.strftime("%Y-%m-%d")
    for column in PRICE_COLUMNS:
        if column not in combined_df.columns:
            combined_df[column] = pd.NA
    return combined_df[PRICE_COLUMNS]


def _merge_factor_csv(factor_file: Path, new_factor_df: pd.DataFrame) -> pd.DataFrame:
    if factor_file.exists():
        existing_df = pd.read_csv(factor_file)
        combined_df = pd.concat([existing_df, new_factor_df], ignore_index=True)
    else:
        combined_df = new_factor_df.copy()

    if combined_df.empty:
        return pd.DataFrame(columns=FACTOR_COLUMNS)
    combined_df["dividOperateDate"] = pd.to_datetime(
        combined_df["dividOperateDate"], errors="coerce"
    )
    combined_df["adjustFactor"] = pd.to_numeric(
        combined_df["adjustFactor"], errors="coerce"
    )
    combined_df = combined_df.dropna(subset=["dividOperateDate", "adjustFactor"])
    combined_df = combined_df.drop_duplicates(subset=["dividOperateDate"], keep="last")
    combined_df = combined_df.sort_values("dividOperateDate")
    latest_factor = (
        combined_df["adjustFactor"].iloc[-1] if not combined_df.empty else 1.0
    )
    if pd.isna(latest_factor) or latest_factor == 0:
        latest_factor = 1.0
    combined_df["foreAdjustFactor"] = combined_df["adjustFactor"] / latest_factor
    combined_df["backAdjustFactor"] = combined_df["adjustFactor"]
    combined_df["dividOperateDate"] = combined_df["dividOperateDate"].dt.strftime(
        "%Y-%m-%d"
    )
    for column in FACTOR_COLUMNS:
        if column not in combined_df.columns:
            combined_df[column] = pd.NA
    return combined_df[FACTOR_COLUMNS]


def _get_all_tushare_stocks(client: Any) -> list[str]:
    stock_df = client.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code",
    )
    if stock_df is None or stock_df.empty or "ts_code" not in stock_df.columns:
        raise ValueError("Tushare stock_basic 未返回有效 ts_code")
    codes = [tushare_to_baostock(value) for value in stock_df["ts_code"].dropna()]
    return list(dict.fromkeys(codes))


def _download_tushare_factor_only(
    client: Any,
    code: str,
    factor_path: Path,
    start_date: str,
    end_date: str,
) -> bool:
    ts_code = baostock_to_tushare(code)
    adj_df = client.adj_factor(
        ts_code=ts_code,
        start_date=_to_tushare_date(start_date),
        end_date=_to_tushare_date(end_date),
    )
    new_factor_df = _normalize_factor_frame(adj_df, code)
    factor_file = factor_path / f"{_csv_stem(code)}.csv"
    combined_factor_df = _merge_factor_csv(factor_file, new_factor_df)
    combined_factor_df.to_csv(factor_file, index=False, encoding="utf-8")
    return not combined_factor_df.empty


def _parallel_tushare_factor_worker(
    codes: list[str],
    start_date: str,
    end_date: str,
    factor_dir: str,
    token: str | None,
    result_queue: Any,
) -> None:
    stats = _TushareDownloadStats()
    try:
        client = _get_tushare_client(token)
        factor_path = Path(factor_dir).expanduser()
        factor_path.mkdir(parents=True, exist_ok=True)
        for code in tqdm(codes, desc="Tushare复权因子"):
            try:
                if _download_tushare_factor_only(
                    client, code, factor_path, start_date, end_date
                ):
                    stats.incr("factor_updated")
            except Exception as exc:  # noqa: BLE001
                stats.incr("errors")
                logger.warning(f"Tushare 并行下载 {code} 复权因子失败: {exc}")
        result_queue.put(
            {"factor_updated": stats.factor_updated, "errors": stats.errors}
        )
    except BaseException as exc:  # noqa: BLE001
        result_queue.put({"error": f"{type(exc).__name__}: {exc}"})
        raise


def _start_parallel_tushare_factor_process(
    codes: list[str],
    start_date: str,
    end_date: str,
    factor_dir: Path,
    token: str | None,
) -> tuple[Any, Any]:
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_parallel_tushare_factor_worker,
        args=(codes, start_date, end_date, str(factor_dir), token, result_queue),
        daemon=False,
    )
    process.start()
    return process, result_queue


def _finish_parallel_tushare_factor_process(
    process: Any, result_queue: Any
) -> dict[str, Any]:
    process.join()
    result: dict[str, Any] = {}
    try:
        result = result_queue.get_nowait()
    except queue.Empty:
        result = {}
    if result.get("error"):
        raise RuntimeError(f"Tushare 并行复权因子下载失败: {result['error']}")
    if getattr(process, "exitcode", 0) not in (0, None):
        raise RuntimeError(f"Tushare 并行复权因子下载进程异常退出: exitcode={process.exitcode}")
    return result


def _query_daily_bars(
    client: Any,
    ts_code: str,
    start_date: str,
    end_date: str,
    mode: AdjustMode,
) -> pd.DataFrame:
    """Query Tushare daily bars, using pro_bar for adjusted downloads."""
    if mode == "none":
        return client.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    adj = _TUSHARE_ADJ_BY_MODE[mode]
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("未安装 tushare，无法调用 pro_bar 下载复权行情。") from exc

    return ts.pro_bar(
        ts_code=ts_code,
        api=client,
        start_date=start_date,
        end_date=end_date,
        adj=adj,
        freq="D",
        asset="E",
    )


def download_tushare_data(
    start_date: str,
    end_date: str,
    output_dir: str | Path,
    stock_csv_path: str | Path | None = None,
    code_column: str | None = None,
    all_market: bool = False,
    max_workers: int = DEFAULT_TUSHARE_WORKERS,
    adjust_mode: str = "none",
    factor_dir: str | Path | None = None,
    symbols: list[str] | None = None,
    download_state_path: str | Path | None = None,
    token: str | None = None,
    include_daily_basic: bool = False,
    client: Any | None = None,
    parallel_price_factor: bool = False,
) -> list[str]:
    """
    Download Tushare daily bars into AlphaPilot-compatible per-symbol CSV files.

    ``adjust_mode=none`` writes unadjusted daily bars and Tushare ``adj_factor``
    rows. ``forward`` / ``backward`` write adjusted bars directly via Tushare
    ``pro_bar`` (qfq / hfq), matching the baostock download semantics.

    Tushare ``adj_factor`` is downloaded and saved to ``factor_dir`` for *all*
    modes. In ``forward`` / ``backward`` mode the matching per-day factor is also
    written into a ``factor`` column on the price CSV, mirroring the column added
    when ``none`` bars are adjusted offline (see ``adjust_prices``).

    ``include_daily_basic=True`` additionally pulls Tushare ``daily_basic``
    (每日指标, requires the 2000-point tier) and fills the ``turn`` / ``peTTM`` /
    ``pbMRQ`` / ``psTTM`` columns in the same per-symbol price CSV. Accounts
    without enough points degrade gracefully: a warning is logged per symbol and
    price/factor data are still written.
    """
    mode = normalize_adjust_mode(adjust_mode)
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)
    # 因子数据与复权模式无关：none / forward / backward 都下载并保存除权因子，
    # 以便复权行情也能附带 factor 列、且不复权行情可在后续离线复权时复用。
    factor_path = resolve_tushare_factor_dir(factor_dir)
    factor_path.mkdir(parents=True, exist_ok=True)
    parallel_factors_enabled = bool(parallel_price_factor and mode == "none")
    if parallel_price_factor and not parallel_factors_enabled:
        logger.info("parallel_price_factor 仅在 adjust_mode=none 时生效，当前保持原下载流程。")
    state_path = resolve_download_state_path(download_state_path, output_path)
    state_store = DownloadStateStore(state_path)
    pro = client or _get_tushare_client(token)

    if max_workers != 1:
        logger.warning(f"Tushare 下载默认按单线程执行以避免限流，已忽略 max_workers={max_workers}")
        max_workers = 1

    if symbols:
        all_stocks = [c for c in (normalize_to_baostock(s) for s in symbols) if c]
        if not all_stocks:
            raise ValueError(f"未从 symbols 解析到有效股票代码: {symbols}")
    elif all_market:
        all_stocks = _get_all_tushare_stocks(pro)
    elif stock_csv_path:
        all_stocks = load_stocks_from_file(stock_csv_path, code_column=code_column)
    else:
        all_stocks = _get_all_tushare_stocks(pro)

    stats = _TushareDownloadStats()
    download_starts: dict[str, str | None] = {}
    for code in all_stocks:
        output_file = output_path / f"{_csv_stem(code)}.csv"
        state = state_store.get(
            source=TUSHARE_SOURCE,
            adjust_mode=mode,
            code=code,
            raw_dir=output_path,
        )
        if state is None:
            last_date = _read_price_csv_last_date(output_file)
            if last_date is not None:
                last_date_str = last_date.strftime("%Y-%m-%d")
                state = state_store.upsert(
                    source=TUSHARE_SOURCE,
                    adjust_mode=mode,
                    code=code,
                    raw_dir=output_path,
                    data_end_date=last_date_str,
                    checked_until=last_date_str,
                    last_status="bootstrap",
                    last_error="",
                )

        checked_until = state.checked_until or state.data_end_date if state else None
        if checked_until is not None:
            if checked_until >= end_date:
                stats.incr("skipped_up_to_date")
                download_starts[code] = None
            else:
                download_starts[code] = _next_date_str(checked_until)
        else:
            download_starts[code] = start_date

    try:
        active_starts = [
            date
            for date in download_starts.values()
            if date is not None and date <= end_date
        ]
        trading_dates: set[str] | None = None
        if active_starts:
            trading_dates = _query_trade_dates(pro, min(active_starts), end_date)
            logger.info(f"Tushare 下载状态表: {state_path}")
        factor_process = factor_queue = None
        if parallel_factors_enabled and active_starts:
            logger.info("启用 Tushare 并行下载: 行情 CSV 与复权因子将在独立进程中同时执行。")
            active_codes = [
                code
                for code, start in download_starts.items()
                if start is not None and start <= end_date
            ]
            factor_process, factor_queue = _start_parallel_tushare_factor_process(
                active_codes,
                start_date,
                end_date,
                factor_path,
                token,
            )

        def download_single_stock(code: str) -> None:
            start = download_starts.get(code)
            if start is None or start > end_date:
                return

            output_file = output_path / f"{_csv_stem(code)}.csv"
            factor_file = (
                factor_path / f"{_csv_stem(code)}.csv"
                if factor_path and not parallel_factors_enabled
                else None
            )

            if not _has_trading_day(trading_dates, start, end_date):
                state_store.upsert(
                    source=TUSHARE_SOURCE,
                    adjust_mode=mode,
                    code=code,
                    raw_dir=output_path,
                    checked_until=end_date,
                    last_status="no_trading_days",
                    last_error="",
                    mark_success=True,
                )
                stats.incr("skipped_no_trading_days")
                return

            ts_code = baostock_to_tushare(code)
            try:
                daily_df = _query_daily_bars(
                    pro,
                    ts_code=ts_code,
                    start_date=_to_tushare_date(start),
                    end_date=_to_tushare_date(end_date),
                    mode=mode,
                )
                adj_df = None
                if factor_file is not None or mode != "none":
                    adj_df = pro.adj_factor(
                        ts_code=ts_code,
                        start_date=_to_tushare_date(start_date),
                        end_date=_to_tushare_date(end_date),
                    )
            except Exception as exc:  # noqa: BLE001 - record API failures per symbol
                logger.warning(f"Tushare 获取 {code} 失败: {exc}")
                state_store.upsert(
                    source=TUSHARE_SOURCE,
                    adjust_mode=mode,
                    code=code,
                    raw_dir=output_path,
                    last_status="error",
                    last_error=str(exc),
                )
                stats.incr("errors")
                return

            new_df = _normalize_daily_frame(daily_df, code)
            if new_df.empty:
                state_store.upsert(
                    source=TUSHARE_SOURCE,
                    adjust_mode=mode,
                    code=code,
                    raw_dir=output_path,
                    checked_until=end_date,
                    last_status="empty",
                    last_error="",
                    mark_success=True,
                )
                stats.incr("empty")
                return

            combined_factor_df: pd.DataFrame | None = None
            if factor_file is not None:
                new_factor_df = _normalize_factor_frame(adj_df, code)
                combined_factor_df = _merge_factor_csv(factor_file, new_factor_df)
                combined_factor_df.to_csv(factor_file, index=False, encoding="utf-8")
                stats.incr("factor_updated")

            combined_df = _merge_price_csv(output_file, new_df)

            if include_daily_basic:
                # daily_basic needs the 2000-point tier; fetch it separately so a
                # permission/quota error never aborts the price+factor download.
                # Pulled over the full [start_date, end_date] window (like
                # adj_factor) so existing rows get backfilled in incremental runs.
                try:
                    basic_df = pro.daily_basic(
                        ts_code=ts_code,
                        start_date=_to_tushare_date(start_date),
                        end_date=_to_tushare_date(end_date),
                        fields=DAILY_BASIC_FIELDS,
                    )
                except Exception as exc:  # noqa: BLE001 - degrade without points
                    logger.warning(
                        f"Tushare daily_basic 获取 {code} 失败（需 2000 积分）: {exc}"
                    )
                    basic_df = None
                    stats.incr("basic_failed")

                normalized_basic = _normalize_daily_basic_frame(basic_df)
                if not normalized_basic.empty:
                    combined_df = _apply_daily_basic(combined_df, normalized_basic)
                    stats.incr("basic_updated")

            if mode != "none":
                # pro_bar 已返回复权价，这里把对应的复权因子一并写入 factor 列，
                # 与不复权行情后续离线复权生成的 factor 列保持一致。
                combined_df = _attach_factor_column(
                    combined_df, combined_factor_df, mode
                )

            combined_df.to_csv(output_file, index=False, encoding="utf-8")
            stats.incr("price_updated")
            data_end_date = pd.to_datetime(combined_df["date"], errors="coerce").max()
            state_store.upsert(
                source=TUSHARE_SOURCE,
                adjust_mode=mode,
                code=code,
                raw_dir=output_path,
                data_end_date=data_end_date.strftime("%Y-%m-%d"),
                checked_until=end_date,
                last_status="updated",
                last_error="",
                mark_success=True,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(download_single_stock, code) for code in all_stocks
            ]
            for future in tqdm(
                as_completed(futures), total=len(futures), desc="Tushare下载"
            ):
                future.result()

        if factor_process is not None:
            factor_result = _finish_parallel_tushare_factor_process(
                factor_process, factor_queue
            )
            stats.incr("factor_updated", int(factor_result.get("factor_updated", 0)))
            stats.incr("errors", int(factor_result.get("errors", 0)))

        basic_summary = (
            f"每日指标更新={stats.basic_updated}, 每日指标失败={stats.basic_failed}, "
            if include_daily_basic
            else ""
        )
        logger.info(
            "Tushare 下载统计: "
            f"跳过(已最新)={stats.skipped_up_to_date}, "
            f"跳过(无交易日)={stats.skipped_no_trading_days}, "
            f"补行情={stats.price_updated}, "
            f"因子更新={stats.factor_updated}, "
            f"{basic_summary}"
            f"空结果={stats.empty}, "
            f"错误={stats.errors}"
        )
    finally:
        state_store.save()

    return all_stocks


def download_cn_data(
    start_date: str = "2016-12-31",
    end_date: str | None = None,
    data_dir: str | Path | None = None,
    stock_csv: str | Path | None = None,
    code_column: str | None = None,
    all_market: bool = False,
    max_workers: int = DEFAULT_TUSHARE_WORKERS,
    adjust_mode: str = "none",
    factor_dir: str | Path | None = None,
    symbols: list[str] | None = None,
    download_state_path: str | Path | None = None,
    token: str | None = None,
    include_daily_basic: bool = False,
    client: Any | None = None,
    parallel_price_factor: bool = False,
) -> list[str]:
    """Tushare-flavoured CN data downloader with the same shape as prepare_cn."""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    mode = normalize_adjust_mode(adjust_mode)
    raw_dir = resolve_tushare_raw_dir(data_dir, mode)
    logger.info(f"开始下载 Tushare A 股数据 ({mode}): {start_date} ~ {end_date} -> {raw_dir}")
    if mode != "none":
        logger.info(f"Tushare 复权模式: {_TUSHARE_ADJ_BY_MODE[mode]} (pro_bar)")
    logger.info(f"Tushare 复权因子目录: {resolve_tushare_factor_dir(factor_dir)}")
    if include_daily_basic:
        logger.info("已启用 daily_basic（每日指标，需 2000 积分）: 将填充 turn/peTTM/pbMRQ/psTTM")
    codes = download_tushare_data(
        start_date=start_date,
        end_date=end_date,
        output_dir=raw_dir,
        stock_csv_path=stock_csv,
        code_column=code_column,
        all_market=all_market,
        max_workers=max_workers,
        adjust_mode=mode,
        factor_dir=factor_dir,
        symbols=symbols,
        download_state_path=download_state_path,
        token=token,
        include_daily_basic=include_daily_basic,
        client=client,
        parallel_price_factor=parallel_price_factor,
    )
    logger.info("Tushare CSV 下载完成。")
    return codes
