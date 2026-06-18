"""Apply BaoStock adjust factors to unadjusted daily CSV bars."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from alphapilot.log import logger
from alphapilot.systems.data.prepare_cn import default_raw_dir, normalize_adjust_mode

_PRICE_COLS = ("open", "high", "low", "close", "preclose")


def _pick_factor_column(factor_df: pd.DataFrame, primary: str, fallback: str = "adjustFactor") -> str | None:
    """Return a factor column name, or None if the file has no usable factor rows."""
    for col in (primary, fallback, "backAdjustFactor", "foreAdjustFactor"):
        if col in factor_df.columns and pd.to_numeric(factor_df[col], errors="coerce").notna().any():
            return col
    return None


def _prepare_factor_events(factor_df: pd.DataFrame, factor_col: str) -> pd.DataFrame:
    events = factor_df[["dividOperateDate", factor_col]].copy()
    events["dividOperateDate"] = pd.to_datetime(events["dividOperateDate"], errors="coerce")
    events[factor_col] = pd.to_numeric(events[factor_col], errors="coerce")
    events = events.dropna(subset=["dividOperateDate", factor_col])
    events = events.sort_values("dividOperateDate")
    return events.drop_duplicates(subset=["dividOperateDate"], keep="last")


def lookup_factor_for_dates(
    trade_dates: pd.DatetimeIndex,
    factor_df: pd.DataFrame,
    factor_col: str,
    *,
    before_first_ex: str = "unit",
) -> pd.Series:
    """
    对每个交易日取 ``dividOperateDate <= 交易日`` 的最近一条复权因子（与 baostock 常用写法一致）。

    Args:
        before_first_ex: 早于首条除权日时的填充方式 —
            ``first`` 填首条除权因子（后复权，与 baostock/通达信一致）；
            ``unit`` 填 1.0；
            ``latest`` 填因子表最后一条（前复权参考实现常用）。
    """
    if factor_df.empty or "dividOperateDate" not in factor_df.columns:
        return pd.Series(1.0, index=trade_dates)

    events = _prepare_factor_events(factor_df, factor_col)
    if events.empty:
        return pd.Series(1.0, index=trade_dates)

    first_factor = float(events[factor_col].iloc[0])
    latest_factor = float(events[factor_col].iloc[-1])
    if first_factor == 0 or pd.isna(first_factor):
        first_factor = 1.0
    if latest_factor == 0 or pd.isna(latest_factor):
        latest_factor = 1.0
    if before_first_ex == "latest":
        fill_before = latest_factor
    elif before_first_ex == "first":
        fill_before = first_factor
    else:
        fill_before = 1.0

    bars = pd.DataFrame({"date": pd.DatetimeIndex(trade_dates)})
    merged = pd.merge_asof(
        bars.sort_values("date"),
        events.rename(columns={"dividOperateDate": "date"}),
        on="date",
        direction="backward",
    )
    factors = merged[factor_col].fillna(fill_before)
    return pd.Series(factors.values, index=trade_dates)


def lookup_factor_for_date_loop(
    trade_date: pd.Timestamp,
    factor_df: pd.DataFrame,
    factor_col: str,
    *,
    before_first_ex: str = "latest",
) -> float:
    """Reference implementation matching row-wise ``apply(get_factor_for_date)`` style."""
    events = _prepare_factor_events(factor_df, factor_col)
    if events.empty:
        return 1.0

    mask = events["dividOperateDate"] <= trade_date
    if mask.any():
        return float(events.loc[mask, factor_col].iloc[-1])

    if before_first_ex == "latest":
        return float(events[factor_col].iloc[-1])
    return 1.0


def apply_adjust_to_frame(
    price_df: pd.DataFrame,
    factor_df: pd.DataFrame,
    target_mode: str,
    price_cols: tuple[str, ...] = _PRICE_COLS,
    symbol: str | None = None,
) -> pd.DataFrame:
    """
    使用 BaoStock 涨跌幅复权因子调整 OHLC。

    - 前复权: ``复权价 = 未复权价 × foreAdjustFactor``（按交易日匹配因子）
    - 后复权: ``复权价 = 未复权价 × backAdjustFactor``（因子须含完整历史，见 refresh_factors）
    """
    mode = normalize_adjust_mode(target_mode)
    if mode == "none":
        raise ValueError("target_mode 不能为 none，请使用 forward 或 backward。")

    out = price_df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")
    if out.empty:
        return out

    dates = pd.DatetimeIndex(out["date"])

    if mode == "backward":
        col = _pick_factor_column(factor_df, "backAdjustFactor", "adjustFactor")
        # 早于上市/首条除权日填 1.0；因子文件须含完整历史（见 prepare_cn.FACTOR_HISTORY_START_DATE）
        before_first_ex = "unit"
    else:
        col = _pick_factor_column(factor_df, "foreAdjustFactor", "adjustFactor")
        before_first_ex = "latest"

    if col is None:
        code = symbol
        if not code and "code" in factor_df.columns and len(factor_df):
            code = str(factor_df["code"].iloc[0])
        logger.warning(
            f"复权因子无有效记录 ({code or 'unknown'})，按因子 1.0 处理（价格保持不变）"
        )
        factors = pd.Series(1.0, index=dates)
    else:
        factors = lookup_factor_for_dates(
            dates, factor_df, col, before_first_ex=before_first_ex
        )

    for c in price_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce") * factors.values

    out["factor"] = factors.values

    return out


def apply_adjust_directory(
    raw_dir: str | Path,
    factor_dir: str | Path,
    output_dir: str | Path,
    target_mode: str,
    max_workers: int = 4,
) -> int:
    """
    Convert all unadjusted CSV files under *raw_dir* to forward/backward adjusted CSVs.

    Returns the number of symbols written.
    """
    raw_path = Path(raw_dir).expanduser()
    factor_path = Path(factor_dir).expanduser()
    out_path = Path(output_dir).expanduser()
    out_path.mkdir(parents=True, exist_ok=True)

    mode = normalize_adjust_mode(target_mode)
    if mode == "none":
        raise ValueError("target_mode 须为 forward 或 backward。")

    logger.info(f"开始复权 ({mode}): {raw_path} -> {out_path}")

    csv_files = sorted(raw_path.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"未在 {raw_path} 找到除权 CSV 文件。")

    def _process_one(csv_file: Path) -> bool:
        factor_file = factor_path / csv_file.name
        if not factor_file.exists():
            logger.warning(f"跳过 {csv_file.name}: 缺少复权因子文件 {factor_file}")
            return False

        price_df = pd.read_csv(csv_file)
        if price_df.empty or "date" not in price_df.columns:
            logger.warning(f"跳过 {csv_file.name}: 行情为空或缺少 date 列")
            return False

        factor_df = pd.read_csv(factor_file)
        try:
            adjusted = apply_adjust_to_frame(
                price_df, factor_df, mode, symbol=csv_file.stem
            )
        except Exception as exc:
            logger.warning(f"跳过 {csv_file.name}: 复权失败 ({exc})")
            return False
        adjusted.to_csv(out_path / csv_file.name, index=False, encoding="utf-8")
        return True

    written = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one, f): f for f in csv_files}
        for fut in tqdm(as_completed(futures), total=len(futures), desc=f"复权({mode})"):
            if fut.result():
                written += 1

    logger.info(f"复权完成: {written}/{len(csv_files)} -> {out_path}")
    return written
