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


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


@DATA_SOURCE_REGISTRY.register("baostock_cn", is_default=True)
class BaostockDataSourceAdapter(BaseDataSourceAdapter):
    """Download A-share daily CSV via baostock."""

    def download(self, request: DataDownloadRequest) -> DataDownloadResult:
        from alphapilot.systems.data.prepare_cn import (
            download_cn_data,
            resolve_raw_dir,
        )
        from alphapilot.systems.data.frequency import get_frequency

        options: dict[str, Any] = dict(request.options)
        spec = get_frequency(options.pop("freq", "day"))
        if spec.is_intraday:
            return self._download_minute(request, options, spec)

        adjust_mode = options.pop("adjust_mode", "backward")
        stock_csv = options.pop("stock_csv", None)
        code_column = options.pop("code_column", None)
        # Only fall back to whole-market when no explicit symbols/CSV were given.
        all_market = options.pop(
            "all_market", request.symbols is None and stock_csv is None
        )
        max_workers = options.pop("max_workers", 1)
        factor_dir = options.pop("factor_dir", None)
        download_state_path = options.pop("download_state_path", None)
        parallel_price_factor = _parse_bool(options.pop("parallel_price_factor", False))

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
            symbols=request.symbols,
            download_state_path=download_state_path,
            parallel_price_factor=parallel_price_factor,
        )
        return DataDownloadResult(
            output_dir=Path(raw_dir),
            symbols=codes,
            extra={"adjust_mode": adjust_mode},
        )

    def _download_minute(
        self,
        request: DataDownloadRequest,
        options: dict[str, Any],
        spec: Any,
    ) -> DataDownloadResult:
        """Intraday branch: download minute bars via the minute pipeline."""
        from alphapilot.systems.data.data_paths import baostock_minute_raw_dir
        from alphapilot.systems.data.prepare_cn_minute import download_cn_minute_data

        adjust_mode = options.pop("adjust_mode", "backward")
        stock_csv = options.pop("stock_csv", None)
        code_column = options.pop("code_column", None)
        max_workers = options.pop("max_workers", 1)
        download_state_path = options.pop("download_state_path", None)

        raw_dir = (
            Path(request.output_dir).expanduser()
            if request.output_dir is not None
            else baostock_minute_raw_dir(spec.key)
        )

        codes = download_cn_minute_data(
            start_date=request.start_date,
            end_date=request.end_date,
            freq=spec.key,
            data_dir=raw_dir,
            stock_csv=stock_csv,
            code_column=code_column,
            symbols=request.symbols,
            adjust_mode=adjust_mode,
            max_workers=max_workers,
            download_state_path=download_state_path,
        )
        return DataDownloadResult(
            output_dir=Path(raw_dir),
            symbols=codes,
            extra={"adjust_mode": adjust_mode, "freq": spec.key},
        )

    def default_output_dir(self) -> Path:
        from alphapilot.systems.data.prepare_cn import default_raw_dir

        return default_raw_dir("backward")
