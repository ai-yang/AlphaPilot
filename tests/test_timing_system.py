from __future__ import annotations

from pathlib import Path

import pandas as pd

from alphapilot.systems.timing.base import TimingBacktestRequest


def _write_csv(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "sz000001.csv"
    pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=35, freq="D").strftime("%Y-%m-%d"),
            "code": ["sz000001"] * 35,
            "open": [10 + i * 0.1 for i in range(35)],
            "high": [10.5 + i * 0.1 for i in range(35)],
            "low": [9.5 + i * 0.1 for i in range(35)],
            "close": [10 + i * 0.1 for i in range(35)],
            "volume": [1000] * 35,
            "amount": [10000] * 35,
        }
    ).to_csv(csv_path, index=False)
    return csv_path


def test_timing_system_loads_local_csv_and_generates_signals(engine, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_csv(raw)
    timing = engine.get_system("timing")

    req = TimingBacktestRequest(
        strategy_name="sma_filter",
        symbols=["sz.000001"],
        start_date="2026-01-05",
        end_date="2026-01-20",
        data_dir=raw,
        strategy_params={"window": 3},
    )
    signals = timing.generate_signals(req)

    assert not signals.empty
    assert signals["instrument"].unique().tolist() == ["SZ000001"]
    assert signals["datetime"].min() >= pd.Timestamp("2026-01-05")


def test_timing_backtest_writes_artifacts(engine, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    out = tmp_path / "timing_out"
    _write_csv(raw)
    timing = engine.get_system("timing")

    req = TimingBacktestRequest(
        strategy_name="dual_ma",
        symbols="000001",
        data_dir=raw,
        cash=100000,
        trade_unit=100,
        strategy_params={"short_window": 2, "long_window": 5},
        output_dir=out,
    )
    result = timing.run_backtest(req)

    assert result.artifact_dir == out
    assert (out / "signals.csv").is_file()
    assert (out / "trades.csv").is_file()
    assert (out / "equity_curve.csv").is_file()
    assert (out / "positions.csv").is_file()
    assert result.summary["strategy"] == "dual_ma"
