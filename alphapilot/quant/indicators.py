"""Pure pandas/numpy technical indicators for timing strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _series(value: pd.Series) -> pd.Series:
    return pd.to_numeric(value, errors="coerce")


def ma(close: pd.Series, window: int = 20) -> pd.Series:
    """Simple moving average."""
    return _series(close).rolling(window, min_periods=window).mean()


def bollinger(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger bands: middle/upper/lower."""
    price = _series(close)
    middle = price.rolling(window, min_periods=window).mean()
    std = price.rolling(window, min_periods=window).std(ddof=0)
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": middle + num_std * std,
            "lower": middle - num_std * std,
        },
        index=close.index,
    )


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index in [0, 100]."""
    price = _series(close)
    delta = price.diff()
    gain = delta.clip(lower=0).rolling(window, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100).where(loss != 0, 100).where(gain != 0, 0)


def kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 9,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> pd.DataFrame:
    """KDJ oscillator."""
    h = _series(high)
    l = _series(low)
    c = _series(close)
    low_n = l.rolling(window, min_periods=window).min()
    high_n = h.rolling(window, min_periods=window).max()
    rsv = (c - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / max(k_smooth, 1), adjust=False).mean()
    d = k.ewm(alpha=1 / max(d_smooth, 1), adjust=False).mean()
    j = 3 * k - 2 * d
    return pd.DataFrame({"k": k, "d": d, "j": j}, index=close.index)


def aroon(high: pd.Series, low: pd.Series, window: int = 25) -> pd.DataFrame:
    """Aroon up/down in [0, 100]."""

    def up_func(values: np.ndarray) -> float:
        periods_since_high = len(values) - 1 - int(np.argmax(values))
        return 100.0 * (len(values) - periods_since_high) / len(values)

    def down_func(values: np.ndarray) -> float:
        periods_since_low = len(values) - 1 - int(np.argmin(values))
        return 100.0 * (len(values) - periods_since_low) / len(values)

    up = _series(high).rolling(window, min_periods=window).apply(up_func, raw=True)
    down = _series(low).rolling(window, min_periods=window).apply(down_func, raw=True)
    return pd.DataFrame({"aroon_up": up, "aroon_down": down}, index=high.index)


def stoch_rsi(
    close: pd.Series,
    rsi_window: int = 14,
    stoch_window: int = 14,
) -> pd.Series:
    """Stochastic RSI in [0, 1]."""
    r = rsi(close, rsi_window)
    low_r = r.rolling(stoch_window, min_periods=stoch_window).min()
    high_r = r.rolling(stoch_window, min_periods=stoch_window).max()
    return (r - low_r) / (high_r - low_r).replace(0, np.nan)


def arbr(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 26,
) -> pd.DataFrame:
    """AR/BR sentiment indicators."""
    o = _series(open_)
    h = _series(high)
    l = _series(low)
    c = _series(close)
    ar_num = (h - o).rolling(window, min_periods=window).sum()
    ar_den = (o - l).rolling(window, min_periods=window).sum()
    prev_close = c.shift(1)
    br_num = (h - prev_close).clip(lower=0).rolling(window, min_periods=window).sum()
    br_den = (prev_close - l).clip(lower=0).rolling(window, min_periods=window).sum()
    return pd.DataFrame(
        {
            "ar": ar_num / ar_den.replace(0, np.nan) * 100,
            "br": br_num / br_den.replace(0, np.nan) * 100,
        },
        index=open_.index,
    )
