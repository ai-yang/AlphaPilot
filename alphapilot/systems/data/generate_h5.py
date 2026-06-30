"""Export Qlib price-volume features to daily_pv h5 for factor calculation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import qlib
from qlib.data import D

from alphapilot.log import logger
from alphapilot.systems.data.prepare_cn import DEFAULT_STOCK_CSV
from alphapilot.systems.data.stock_list import default_market_name

from alphapilot.systems.data.data_paths import existing_baostock_qlib_dir

DEFAULT_QLIB_DIR = existing_baostock_qlib_dir()
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "modules"
    / "alpha_mining"
    / "qlib"
    / "experiment"
    / "factor_data_template"
)
DEFAULT_MARKET = default_market_name(DEFAULT_STOCK_CSV)
DEFAULT_FIELDS = ["$open", "$close", "$high", "$low", "$volume"]
DEFAULT_START = "2015-01-01"


def generate_daily_pv_h5(
    qlib_dir: str | Path = DEFAULT_QLIB_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    market: str = DEFAULT_MARKET,
    fields: list[str] | None = None,
    start_date: str = DEFAULT_START,
    debug_stock_count: int = 100,
    freq: str = "day",
) -> None:
    """Write price-volume h5 (all + debug) under *output_dir* for the given *freq*.

    ``freq`` selects the qlib bar frequency ("day" or intraday "5min"/...); the
    output filenames keep the ``daily_pv`` name regardless (content matches freq).
    """
    from alphapilot.systems.data.frequency import get_frequency

    qlib_freq = get_frequency(freq).qlib_freq
    qlib_dir = str(Path(qlib_dir).expanduser())
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = fields or list(DEFAULT_FIELDS)

    qlib.init(provider_uri=qlib_dir)
    instruments = D.instruments(market=market)
    logger.info(f"从 Qlib 导出价量数据: market={market}, fields={fields}, freq={qlib_freq}")

    # Index is (datetime, instrument) after swaplevel; ``$return`` must be the per-instrument
    # bar-over-bar change, so group by the ``instrument`` level (grouping by the datetime level
    # would compute a meaningless cross-sectional pct_change within a single timestamp).
    data = D.features(instruments, fields, freq=qlib_freq).swaplevel().sort_index().loc[start_date:].sort_index()
    data["$return"] = data.groupby(level="instrument")["$close"].pct_change().fillna(0)
    logger.info(f"daily_pv_all 形状: {data.shape}")
    data.to_hdf(output_dir / "daily_pv_all.h5", key="data")

    # Slice the debug subset straight from the full frame (keeps the already-correct ``$return``
    # and avoids a second, expensive ``D.features`` read).
    debug_instruments = data.index.get_level_values("instrument").unique()[:debug_stock_count]
    debug_data = data.loc[pd.IndexSlice[:, debug_instruments], :].sort_index()
    logger.info(f"daily_pv_debug 形状: {debug_data.shape}")
    debug_data.to_hdf(output_dir / "daily_pv_debug.h5", key="data")
    logger.info(f"h5 已写入: {output_dir}")
