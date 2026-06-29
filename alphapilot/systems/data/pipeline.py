"""Data-system owned orchestration helpers.

This module centralizes data preparation entrypoints under
``alphapilot.systems.data`` so ``QlibDataSystem`` stays thin.
"""

from __future__ import annotations

from typing import Any, Callable

try:
    from alphapilot.modules.portal.jobs import update_current_job_progress
except Exception:  # pragma: no cover - portal is optional for CLI data tools
    def update_current_job_progress(*_args, **_kwargs) -> None:  # type: ignore[no-redef]
        return None


def convert_data(**options: Any) -> Any:
    """Convert raw CSV to qlib binary via system-level PrepareDataCLI."""
    from alphapilot.systems.data.prepare_data import PrepareDataCLI

    update_current_job_progress(15, "convert:start", "开始转换 Qlib 数据")
    result = PrepareDataCLI().convert(**options)
    update_current_job_progress(95, "convert:done", "Qlib 数据转换完成")
    return result


def run_pipeline(**options: Any) -> Any:
    """Run download -> adjust -> convert data pipeline."""
    from alphapilot.systems.data.prepare_data import PrepareDataCLI

    update_current_job_progress(2, "pipeline:start", "启动数据流水线")
    result = PrepareDataCLI().pipeline(**options)
    update_current_job_progress(99, "pipeline:done", "数据流水线完成")
    return result


def load_universe(*, stock_csv: str | None = None, code_column: str | None = None) -> Any:
    """Load stock universe from CSV."""
    from alphapilot.systems.data.stock_list import load_stocks_from_file
    from alphapilot.systems.data.prepare_cn import DEFAULT_STOCK_CSV

    source = stock_csv or str(DEFAULT_STOCK_CSV)
    return load_stocks_from_file(source, code_column=code_column)


def dispatch_prepare_action(
    *,
    action: str,
    download_handler: Callable[..., Any],
    convert_handler: Callable[..., Any],
    pipeline_handler: Callable[..., Any],
    **options: Any,
) -> Any:
    """Legacy-compatible prepare_data action dispatcher owned by data system."""
    action = action.strip()

    start_date = options.pop("start_date", "2005-01-01")
    end_date = options.pop("end_date", None)
    stock_csv = options.pop("stock_csv", None)
    adjust_mode = options.pop("adjust_mode", "backward")
    market = options.pop("market", None)
    qlib_dir = options.pop("qlib_dir", None)
    output_dir = options.pop("output_dir", None)

    if action == "pipeline":
        kwargs: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "adjust_mode": adjust_mode,
        }
        kwargs.update(options)
        if stock_csv:
            kwargs["stock_csv"] = stock_csv
        return pipeline_handler(**kwargs)

    if action == "download":
        kwargs = {
            "start_date": start_date,
            "end_date": end_date,
            "adjust_mode": adjust_mode,
        }
        kwargs.update(options)
        if stock_csv:
            kwargs["stock_csv"] = stock_csv
        if output_dir:
            kwargs["output_dir"] = output_dir
        return download_handler(**kwargs)

    if action == "convert":
        kwargs = {"adjust_mode": adjust_mode}
        kwargs.update(options)
        if stock_csv:
            kwargs["stock_csv"] = stock_csv
        if qlib_dir:
            kwargs["qlib_dir"] = qlib_dir
        return convert_handler(**kwargs)

    if action in {"refresh_factors", "apply_adjust", "dump", "calendar"}:
        from alphapilot.systems.data.prepare_data import PrepareDataCLI

        cli = PrepareDataCLI()
        if not hasattr(cli, action):
            raise ValueError(f"Unsupported prepare_data action: {action!r}")

        kwargs = dict(options)
        # ``source`` is a download-time selector; these CLI actions (apply_adjust / refresh_factors
        # / dump / ...) operate on default/configured dirs and don't accept it. Drop it so a stray
        # value (e.g. from the portal form or a saved schedule) can't raise a TypeError.
        kwargs.pop("source", None)
        if stock_csv:
            kwargs["stock_csv"] = stock_csv
        if market:
            kwargs["market"] = market
        if qlib_dir:
            kwargs["qlib_dir"] = qlib_dir
        if output_dir:
            kwargs["output_dir"] = output_dir
        if action in {"apply_adjust", "download", "convert", "pipeline"}:
            kwargs["adjust_mode"] = adjust_mode
        if action in {"download", "pipeline"}:
            kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
        return getattr(cli, action)(**kwargs)

    raise ValueError(f"Unsupported prepare_data action: {action!r}")
