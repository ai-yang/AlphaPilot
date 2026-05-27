"""Export Qlib price-volume features to daily_pv h5 for factor calculation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import qlib
from qlib.data import D

from alphaagent.app.data.prepare_cn import DEFAULT_STOCK_CSV
from alphaagent.app.data.stock_list import default_market_name
from alphaagent.log import logger

DEFAULT_QLIB_DIR = Path("~/.qlib/qlib_data/cn_data")
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "scenarios"
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
) -> None:
    """Write daily_pv_all.h5 and daily_pv_debug.h5 under *output_dir*."""
    qlib_dir = str(Path(qlib_dir).expanduser())
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = fields or list(DEFAULT_FIELDS)

    qlib.init(provider_uri=qlib_dir)
    instruments = D.instruments(market=market)
    logger.info(f"从 Qlib 导出价量数据: market={market}, fields={fields}")

    data = D.features(instruments, fields, freq="day").swaplevel().sort_index().loc[start_date:].sort_index()
    data["$return"] = data.groupby(level=0)["$close"].pct_change().fillna(0)
    logger.info(f"daily_pv_all 形状: {data.shape}")
    data.to_hdf(output_dir / "daily_pv_all.h5", key="data")

    debug_instruments = data.reset_index()["instrument"].unique()[:debug_stock_count]
    debug_data = (
        D.features(instruments, fields, freq="day")
        .swaplevel()
        .sort_index()
        .swaplevel()
        .loc[debug_instruments]
        .swaplevel()
        .sort_index()
        .loc[start_date:]
        .sort_index()
    )
    debug_data["$return"] = debug_data.groupby(level=0)["$close"].pct_change().fillna(0)
    logger.info(f"daily_pv_debug 形状: {debug_data.shape}")
    debug_data.to_hdf(output_dir / "daily_pv_debug.h5", key="data")
    logger.info(f"h5 已写入: {output_dir}")
