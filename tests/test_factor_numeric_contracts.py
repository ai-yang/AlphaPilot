from __future__ import annotations

import numpy as np
import pandas as pd

from alphapilot.components.coder.factor_coder import function_lib as fl


def _series(values: list[float], *, instruments: tuple[str, ...]) -> pd.Series:
    dates = pd.date_range("2024-01-02", periods=len(values) // len(instruments))
    index = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )
    return pd.Series(values, index=index, name="value", dtype=float)


def test_cross_section_statistics_broadcast_to_original_index() -> None:
    values = _series(
        [1.0, 2.0, 4.0, 8.0, -3.0, 0.0, 6.0, 9.0],
        instruments=("AAA", "BBB", "CCC", "DDD"),
    )

    for function, statistic in (
        (fl.MEAN, "mean"),
        (fl.STD, "std"),
        (fl.SKEW, "skew"),
        (fl.MEDIAN, "median"),
    ):
        actual = function(values)
        expected = values.groupby(level="datetime").transform(statistic)
        pd.testing.assert_series_equal(actual, expected)
        assert actual.index.equals(values.index)

    kurtosis = fl.KURT(values)
    expected_kurtosis = values.groupby(level="datetime").transform(
        lambda group: group.kurt()
    )
    pd.testing.assert_series_equal(kurtosis, expected_kurtosis)
    assert kurtosis.index.equals(values.index)


def test_max_and_min_have_cross_sectional_and_pairwise_arities() -> None:
    values = _series([1.0, 4.0, -2.0, 3.0], instruments=("AAA", "BBB"))
    other = pd.Series(
        [2.0, 0.0, -3.0, 5.0], index=values.index, name=values.name
    )

    pd.testing.assert_series_equal(
        fl.MAX(values), values.groupby(level="datetime").transform("max")
    )
    pd.testing.assert_series_equal(
        fl.MIN(values), values.groupby(level="datetime").transform("min")
    )
    pd.testing.assert_series_equal(fl.MAX(values, other), values.combine(other, max))
    pd.testing.assert_series_equal(fl.MIN(values, other), values.combine(other, min))
    pd.testing.assert_series_equal(fl.MAX(values, 0.0), values.clip(lower=0.0))
    pd.testing.assert_series_equal(fl.MIN(values, 0.0), values.clip(upper=0.0))


def test_highday_and_lowday_use_day_zero_and_most_recent_tie() -> None:
    highs = _series([1.0, 3.0, 3.0, 2.0, 3.0], instruments=("AAA",))
    lows = _series([4.0, 2.0, 2.0, 3.0, 2.0], instruments=("AAA",))

    pd.testing.assert_series_equal(
        fl.HIGHDAY(highs, 4),
        pd.Series([0.0, 0.0, 0.0, 1.0, 0.0], index=highs.index, name="value"),
    )
    pd.testing.assert_series_equal(
        fl.LOWDAY(lows, 4),
        pd.Series([0.0, 0.0, 0.0, 1.0, 0.0], index=lows.index, name="value"),
    )


def test_log_is_natural_log_and_preserves_index() -> None:
    values = _series([1.0, np.e, np.e**2], instruments=("AAA",))

    actual = fl.LOG(values)

    pd.testing.assert_series_equal(
        actual,
        pd.Series([0.0, 1.0, 2.0], index=values.index, name="value"),
    )


def test_zscore_and_scale_handle_degenerate_cross_sections() -> None:
    values = _series(
        [2.0, 2.0, np.nan, 0.0, 0.0, np.nan],
        instruments=("AAA", "BBB", "CCC"),
    )

    zscore = fl.ZSCORE(values)
    scaled = fl.SCALE(values, 2.5)

    expected_zscore = pd.Series(
        [0.0, 0.0, np.nan, 0.0, 0.0, np.nan],
        index=values.index,
        name="value",
    )
    expected_scaled = pd.Series(
        [1.25, 1.25, np.nan, 0.0, 0.0, np.nan],
        index=values.index,
        name="value",
    )
    pd.testing.assert_series_equal(zscore, expected_zscore)
    pd.testing.assert_series_equal(scaled, expected_scaled)
    assert not np.isinf(zscore.dropna()).any()
    assert not np.isinf(scaled.dropna()).any()


def test_scale_normalizes_each_nonzero_cross_section() -> None:
    values = _series([1.0, -3.0, 2.0, 2.0], instruments=("AAA", "BBB"))

    scaled = fl.SCALE(values, 2.5)

    absolute_sums = scaled.abs().groupby(level="datetime").sum()
    expected = pd.Series(2.5, index=absolute_sums.index, name="value")
    pd.testing.assert_series_equal(absolute_sums, expected)
    assert scaled.index.equals(values.index)


def test_bollinger_bands_are_middle_plus_or_minus_two_sigma() -> None:
    prices = _series([1.0, 2.0, 4.0, 8.0, 16.0], instruments=("AAA",))
    middle = prices.groupby(level="instrument").transform(
        lambda group: group.rolling(3, min_periods=1).mean()
    )
    sigma = prices.groupby(level="instrument").transform(
        lambda group: group.rolling(3, min_periods=1).std()
    )

    pd.testing.assert_series_equal(fl.BB_MIDDLE(prices, 3), middle)
    pd.testing.assert_series_equal(fl.BB_UPPER(prices, 3), middle + 2 * sigma)
    pd.testing.assert_series_equal(fl.BB_LOWER(prices, 3), middle - 2 * sigma)


def test_alphaforge_log_translations_match_the_runtime_contract() -> None:
    # Importing the package installs the vendored alphagen module path.
    import alphapilot.modules.alphaforge  # noqa: F401
    from alphagen.data.expression import Log, S_log1p
    from alphagen_generic.features import close

    from alphapilot.modules.alphaforge.translate import translate

    assert translate(Log(close)) == "LOG($close)"
    assert translate(S_log1p(close)) == (
        "MULTIPLY(SIGN($close),LOG(ADD(ABS($close),1)))"
    )

    values = _series([-3.0, -1.0, 0.0, 2.0], instruments=("AAA",))
    translated_value = fl.MULTIPLY(fl.SIGN(values), fl.LOG(fl.ADD(fl.ABS(values), 1)))
    expected = np.sign(values) * np.log1p(np.abs(values))
    pd.testing.assert_series_equal(translated_value, expected)
