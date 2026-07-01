"""Built-in timing strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from alphapilot.quant import indicators
from alphapilot.quant.signals import cross_above, cross_below, threshold_signal, to_target_weight
from alphapilot.systems.timing.base import TimingContext


@dataclass(frozen=True)
class StrategySpec:
    name: str
    description: str
    defaults: dict[str, Any]
    factory: Callable[[dict[str, Any]], "RuleTimingStrategy"]


class RuleTimingStrategy:
    name = "rule"
    description = ""
    defaults: dict[str, Any] = {}

    def __init__(self, **params: Any) -> None:
        merged = dict(self.defaults)
        merged.update(params)
        self.params = merged

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        raise NotImplementedError

    def generate_signals(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        frames = []
        for instrument, group in bars.sort_values("datetime").groupby("instrument", sort=True):
            out = self._instrument_signal(group.reset_index(drop=True), context)
            out["instrument"] = instrument
            frames.append(out)
        if not frames:
            return pd.DataFrame(
                columns=["datetime", "instrument", "signal", "target_percent", "score", "reason"]
            )
        result = pd.concat(frames, ignore_index=True)
        return result[["datetime", "instrument", "signal", "target_percent", "score", "reason"]]

    def _frame(
        self,
        bars: pd.DataFrame,
        signal: pd.Series,
        score: pd.Series | float = 0.0,
        reason: str = "",
    ) -> pd.DataFrame:
        target_percent = float(self.params.get("target_percent", 1.0))
        score_series = score if isinstance(score, pd.Series) else pd.Series(score, index=signal.index)
        return pd.DataFrame(
            {
                "datetime": bars["datetime"].values,
                "signal": signal.fillna(0).astype(int).values,
                "target_percent": to_target_weight(signal, target_percent).values,
                "score": pd.to_numeric(score_series, errors="coerce").values,
                "reason": reason,
            }
        )


class BollMeanReversion(RuleTimingStrategy):
    name = "boll_mean_reversion"
    description = "BOLL mean reversion: buy below lower band, exit above middle/upper band."
    defaults = {"window": 20, "num_std": 2.0, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        bands = indicators.bollinger(bars["close"], self.params["window"], self.params["num_std"])
        buy = bars["close"] < bands["lower"]
        sell = (bars["close"] > bands["middle"]) | (bars["close"] > bands["upper"])
        signal = threshold_signal(buy, sell)
        score = (bands["middle"] - bars["close"]) / bars["close"]
        return self._frame(bars, signal, score, "boll_mean_reversion")


class SmaFilter(RuleTimingStrategy):
    name = "sma_filter"
    description = "Long when close is above its moving average."
    defaults = {"window": 20, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        avg = indicators.ma(bars["close"], self.params["window"])
        signal = (bars["close"] > avg).astype(int)
        return self._frame(bars, signal, bars["close"] / avg - 1, "sma_filter")


class DualMA(RuleTimingStrategy):
    name = "dual_ma"
    description = "Buy on short MA crossing above long MA; exit on cross below."
    defaults = {"short_window": 5, "long_window": 20, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        short = indicators.ma(bars["close"], self.params["short_window"])
        long = indicators.ma(bars["close"], self.params["long_window"])
        signal = threshold_signal(cross_above(short, long), cross_below(short, long))
        return self._frame(bars, signal, short / long - 1, "dual_ma")


class RsiReversion(RuleTimingStrategy):
    name = "rsi_reversion"
    description = "RSI mean reversion: buy oversold, exit overbought."
    defaults = {"window": 14, "low": 30.0, "high": 70.0, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        r = indicators.rsi(bars["close"], self.params["window"])
        signal = threshold_signal(r < self.params["low"], r > self.params["high"])
        return self._frame(bars, signal, 50 - r, "rsi_reversion")


class KdjCross(RuleTimingStrategy):
    name = "kdj_cross"
    description = "Buy when K crosses above D; exit when K crosses below D."
    defaults = {"window": 9, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        kdj = indicators.kdj(bars["high"], bars["low"], bars["close"], self.params["window"])
        signal = threshold_signal(cross_above(kdj["k"], kdj["d"]), cross_below(kdj["k"], kdj["d"]))
        return self._frame(bars, signal, kdj["k"] - kdj["d"], "kdj_cross")


class AroonTrend(RuleTimingStrategy):
    name = "aroon_trend"
    description = "Trend following with Aroon up/down."
    defaults = {"window": 25, "up_threshold": 70.0, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        ar = indicators.aroon(bars["high"], bars["low"], self.params["window"])
        buy = (ar["aroon_up"] > ar["aroon_down"]) & (ar["aroon_up"] > self.params["up_threshold"])
        sell = ar["aroon_down"] > ar["aroon_up"]
        signal = threshold_signal(buy, sell)
        return self._frame(bars, signal, ar["aroon_up"] - ar["aroon_down"], "aroon_trend")


class StochRsiReversion(RuleTimingStrategy):
    name = "stoch_rsi_reversion"
    description = "StochRSI mean reversion."
    defaults = {"rsi_window": 14, "stoch_window": 14, "low": 0.2, "high": 0.8, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        s = indicators.stoch_rsi(bars["close"], self.params["rsi_window"], self.params["stoch_window"])
        signal = threshold_signal(s < self.params["low"], s > self.params["high"])
        return self._frame(bars, signal, 0.5 - s, "stoch_rsi_reversion")


class ArbrReversion(RuleTimingStrategy):
    name = "arbr_reversion"
    description = "ARBR sentiment reversion."
    defaults = {"window": 26, "low": 70.0, "high": 150.0, "target_percent": 1.0}

    def _instrument_signal(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        arbr = indicators.arbr(bars["open"], bars["high"], bars["low"], bars["close"], self.params["window"])
        ratio = arbr["br"] / arbr["ar"].replace(0, pd.NA)
        buy = (arbr["br"] < self.params["low"]) | (ratio < 0.8)
        sell = (arbr["br"] > self.params["high"]) | (ratio > 1.5)
        signal = threshold_signal(buy, sell)
        return self._frame(bars, signal, self.params["low"] - arbr["br"], "arbr_reversion")


_STRATEGY_CLASSES: tuple[type[RuleTimingStrategy], ...] = (
    BollMeanReversion,
    SmaFilter,
    DualMA,
    RsiReversion,
    KdjCross,
    AroonTrend,
    StochRsiReversion,
    ArbrReversion,
)


def list_strategy_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": cls.name,
            "description": cls.description,
            "defaults": dict(cls.defaults),
        }
        for cls in _STRATEGY_CLASSES
    ]


def create_strategy(name: str, params: dict[str, Any] | None = None) -> RuleTimingStrategy:
    key = name.strip().lower()
    for cls in _STRATEGY_CLASSES:
        if cls.name == key:
            return cls(**(params or {}))
    raise ValueError(f"Unsupported timing strategy {name!r}; available={list_builtin_strategy_names()}")


def list_builtin_strategy_names() -> list[str]:
    return [cls.name for cls in _STRATEGY_CLASSES]
