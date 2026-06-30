"""Offline tests for the baostock minute downloader (baostock mocked, no network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from alphapilot.systems.data import prepare_cn_minute
from alphapilot.systems.data.prepare_cn_minute import (
    _normalize_minute_frame,
    download_cn_minute_data,
)
from alphapilot.systems.data.frequency import get_frequency

MINUTE_FIELDS = get_frequency("5min").csv_fields.split(",")


def _row(time: str, code: str, close: str) -> list[str]:
    # Order matches MINUTE_FIELDS: date,time,code,open,high,low,close,volume,amount,adjustflag
    return ["2026-05-06", time, code, "10.0", "10.5", "9.9", close, "1000", "10000", "1"]


def test_normalize_minute_frame_builds_intraday_timestamp() -> None:
    rows = [_row("20260506093500000", "sh.600000", "10.1")]
    df = _normalize_minute_frame(rows, MINUTE_FIELDS, get_frequency("5min"))
    assert list(df["date"]) == ["2026-05-06 09:35:00"]
    assert list(df["code"]) == ["sh600000"]  # dots stripped
    assert df["close"].iloc[0] == 10.1


class _FakeRS:
    def __init__(self, rows: list[list[str]], fields: list[str]) -> None:
        self.error_code = "0"
        self.error_msg = ""
        self.fields = fields
        self._rows = rows
        self._i = -1

    def next(self) -> bool:
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._i]


def _install_fake_bs(monkeypatch: pytest.MonkeyPatch, rows_by_code: dict[str, list[list[str]]]) -> dict:
    calls: dict = {"queries": []}

    def login():
        return SimpleNamespace(error_code="0", error_msg="")

    def logout():
        calls["logged_out"] = True

    def query_history_k_data_plus(code, fields, start_date, end_date, frequency, adjustflag):
        calls["queries"].append((code, frequency, adjustflag))
        return _FakeRS(rows_by_code.get(code, []), fields.split(","))

    fake = SimpleNamespace(
        login=login, logout=logout, query_history_k_data_plus=query_history_k_data_plus
    )
    monkeypatch.setattr(prepare_cn_minute, "bs", fake)
    return calls


def test_download_writes_minute_csv_and_uses_5min_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = {
        "sh.600000": [_row("20260506093500000", "sh.600000", "10.1"),
                      _row("20260506094000000", "sh.600000", "10.2")],
    }
    calls = _install_fake_bs(monkeypatch, rows)

    codes = download_cn_minute_data(
        start_date="2026-05-06",
        end_date="2026-05-09",
        freq="5min",
        data_dir=tmp_path,
        symbols=["sh.600000"],
        download_state_path=tmp_path / "state.csv",
    )
    assert codes == ["sh.600000"]
    # baostock was queried with the 5min frequency code.
    assert calls["queries"][0][1] == "5"

    out = tmp_path / "sh600000.csv"
    assert out.is_file()
    df = pd.read_csv(out)
    assert len(df) == 2
    assert df["date"].iloc[0] == "2026-05-06 09:35:00"


def test_download_is_incremental_and_dedups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = {"sh.600000": [_row("20260506093500000", "sh.600000", "10.1")]}
    _install_fake_bs(monkeypatch, rows)
    common = dict(
        start_date="2026-05-06", end_date="2026-05-09", freq="5min",
        data_dir=tmp_path, symbols=["sh.600000"], download_state_path=tmp_path / "s.csv",
    )
    download_cn_minute_data(**common)
    download_cn_minute_data(**common)  # same bar again -> deduped
    df = pd.read_csv(tmp_path / "sh600000.csv")
    assert len(df) == 1


def test_minute_downloader_rejects_daily_freq(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        download_cn_minute_data(start_date="2026-05-06", freq="day", symbols=["sh.600000"])


def test_baostock_adapter_routes_intraday_to_minute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The data-source adapter dispatches intraday freq to the minute pipeline."""
    from alphapilot.adapters.builtin.data_source.baostock_cn import BaostockDataSourceAdapter
    from alphapilot.adapters.base import DataDownloadRequest

    captured: dict = {}

    def fake_minute(**kwargs):
        captured.update(kwargs)
        return ["sh.600000"]

    monkeypatch.setattr(prepare_cn_minute, "download_cn_minute_data", fake_minute)
    # The adapter imports the symbol lazily inside the method, so patch the source module.
    monkeypatch.setattr(
        "alphapilot.systems.data.prepare_cn_minute.download_cn_minute_data", fake_minute
    )

    req = DataDownloadRequest(
        start_date="2026-05-06", end_date="2026-05-09",
        symbols=["sh.600000"], output_dir=tmp_path,
        options={"freq": "5min", "adjust_mode": "backward"},
    )
    result = BaostockDataSourceAdapter().download(req)
    assert captured["freq"] == "5min"
    assert result.extra["freq"] == "5min"
