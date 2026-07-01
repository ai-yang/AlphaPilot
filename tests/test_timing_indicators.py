from __future__ import annotations

import numpy as np
import pandas as pd

from alphapilot.quant import indicators
from alphapilot.quant.signals import cross_above, cross_below, threshold_signal, to_target_weight


def test_basic_indicators_have_expected_shapes_and_values() -> None:
    close = pd.Series([10, 11, 12, 13, 14, 15], dtype=float)
    high = close + 1
    low = close - 1
    open_ = close - 0.5

    assert indicators.ma(close, 3).iloc[-1] == 14

    boll = indicators.bollinger(close, 3, 2)
    assert set(boll.columns) == {"middle", "upper", "lower"}
    assert boll["middle"].iloc[-1] == 14
    assert boll["upper"].iloc[-1] > boll["middle"].iloc[-1] > boll["lower"].iloc[-1]

    kdj = indicators.kdj(high, low, close, 3)
    assert set(kdj.columns) == {"k", "d", "j"}
    assert kdj["k"].notna().any()

    aroon = indicators.aroon(high, low, 3)
    assert set(aroon.columns) == {"aroon_up", "aroon_down"}
    assert aroon["aroon_up"].iloc[-1] == 100

    arbr = indicators.arbr(open_, high, low, close, 3)
    assert set(arbr.columns) == {"ar", "br"}
    assert np.isfinite(arbr["ar"].dropna()).all()


def test_rsi_and_stoch_rsi_ranges() -> None:
    close = pd.Series([10, 11, 10, 12, 11, 13, 12, 14, 13, 15], dtype=float)
    rsi = indicators.rsi(close, 3).dropna()
    assert ((rsi >= 0) & (rsi <= 100)).all()

    stoch = indicators.stoch_rsi(close, 3, 3).dropna()
    assert ((stoch >= 0) & (stoch <= 1)).all()


def test_signal_helpers_cross_and_persistent_position() -> None:
    left = pd.Series([1, 2, 3, 2, 1], dtype=float)
    right = pd.Series([2, 2, 2, 2, 2], dtype=float)

    assert cross_above(left, right).tolist() == [False, False, True, False, False]
    assert cross_below(left, right).tolist() == [False, False, False, False, True]

    signal = threshold_signal(
        pd.Series([False, True, False, False]),
        pd.Series([False, False, False, True]),
    )
    assert signal.tolist() == [0, 1, 1, 0]
    assert to_target_weight(signal, 0.5).tolist() == [0.0, 0.5, 0.5, 0.0]
