from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from alphapilot.systems.timing.base import TimingBacktestRequest
from alphapilot.systems.timing.engine import TimingBacktestEngine


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "instrument": ["SZ000001"] * 4,
            "open": [10.0, 10.0, 11.0, 12.0],
            "high": [10.5, 10.5, 11.5, 12.5],
            "low": [9.5, 9.5, 10.5, 11.5],
            "close": [10.0, 10.5, 11.0, 12.0],
            "volume": [1000] * 4,
            "amount": [10000] * 4,
        }
    )


def test_engine_uses_next_bar_open_and_respects_trade_unit(tmp_path: Path) -> None:
    signals = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "instrument": ["SZ000001"] * 4,
            "signal": [1, 1, 0, 1],
            "target_percent": [1.0, 1.0, 0.0, 1.0],
            "score": [1.0, 1.0, 0.0, 1.0],
            "reason": ["test"] * 4,
        }
    )
    req = TimingBacktestRequest(
        strategy_name="unit",
        cash=1000,
        open_cost=0,
        close_cost=0,
        min_cost=0,
        trade_unit=100,
        output_dir=tmp_path,
    )

    result = TimingBacktestEngine().run(bars=_bars(), signals=signals, request=req)

    assert list(result.trades["side"]) == ["buy", "sell"]
    assert str(result.trades.iloc[0]["signal_datetime"]).startswith("2026-01-01")
    assert str(result.trades.iloc[0]["datetime"]).startswith("2026-01-02")
    assert result.trades.iloc[0]["amount"] == 100
    assert result.trades.iloc[1]["amount"] == 100
    # The final buy signal on 2026-01-04 has no next bar and must not execute.
    assert len(result.trades) == 2
    assert result.summary["final_equity"] == 1200
    assert (tmp_path / "summary.json").is_file()
    assert json.loads((tmp_path / "summary.json").read_text())["n_trades"] == 2


def test_engine_shrinks_buy_when_cash_is_insufficient(tmp_path: Path) -> None:
    bars = _bars()
    bars.loc[1, "open"] = 9.5
    signals = pd.DataFrame(
        {
            "datetime": bars["datetime"],
            "instrument": ["SZ000001"] * 4,
            "signal": [1, 1, 1, 1],
            "target_percent": [1.0, 1.0, 1.0, 1.0],
            "score": [1.0] * 4,
            "reason": ["test"] * 4,
        }
    )
    req = TimingBacktestRequest(
        strategy_name="unit",
        cash=1000,
        open_cost=0,
        close_cost=0,
        min_cost=0,
        trade_unit=100,
        output_dir=tmp_path,
    )

    result = TimingBacktestEngine().run(bars=bars, signals=signals, request=req)

    assert result.trades.iloc[0]["side"] == "buy"
    assert result.trades.iloc[0]["amount"] == 100
    assert result.trades.iloc[0]["value"] == 950
