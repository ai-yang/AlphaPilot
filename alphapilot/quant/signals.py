"""Signal utilities for timing strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd


def cross_above(left: pd.Series, right: pd.Series | float) -> pd.Series:
    """True when ``left`` crosses from <= ``right`` to > ``right``."""
    r = right if isinstance(right, pd.Series) else pd.Series(right, index=left.index)
    return (left > r) & (left.shift(1) <= r.shift(1))


def cross_below(left: pd.Series, right: pd.Series | float) -> pd.Series:
    """True when ``left`` crosses from >= ``right`` to < ``right``."""
    r = right if isinstance(right, pd.Series) else pd.Series(right, index=left.index)
    return (left < r) & (left.shift(1) >= r.shift(1))


def threshold_signal(
    buy: pd.Series,
    sell: pd.Series,
    *,
    initial: int = 0,
) -> pd.Series:
    """Convert buy/sell booleans to a persistent long/flat signal."""
    state = int(initial)
    values: list[int] = []
    for b, s in zip(buy.fillna(False), sell.fillna(False), strict=False):
        if bool(s):
            state = 0
        if bool(b):
            state = 1
        values.append(state)
    return pd.Series(values, index=buy.index, dtype="int64")


def to_target_weight(signal: pd.Series, long_weight: float = 1.0) -> pd.Series:
    """Map positive signals to ``long_weight`` and all others to zero."""
    return pd.Series(
        np.where(pd.to_numeric(signal, errors="coerce").fillna(0) > 0, long_weight, 0.0),
        index=signal.index,
        dtype="float64",
    )
