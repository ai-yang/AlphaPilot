"""Load stock universes from CSV/TXT and sync Qlib instrument files."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from alphapilot.kernel.paths import remap_legacy_relative_path
from alphapilot.log import logger

# Column names tried when --code_column is not set (first match wins).
CODE_COLUMN_CANDIDATES = (
    "ts_code",
    "code",
    "symbol",
    "stock_code",
    "ticker",
    "股票代码",
    "证券代码",
)

_EXCHANGE_SUFFIX = frozenset({"SH", "SZ", "BJ"})
_BAOSTOCK_PREFIX = frozenset({"sh", "sz", "bj"})


def _is_blank(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    return str(value).strip() == ""


def infer_exchange_from_code(code: str) -> str:
    """Infer baostock exchange prefix from a 6-digit (or longer) numeric code."""
    code = re.sub(r"\D", "", str(code))
    if len(code) < 6:
        raise ValueError(f"无法识别交易所，代码位数不足: {code}")
    if code.startswith(("60", "68")):
        return "sh"
    if code.startswith(("00", "30")):
        return "sz"
    if code.startswith(("92", "83", "87", "43")):
        return "bj"
    raise ValueError(f"无法根据代码前缀推断交易所: {code}")


def normalize_to_baostock(code: str) -> str | None:
    """
    Normalize a single symbol to baostock format, e.g. ``sz.300001``.

    Supported inputs:
    - ``300001.SZ`` / ``688001.SH`` (tushare ts_code)
    - ``sz.300001`` / ``sh.600000`` (baostock)
    - ``SZ300001`` / ``SH600000`` (qlib instrument id)
    - ``300001`` (6-digit, exchange inferred)
  """
    if _is_blank(code):
        return None

    raw = str(code).strip().upper()
    # qlib: SH600000
    m = re.match(r"^(SH|SZ|BJ)(\d+)$", raw)
    if m:
        return f"{m.group(1).lower()}.{m.group(2)}"

    if "." in raw:
        left, right = raw.split(".", 1)
        left, right = left.strip(), right.strip()
        # 300001.SZ
        if right in _EXCHANGE_SUFFIX and left.isdigit():
            return f"{right.lower()}.{left}"
        # sz.300001
        if left.lower() in _BAOSTOCK_PREFIX:
            return f"{left.lower()}.{right}"

    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6:
        try:
            ex = infer_exchange_from_code(digits)
            return f"{ex}.{digits[:6]}"
        except ValueError:
            return None

    logger.warning(f"跳过无法解析的代码: {code}")
    return None


def baostock_to_qlib_instrument(baostock_code: str) -> str:
    """``sz.300001`` -> ``SZ300001``."""
    exchange, num = baostock_code.lower().split(".", 1)
    return f"{exchange.upper()}{num}"


def baostock_to_csv_stem(baostock_code: str) -> str:
    """``sz.300001`` -> ``sz300001`` (matches download CSV filename)."""
    return baostock_code.replace(".", "")


def infer_date_range_from_csv(csv_path: Path) -> tuple[str, str] | None:
    """Return ``(start, end)`` as ``YYYY-MM-DD`` from the ``date`` column, or ``None``."""
    if not csv_path.is_file():
        return None
    try:
        df = pd.read_csv(csv_path, usecols=["date"])
    except (ValueError, pd.errors.EmptyDataError, FileNotFoundError):
        return None
    if df.empty:
        return None
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")


def _detect_code_column(df: pd.DataFrame, code_column: str | None) -> str:
    if code_column:
        if code_column not in df.columns:
            raise ValueError(
                f"列 {code_column!r} 不存在。可用列: {list(df.columns)}"
            )
        return code_column
    for name in CODE_COLUMN_CANDIDATES:
        if name in df.columns:
            return name
    raise ValueError(
        "未找到股票代码列。请用 --code_column 指定，"
        f"或提供以下列名之一: {list(CODE_COLUMN_CANDIDATES)}。"
        f"当前列: {list(df.columns)}"
    )


def load_stocks_from_file(
    stock_file: str | Path,
    code_column: str | None = None,
) -> list[str]:
    """
    Load baostock codes from CSV or TXT.

    TXT: one symbol per line (``#`` 开头为注释).
    CSV: auto-detect code column or use *code_column*.
    """
    remapped = remap_legacy_relative_path(stock_file)
    path = Path(remapped if remapped is not None else stock_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"股票列表文件不存在: {path}")

    if path.suffix.lower() == ".txt":
        codes: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = normalize_to_baostock(line.split()[0])
            if parsed:
                codes.append(parsed)
    else:
        df = pd.read_csv(path)
        col = _detect_code_column(df, code_column)
        logger.info(f"从 {path.name} 读取列 {col!r}，共 {len(df)} 行")
        codes = []
        for value in df[col].dropna().unique():
            parsed = normalize_to_baostock(value)
            if parsed:
                codes.append(parsed)

    # dedupe preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    if not unique:
        raise ValueError(f"在 {path} 中未解析到任何有效股票代码")

    logger.info(f"有效股票 {len(unique)} 只（示例: {unique[:3]} ...）")
    return unique


def default_market_name(stock_file: str | Path | None) -> str:
    if stock_file is None:
        return "main_board"
    return Path(stock_file).expanduser().stem


def write_qlib_instruments(
    baostock_codes: list[str],
    qlib_dir: str | Path,
    market: str,
    start_date: str = "2016-12-31",
    end_date: str | None = None,
    data_dir: str | Path | None = None,
    keep_missing: bool = False,
) -> Path:
    """
    Write ``instruments/{market}.txt`` for Qlib ``D.instruments(market=...)``.

    When *data_dir* is set, each stock's start/end come from the first and last
    ``date`` in ``{data_dir}/{sz300001}.csv``. Stocks without a usable CSV are
    skipped, unless *keep_missing* is true, in which case they are written with
    the default *start_date* / *end_date* range. When *data_dir* is omitted, all
    stocks share *start_date* / *end_date*.
    """
    from datetime import datetime

    qlib_dir = Path(qlib_dir).expanduser()
    default_end = end_date or datetime.now().strftime("%Y-%m-%d")
    out = qlib_dir / "instruments" / f"{market}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)

    data_root = Path(data_dir).expanduser() if data_dir else None
    lines: list[str] = []
    skipped = 0

    for code in baostock_codes:
        inst_start, inst_end = start_date, default_end
        if data_root is not None:
            date_range = infer_date_range_from_csv(data_root / f"{baostock_to_csv_stem(code)}.csv")
            if date_range is None:
                skipped += 1
                if not keep_missing:
                    continue
            else:
                inst_start, inst_end = date_range

        lines.append(
            f"{baostock_to_qlib_instrument(code)}\t{inst_start}\t{inst_end}\n"
        )

    if not lines:
        raise ValueError(
            f"未生成任何 instruments 行（请求 {len(baostock_codes)} 只，"
            f"跳过 {skipped} 只无行情 CSV）。请确认 data_dir={data_root!r}"
        )

    out.write_text("".join(lines), encoding="utf-8")
    msg = f"已写入 Qlib 股票池 {market!r}: {out}（{len(lines)} 只）"
    if data_root is not None:
        action = "默认日期写入无数据" if keep_missing else "跳过无数据"
        msg += f"，按 CSV 起止日期；{action} {skipped} 只"
    logger.info(msg)
    return out
