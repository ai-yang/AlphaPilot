"""Built-in data source adapter for Tushare A-share daily data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alphapilot.adapters.base import (
    BaseDataSourceAdapter,
    DataDownloadRequest,
    DataDownloadResult,
)
from alphapilot.adapters.registry import DATA_SOURCE_REGISTRY


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


@DATA_SOURCE_REGISTRY.register("tushare_cn")
class TushareDataSourceAdapter(BaseDataSourceAdapter):
    """Download A-share daily CSV via Tushare Pro."""

    def download(self, request: DataDownloadRequest) -> DataDownloadResult:
        from alphapilot.systems.data.prepare_tushare import (
            download_cn_data,
            resolve_tushare_raw_dir,
        )

        options: dict[str, Any] = dict(request.options)
        adjust_mode = options.pop("adjust_mode", "none")
        stock_csv = options.pop("stock_csv", None)
        code_column = options.pop("code_column", None)
        data_dir = options.pop("data_dir", None)
        all_market = options.pop(
            "all_market", request.symbols is None and stock_csv is None
        )
        max_workers = options.pop("max_workers", 1)
        factor_dir = options.pop("factor_dir", None)
        download_state_path = options.pop("download_state_path", None)
        token = options.pop("token", None)
        include_daily_basic = _parse_bool(options.pop("include_daily_basic", False))
        parallel_price_factor = _parse_bool(options.pop("parallel_price_factor", False))

        raw_dir = (
            Path(request.output_dir).expanduser()
            if request.output_dir is not None
            else resolve_tushare_raw_dir(data_dir, adjust_mode)
        )

        codes = download_cn_data(
            start_date=request.start_date,
            end_date=request.end_date,
            data_dir=raw_dir,
            stock_csv=stock_csv,
            code_column=code_column,
            all_market=all_market,
            max_workers=max_workers,
            adjust_mode=adjust_mode,
            factor_dir=factor_dir,
            symbols=request.symbols,
            download_state_path=download_state_path,
            token=token,
            include_daily_basic=include_daily_basic,
            parallel_price_factor=parallel_price_factor,
        )
        return DataDownloadResult(
            output_dir=Path(raw_dir),
            symbols=codes,
            extra={
                "adjust_mode": adjust_mode,
                "factor_dir": str(factor_dir) if factor_dir is not None else None,
            },
        )

    def default_output_dir(self) -> Path:
        from alphapilot.systems.data.prepare_tushare import default_tushare_raw_dir

        return default_tushare_raw_dir("none")
