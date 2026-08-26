"""Signal (IC) engine with explicit coverage and holdout-boundary checks.

The engine reuses the normal factor-calculation path and scores each factor
cross-sectionally.  A configured Qlib label is preferred for sealed holdout
evaluation; the historical one-period close return remains available for
ordinary requests that do not provide ``single_ic_label_expression``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphapilot.log import logger
from alphapilot.systems.backtest.engines.base import EngineOutcome
from alphapilot.systems.backtest.types import SingleICCoverageOptions

#: Pseudo-factor name injected by the pipeline so the engine can build the label.
CLOSE_TASK_NAME = "__close__"
LEADERBOARD_FILE = "factor_ic_leaderboard.csv"


def make_close_task() -> Any:
    """Return the ``$close`` pseudo-factor used by the default label."""
    from alphapilot.components.coder.factor_coder.factor import FactorTask

    return FactorTask(
        factor_name=CLOSE_TASK_NAME,
        factor_description="",
        factor_formulation="",
        factor_expression="$close",
        variables="",
    )


def _safe_ratio(num: float, den: float) -> float:
    if den is None or not math.isfinite(den) or den == 0:
        return float("nan")
    return float(num / den)


def _validate_panel_index(index: pd.Index, *, owner: str) -> tuple[int, int]:
    """Validate a two-level panel and return datetime/instrument positions.

    Qlib normally names the levels ``datetime`` and ``instrument``, but older
    factor caches may use unnamed or application-specific names.  Preserve the
    historical positional fallback while still validating dates, instruments,
    dimensionality, and uniqueness.
    """
    if not isinstance(index, pd.MultiIndex):
        raise ValueError(f"{owner} index must be a two-level MultiIndex")
    if index.nlevels != 2:
        raise ValueError(
            f"{owner} index must have exactly two levels; got {index.nlevels}"
        )
    names = list(index.names)
    if "datetime" in names:
        datetime_position = names.index("datetime")
    elif "instrument" in names:
        datetime_position = 1 - names.index("instrument")
    else:
        datetime_position = 0
    if "instrument" in names:
        instrument_position = names.index("instrument")
    else:
        instrument_position = 1 - datetime_position
    if datetime_position == instrument_position:
        raise ValueError(f"{owner} index cannot resolve distinct panel levels")
    if not index.is_unique:
        duplicate_count = int(index.duplicated(keep=False).sum())
        raise ValueError(
            f"{owner} index must be unique; found {duplicate_count} duplicate rows"
        )
    datetimes = pd.to_datetime(
        index.get_level_values(datetime_position), errors="coerce"
    )
    if datetimes.isna().any():
        raise ValueError(f"{owner} index contains invalid datetime values")
    if pd.isna(index.get_level_values(instrument_position)).any():
        raise ValueError(f"{owner} index contains null instrument values")
    return datetime_position, instrument_position


def _canonical_panel_index(
    value: pd.DataFrame | pd.Series, *, owner: str
) -> pd.DataFrame | pd.Series:
    """Return a panel ordered and named as ``(datetime, instrument)``."""
    datetime_position, instrument_position = _validate_panel_index(
        value.index, owner=owner
    )
    result = value.copy()
    if (datetime_position, instrument_position) != (0, 1):
        result = result.reorder_levels([datetime_position, instrument_position])
    result.index = result.index.set_names(["datetime", "instrument"])
    return result


def compute_forward_return_label(close: pd.Series, inst_level: str | int) -> pd.Series:
    """Build ``close.shift(-2) / close.shift(-1) - 1`` for each instrument."""
    grouped = close.groupby(level=inst_level, sort=False)
    return grouped.shift(-2) / grouped.shift(-1) - 1.0


def _date_mask(index: pd.MultiIndex, start: Any, end: Any) -> np.ndarray:
    datetimes = pd.to_datetime(index.get_level_values("datetime"), errors="raise")
    mask = np.ones(len(index), dtype=bool)
    if start is not None:
        mask &= datetimes >= pd.Timestamp(start)
    if end is not None:
        end_ts = pd.Timestamp(end)
        # Date-only Qlib boundaries are inclusive of every intraday bar.
        if end_ts == end_ts.normalize():
            mask &= datetimes < end_ts + pd.Timedelta(days=1)
        else:
            mask &= datetimes <= end_ts
    return mask


def _normalise_bounds(start: Any, end: Any) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    start_ts = pd.Timestamp(start) if start is not None else None
    end_ts = pd.Timestamp(end) if end is not None else None
    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        raise ValueError(f"single_ic start date {start_ts} is after end date {end_ts}")
    return start_ts, end_ts


def _finite_numeric(series: pd.Series) -> tuple[pd.Series, int, int]:
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    values = numeric.to_numpy(dtype=float, copy=False)
    inf_count = int(np.isinf(values).sum())
    non_numeric_count = int((numeric.isna() & series.notna()).sum())
    numeric = numeric.mask(~np.isfinite(values))
    return numeric, inf_count, non_numeric_count


def _per_factor_ic(
    factor: pd.Series,
    label: pd.Series,
    *,
    dt_level: str | int,
    min_stocks_per_day: int,
    min_days: int,
    min_overlap_ratio: float,
) -> dict[str, Any]:
    factor, factor_inf, factor_non_numeric = _finite_numeric(factor)
    label, label_inf, label_non_numeric = _finite_numeric(label)
    pair = pd.concat([factor.rename("f"), label.rename("y")], axis=1)
    finite_label = int(pair["y"].notna().sum())
    pair = pair.dropna()
    observations = int(len(pair))
    overlap_ratio = observations / finite_label if finite_label else 0.0

    daily_counts = pair.groupby(level=dt_level, sort=True).size()
    eligible_dates = daily_counts[daily_counts >= min_stocks_per_day].index
    ic_values: list[float] = []
    rank_values: list[float] = []
    valid_periods: list[pd.Timestamp] = []
    for date in eligible_dates:
        group = pair.xs(date, level=dt_level, drop_level=False)
        ic = float(group["f"].corr(group["y"]))
        rank_ic = float(group["f"].corr(group["y"], method="spearman"))
        if math.isfinite(ic) and math.isfinite(rank_ic):
            ic_values.append(ic)
            rank_values.append(rank_ic)
            valid_periods.append(pd.Timestamp(date))

    ic_series = pd.Series(ic_values, dtype=float)
    rank_series = pd.Series(rank_values, dtype=float)
    n_periods = len(ic_values)
    n_days = int(pd.DatetimeIndex(valid_periods).normalize().nunique())
    observed_periods = pd.to_datetime(pair.index.get_level_values(dt_level))
    observed_days = int(pd.DatetimeIndex(observed_periods).normalize().nunique())
    eligible_days = int(
        pd.DatetimeIndex(pd.to_datetime(eligible_dates)).normalize().nunique()
    )
    errors: list[str] = []
    if finite_label == 0:
        errors.append("no_finite_label_rows")
    if overlap_ratio < min_overlap_ratio:
        errors.append("finite_overlap_below_minimum")
    if n_days < min_days:
        errors.append("valid_ic_days_below_minimum")
    coverage_valid = not errors

    if coverage_valid:
        ic_mean = float(ic_series.mean())
        rank_mean = float(rank_series.mean())
        icir = _safe_ratio(ic_mean, float(ic_series.std()))
        rank_icir = _safe_ratio(rank_mean, float(rank_series.std()))
    else:
        ic_mean = rank_mean = icir = rank_icir = float("nan")

    if observations:
        observed_dates = pd.to_datetime(pair.index.get_level_values(dt_level))
        coverage_start = observed_dates.min().isoformat()
        coverage_end = observed_dates.max().isoformat()
    else:
        coverage_start = coverage_end = ""
    return {
        "IC": ic_mean,
        "RankIC": rank_mean,
        "ICIR": icir,
        "RankICIR": rank_icir,
        "n_days": int(n_days),
        "n_periods": int(n_periods),
        "coverage_valid": coverage_valid,
        "coverage_error": ";".join(errors),
        "coverage_rows": observations,
        "coverage_label_rows": finite_label,
        "coverage_overlap_ratio": float(overlap_ratio),
        "coverage_days_observed": observed_days,
        "coverage_days_eligible": eligible_days,
        "coverage_periods_observed": int(len(daily_counts)),
        "coverage_periods_eligible": int(len(eligible_dates)),
        "coverage_min_stocks_per_day": int(min_stocks_per_day),
        "coverage_min_days": int(min_days),
        "coverage_min_overlap_ratio": float(min_overlap_ratio),
        "coverage_min_daily_stocks": (
            int(daily_counts.min()) if not daily_counts.empty else 0
        ),
        "coverage_median_daily_stocks": (
            float(daily_counts.median()) if not daily_counts.empty else 0.0
        ),
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "factor_inf_rows": factor_inf,
        "factor_non_numeric_rows": factor_non_numeric,
        "label_inf_rows": label_inf,
        "label_non_numeric_rows": label_non_numeric,
    }


def compute_factor_ic_table(
    factor_frame: pd.DataFrame,
    *,
    label: pd.Series | None = None,
    start: Any = None,
    end: Any = None,
    options: SingleICCoverageOptions | None = None,
) -> pd.DataFrame:
    """Compute signed IC metrics and explicit per-factor coverage diagnostics.

    Values outside ``[start, end]`` are never scored.  Infinite values are
    counted and excluded.  A factor that does not meet the requested finite
    overlap, cross-sectional size, or valid-day threshold is retained in the
    report with ``coverage_valid=False`` and NaN metrics, rather than silently
    receiving a misleading score.
    """
    if options is None:
        options = SingleICCoverageOptions()
    elif not isinstance(options, SingleICCoverageOptions):
        raise TypeError("options must be a SingleICCoverageOptions instance")
    if not factor_frame.columns.is_unique:
        raise ValueError("single_ic factor columns must be unique")
    factor_frame = _canonical_panel_index(
        factor_frame, owner="factor frame"
    )
    dt_level, inst_level = "datetime", "instrument"
    if label is None and CLOSE_TASK_NAME not in factor_frame.columns:
        raise ValueError(
            f"single_ic requires the '{CLOSE_TASK_NAME}' pseudo-factor column to build the label; "
            f"got columns {list(factor_frame.columns)}"
        )
    start_ts, end_ts = _normalise_bounds(start, end)
    factor_frame = factor_frame.loc[_date_mask(factor_frame.index, start_ts, end_ts)]
    if factor_frame.empty:
        raise ValueError(
            f"single_ic factor frame has no rows in requested range [{start_ts}, {end_ts}]"
        )

    if label is None:
        label = compute_forward_return_label(factor_frame[CLOSE_TASK_NAME], inst_level)
        structural_overlap = len(factor_frame.index)
        structural_label_rows = len(label.index)
        structural_ratio = 1.0
    else:
        if not isinstance(label, pd.Series):
            raise ValueError("single_ic label must be a pandas Series")
        label = _canonical_panel_index(label, owner="label")
        label = label.loc[_date_mask(label.index, start_ts, end_ts)]
        if label.empty:
            raise ValueError(
                f"single_ic label has no rows in requested range [{start_ts}, {end_ts}]"
            )
        structural_overlap = len(factor_frame.index.intersection(label.index))
        structural_label_rows = len(label.index)
        structural_ratio = structural_overlap / structural_label_rows
        if structural_overlap == 0:
            raise ValueError("single_ic factor frame and label have no overlapping index rows")
        if structural_ratio < options.min_overlap_ratio:
            raise ValueError(
                "single_ic structural index overlap is below minimum: "
                f"ratio={structural_ratio:.6f}, minimum={options.min_overlap_ratio:.6f}"
            )
        label = label.reindex(factor_frame.index)

    rows: list[dict[str, Any]] = []
    for col in factor_frame.columns:
        if col == CLOSE_TASK_NAME:
            continue
        row = {"factor_name": col}
        row.update(
            _per_factor_ic(
                factor_frame[col],
                label,
                dt_level=dt_level,
                min_stocks_per_day=options.min_stocks_per_day,
                min_days=options.min_days,
                min_overlap_ratio=options.min_overlap_ratio,
            )
        )
        row.update(
            {
                "coverage_index_rows": int(structural_overlap),
                "coverage_label_index_rows": int(structural_label_rows),
                "coverage_index_overlap_ratio": float(structural_ratio),
                "coverage_requested_start": start_ts.isoformat() if start_ts else "",
                "coverage_requested_end": end_ts.isoformat() if end_ts else "",
            }
        )
        rows.append(row)

    table = pd.DataFrame(rows)
    if not table.empty and not options.preserve_candidate_order:
        # Historical public behavior: strongest absolute IC first, including
        # predictive factors whose useful direction is negative.
        table = table.sort_values(
            "IC", ascending=False, key=lambda values: values.abs()
        )
    return table.reset_index(drop=True)


def _yaml_value(params: Any, key: str, default: Any = None) -> Any:
    if isinstance(params, dict):
        return params.get(key, default)
    return getattr(params, key, default) if params is not None else default


def _single_ic_options_from_params(params: Any) -> SingleICCoverageOptions:
    """Resolve a typed policy from Qlib params without changing public defaults."""
    value = _yaml_value(params, "single_ic_options")
    if isinstance(value, SingleICCoverageOptions):
        return value
    if isinstance(value, dict):
        return SingleICCoverageOptions(**value)
    if value is not None:
        raise TypeError("single_ic_options config must be a mapping")

    return SingleICCoverageOptions()


def _configured_label_bounds(params: Any) -> tuple[Any, Any]:
    start = _yaml_value(params, "test_start", _yaml_value(params, "start_time"))
    end = _yaml_value(params, "test_end", _yaml_value(params, "end_time"))
    if start is None or end is None:
        raise ValueError(
            "single_ic with single_ic_label_expression requires explicit "
            "test_start/test_end "
            "or start_time/end_time boundaries"
        )
    _normalise_bounds(start, end)
    return start, end


def _load_configured_label(exp: Any, factor_frame: pd.DataFrame) -> pd.Series | None:
    """Load the configured Qlib label and its sealed test segment."""
    params = getattr(exp, "yaml_params", None)
    expression = _yaml_value(params, "single_ic_label_expression")
    if not expression:
        return None

    provider_uri = _yaml_value(params, "provider_uri")
    factor_ctx = getattr(exp, "factor_data_context", None)
    if not provider_uri and factor_ctx is not None:
        provider_uri = str(factor_ctx.spec.qlib_dir)
    market = _yaml_value(params, "market")
    if not market and factor_ctx is not None:
        market = factor_ctx.spec.market
    if not provider_uri or not market:
        raise ValueError(
            "single_ic with single_ic_label_expression requires provider_uri and market"
        )

    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    freq = _yaml_value(params, "freq", "day")
    start, end = _configured_label_bounds(params)
    qlib.init(
        provider_uri=str(provider_uri),
        region=REG_CN,
        expression_cache=None,
        dataset_cache=None,
    )
    label_frame = D.features(
        D.instruments(str(market)),
        [str(expression)],
        start_time=start,
        end_time=end,
        freq=str(freq),
    )
    if label_frame.empty:
        raise ValueError(
            f"Configured single_ic label returned no rows: market={market}, "
            f"range=[{start}, {end}], expression={expression}"
        )
    label = label_frame.iloc[:, 0].rename("label")
    label = _canonical_panel_index(label, owner="configured label")
    if not _date_mask(label.index, start, end).all():
        raise ValueError("Configured single_ic label escaped its requested date boundaries")
    logger.info(
        f"[single_ic] configured label expression={expression!r} "
        f"market={market} range=[{start}, {end}] rows={len(label)}"
    )
    return label


class QlibSignalEngine:
    """Compute per-factor signed IC metrics without model training."""

    name = "qlib_signal"

    def run(
        self,
        exp: Any,
        *,
        use_local: bool = True,
        run_env: dict[str, str] | None = None,
        single_ic_options: SingleICCoverageOptions | None = None,
    ) -> EngineOutcome:
        from alphapilot.systems.backtest.runners.factor_runner import QlibFactorRunner

        runner = QlibFactorRunner(getattr(exp, "scen", None))
        factor_frame = runner.process_factor_data(exp)
        configured_label = _load_configured_label(exp, factor_frame)
        params = getattr(exp, "yaml_params", None)
        configured = configured_label is not None
        if configured:
            start, end = _configured_label_bounds(params)
        else:
            start = end = None
        if single_ic_options is None:
            single_ic_options = _single_ic_options_from_params(params)
        elif not isinstance(single_ic_options, SingleICCoverageOptions):
            raise TypeError(
                "single_ic_options must be a SingleICCoverageOptions instance"
            )
        table = compute_factor_ic_table(
            factor_frame,
            label=configured_label,
            start=start,
            end=end,
            options=single_ic_options,
        )

        try:
            ws = Path(exp.experiment_workspace.workspace_path)
            ws.mkdir(parents=True, exist_ok=True)
            table.to_csv(ws / LEADERBOARD_FILE, index=False)
            logger.info(
                f"[single_ic] wrote IC report ({len(table)} factors) -> {ws / LEADERBOARD_FILE}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[single_ic] failed to write IC report: {exc}")

        per_factor = table.to_dict("records")
        exp.result = table
        return EngineOutcome(metrics=table, per_factor=per_factor, experiment=exp)
