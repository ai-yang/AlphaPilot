"""Offline tests: data_viz loader exposes intraday (minute) sources for the portal."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_minute_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,time,code,open,high,low,close,volume,amount,adjustflag\n"
        "2026-06-23 09:35:00,20260623093500000,sh600000,10.0,10.5,9.9,10.2,1000,10000,2\n"
        "2026-06-23 09:40:00,20260623094000000,sh600000,10.2,10.6,10.1,10.3,1200,12000,2\n",
        encoding="utf-8",
    )


def test_list_data_sources_includes_minute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    from alphapilot.modules.data_viz.loader import list_data_sources
    from alphapilot.systems.data.data_paths import baostock_minute_raw_dir

    raw = baostock_minute_raw_dir("5min")
    _write_minute_csv(raw / "sh600000.csv")

    sources = list_data_sources()
    minute = [s for s in sources if s.freq == "5min"]
    assert minute, f"expected a 5min source, got {[s.label for s in sources]}"
    assert minute[0].provider == "baostock"
    assert minute[0].path == raw
    assert "5min" in minute[0].label
    # Daily sources keep the default freq.
    assert all(s.freq == "day" for s in sources if s.freq != "5min")


def test_load_bars_preserves_intraday_timestamp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    from alphapilot.modules.data_viz.loader import available_date_range, load_bars
    from alphapilot.systems.data.data_paths import baostock_minute_raw_dir

    raw = baostock_minute_raw_dir("5min")
    _write_minute_csv(raw / "sh600000.csv")

    df = load_bars("sh600000", raw)
    assert len(df) == 2
    first = str(df["date"].iloc[0])
    assert first.startswith("2026-06-23") and "09:35:00" in first  # intraday time kept
    dmin, dmax = available_date_range(df)
    assert str(dmin) == "2026-06-23" and str(dmax) == "2026-06-23"
