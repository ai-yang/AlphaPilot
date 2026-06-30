"""Offline tests for the FrequencySpec abstraction and freq-aware data paths."""

from __future__ import annotations

import pytest

from alphapilot.systems.data.frequency import (
    FREQUENCIES,
    get_frequency,
    portfolio_artifact_names,
)


def test_daily_spec_matches_legacy_defaults() -> None:
    spec = get_frequency("day")
    assert spec.key == "day"
    assert spec.baostock_code == "d"
    assert spec.qlib_freq == "day"
    assert spec.is_intraday is False
    assert spec.bars_per_day == 1
    assert spec.ann_scaler == 252  # unchanged daily annualization
    assert spec.qlib_dir_suffix == ""
    assert spec.time_per_step == "day"
    assert spec.rebalance_tag == "1day"


@pytest.mark.parametrize(
    "key,bcode,bars,ann",
    [
        ("5min", "5", 48, 252 * 48),
        ("15min", "15", 16, 252 * 16),
        ("30min", "30", 8, 252 * 8),
        ("60min", "60", 4, 252 * 4),
    ],
)
def test_minute_specs(key: str, bcode: str, bars: int, ann: int) -> None:
    spec = get_frequency(key)
    assert spec.baostock_code == bcode
    assert spec.is_intraday is True
    assert spec.bars_per_day == bars
    assert spec.ann_scaler == ann
    assert spec.qlib_dir_suffix == f"_{key}"
    assert spec.time_per_step == key
    assert spec.rebalance_tag == key
    assert spec.qlib_freq == key
    # Minute bars expose the slimmer baostock schema with a ``time`` column.
    assert "time" in spec.csv_fields
    assert "preclose" not in spec.csv_fields


def test_none_and_aliases_resolve() -> None:
    assert get_frequency(None).key == "day"
    assert get_frequency("5").key == "5min"
    assert get_frequency("5m").key == "5min"
    assert get_frequency("1h").key == "60min"
    assert get_frequency("DAILY").key == "day"
    # Passing a spec back through is idempotent.
    spec = get_frequency("5min")
    assert get_frequency(spec) is spec


def test_unsupported_frequency_rejected() -> None:
    with pytest.raises(ValueError):
        get_frequency("1min")  # baostock has no 1-minute bars
    with pytest.raises(ValueError):
        get_frequency("tick")


def test_portfolio_artifact_names() -> None:
    day = portfolio_artifact_names("day")
    assert day["report"] == "report_normal_1day.pkl"
    assert day["positions"] == "positions_normal_1day.pkl"
    assert day["indicators"] == "indicators_normal_1day.pkl"

    five = portfolio_artifact_names("5min")
    assert five["report"] == "report_normal_5min.pkl"
    assert five["positions"] == "positions_normal_5min.pkl"
    assert five["indicators"] == "indicators_normal_5min.pkl"


def test_day_is_first_registered_freq() -> None:
    # Daily must come first so tolerant lookups stay backward-compatible.
    assert next(iter(FREQUENCIES)) == "day"


def test_data_paths_are_freq_aware(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    from alphapilot.systems.data import data_paths

    day_dir = data_paths.baostock_qlib_dir("day")
    assert day_dir.name == "qlib"

    five_dir = data_paths.baostock_qlib_dir("5min")
    assert five_dir.name == "qlib_5min"
    assert five_dir.parent == day_dir.parent  # sibling layout

    raw = data_paths.baostock_minute_raw_dir("5min")
    assert raw.name == "raw_min_5min"

    with pytest.raises(ValueError):
        data_paths.baostock_minute_raw_dir("day")  # day has no minute raw dir
