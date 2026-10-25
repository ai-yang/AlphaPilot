from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphapilot.components.coder.factor_coder.function_lib import (
    REGBETA,
    SEQUENCE,
    TS_MAD,
    rolling_beta,
)


def _market_series() -> pd.Series:
    index = pd.MultiIndex.from_product(
        [pd.date_range("2020-01-01", periods=63), ["B", "A"]],
        names=["datetime", "instrument"],
    )
    series = pd.Series(
        np.random.default_rng(42).normal(30, 4, len(index)), index=index
    )
    series.iloc[0] = np.nan
    series.iloc[37] = np.nan
    return series


@pytest.mark.parametrize("window", [1, 5, 20, 63, 100])
def test_sequence_beta_matches_window_least_squares(window: int) -> None:
    series = _market_series()
    x = SEQUENCE(window)
    design = np.column_stack([x, np.ones(window)])
    results = []
    for _, group in series.fillna(0).groupby("instrument"):
        values = np.full(len(group), np.nan)
        for i in range(window - 1, len(group)):
            values[i] = np.linalg.lstsq(
                design, group.iloc[i - window + 1:i + 1].to_numpy(), rcond=None
            )[0][0]
        results.append(pd.Series(values, index=group.index))
    expected = pd.concat(results).sort_index()
    actual = REGBETA(series, x, window, n_jobs=1)
    pd.testing.assert_series_equal(actual, expected, rtol=1e-10, atol=1e-10)


def test_time_varying_predictor_retains_window_regression() -> None:
    y = pd.Series([1.0, 3.0, 2.0, 7.0, 4.0, 8.0])
    # The first window resembles SEQUENCE(3), but later windows do not.
    x = pd.Series([1.0, 2.0, 3.0, 8.0, 14.0, 11.0])
    actual = rolling_beta(y, x, 3)
    expected = [np.nan, np.nan] + [
        np.linalg.lstsq(
            np.column_stack([x.iloc[i - 2:i + 1], np.ones(3)]),
            y.iloc[i - 2:i + 1],
            rcond=None,
        )[0][0]
        for i in range(2, len(y))
    ]
    np.testing.assert_allclose(
        actual, expected, rtol=1e-10, atol=1e-10, equal_nan=True
    )


def test_constant_predictor_keeps_least_squares_fallback() -> None:
    y = pd.Series([1.0, 3.0, 2.0, 7.0, 4.0, 8.0])
    x = pd.Series([2.0, 2.0, 2.0])
    design = np.column_stack([x, np.ones(3)])
    expected = [np.nan, np.nan] + [
        np.linalg.lstsq(design, y.iloc[i - 2:i + 1], rcond=None)[0][0]
        for i in range(2, len(y))
    ]
    np.testing.assert_allclose(
        rolling_beta(y, x, 3), expected, rtol=1e-10, atol=1e-10, equal_nan=True
    )


@pytest.mark.parametrize("window", [1, 2, 5, 20, 100])
@pytest.mark.parametrize("dataframe", [False, True])
def test_mad_matches_pandas_including_partial_and_missing_windows(
    window: int, dataframe: bool
) -> None:
    series = _market_series()
    series.iloc[29] = np.inf
    data = pd.DataFrame({"a": series, "b": series * 2 + 3}) if dataframe else series
    expected = data.groupby("instrument").transform(
        lambda group: group.rolling(window, min_periods=1).apply(
            lambda values: np.median(np.abs(values - np.median(values))), raw=True
        )
    )
    actual = TS_MAD(data, window)
    if dataframe:
        pd.testing.assert_frame_equal(actual, expected)
    else:
        pd.testing.assert_series_equal(actual, expected)


def test_mad_matches_pandas_across_chunk_boundary() -> None:
    index = pd.MultiIndex.from_product(
        [pd.date_range("1990-01-01", periods=8600), ["A"]],
        names=["datetime", "instrument"],
    )
    series = pd.Series(np.sin(np.arange(len(index)) / 37), index=index)
    # With a 120-day window, a chunk contains 8,333 windows. Include
    # missing data across that boundary to check both values and alignment.
    series.iloc[8450] = np.nan
    expected = series.rolling(120, min_periods=1).apply(
        lambda values: np.median(np.abs(values - np.median(values))), raw=True
    )
    pd.testing.assert_series_equal(TS_MAD(series, 120), expected)
