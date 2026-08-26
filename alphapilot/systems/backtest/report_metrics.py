"""Frequency-safe metrics derived from Qlib portfolio reports."""

from __future__ import annotations

import math

import pandas as pd


def average_daily_turnover(report: pd.DataFrame) -> float:
    """Return mean daily turnover from a daily or intraday Qlib report.

    Qlib records ``turnover`` once per executor step.  For intraday runs those
    values are bar-level rates, so their arithmetic mean is not a daily metric.
    We first add all finite bar rates within each calendar trading date and
    then average the resulting daily totals.  Daily reports naturally retain
    their existing arithmetic-mean behavior because they have one row per day.

    Invalid or partial data is rejected instead of silently understating
    trading intensity.
    """
    if not isinstance(report, pd.DataFrame):
        raise TypeError("portfolio report must be a pandas DataFrame")
    if report.empty:
        raise ValueError("portfolio report has no rows")
    if "turnover" not in report.columns:
        raise ValueError("portfolio report is missing the turnover column")

    if isinstance(report.index, pd.MultiIndex):
        if "datetime" not in report.index.names:
            raise ValueError("portfolio report MultiIndex has no datetime level")
        raw_datetimes = report.index.get_level_values("datetime")
    else:
        raw_datetimes = report.index
    datetimes = pd.DatetimeIndex(pd.to_datetime(raw_datetimes, errors="coerce"))
    if datetimes.isna().any():
        raise ValueError("portfolio report index contains invalid datetimes")

    turnover = pd.to_numeric(report["turnover"], errors="coerce")
    if turnover.isna().any() or not bool(turnover.map(math.isfinite).all()):
        raise ValueError("portfolio report turnover contains non-finite values")
    if bool((turnover < 0).any()):
        raise ValueError("portfolio report turnover contains negative values")

    bars = pd.Series(
        turnover.to_numpy(dtype=float, copy=False),
        index=datetimes.normalize(),
        dtype=float,
    )
    daily = bars.groupby(level=0, sort=True).sum(min_count=1)
    if daily.empty or daily.isna().any():
        raise ValueError("portfolio report has no complete daily turnover values")
    return float(daily.mean())
