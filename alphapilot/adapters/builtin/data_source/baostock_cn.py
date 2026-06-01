"""Built-in data source adapter that wraps the baostock A-share pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alphapilot.adapters.base import (
    BaseDataSourceAdapter,
    DataDownloadRequest,
    DataDownloadResult,
)
from alphapilot.adapters.registry import DATA_SOURCE_REGISTRY


@DATA_SOURCE_REGISTRY.register("baostock_cn", is_default=True)
class BaostockDataSourceAdapter(BaseDataSourceAdapter):
    """Download A-share daily CSV via baostock."""

    def download(self, request: DataDownloadRequest) -> DataDownloadResult:
        from alphapilot.systems.data.prepare_cn import (
            download_cn_data,
            resolve_raw_dir,
        )

        options: dict[str, Any] = dict(request.options)
        adjust_mode = options.pop("adjust_mode", "backward")
        stock_csv = options.pop("stock_csv", None)
        code_column = options.pop("code_column", None)
        all_market = options.pop("all_market", request.symbols is None and stock_csv is None)
        max_workers = options.pop("max_workers", 2)
        factor_dir = options.pop("factor_dir", None)

        raw_dir = (
            Path(request.output_dir).expanduser()
            if request.output_dir is not None
            else resolve_raw_dir(None, adjust_mode)
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
        )
        return DataDownloadResult(
            output_dir=Path(raw_dir),
            symbols=codes,
            extra={"adjust_mode": adjust_mode},
        )

    def default_output_dir(self) -> Path:
        from alphapilot.systems.data.prepare_cn import default_raw_dir

        return default_raw_dir("backward")
