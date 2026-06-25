from __future__ import annotations

import pandas as pd

from alphapilot.systems.data.download_state import DownloadStateStore
from alphapilot.systems.data.prepare_cn import download_stock_data


class _FakeLogin:
    error_code = "0"
    error_msg = ""


class _FakeResult:
    def __init__(self, fields, rows, *, error_code="0", error_msg=""):
        self.fields = fields
        self.rows = rows
        self.error_code = error_code
        self.error_msg = error_msg
        self._index = -1

    def next(self):
        self._index += 1
        return self._index < len(self.rows)

    def get_row_data(self):
        return self.rows[self._index]


class _FakeBaostock:
    def __init__(self, *, trade_rows=None, history_rows=None, trade_error=False):
        self.trade_rows = trade_rows or []
        self.history_rows = history_rows or []
        self.trade_error = trade_error
        self.history_calls = []

    def login(self):
        return _FakeLogin()

    def logout(self):
        return None

    def query_trade_dates(self, start_date, end_date):
        if self.trade_error:
            return _FakeResult([], [], error_code="1", error_msg="calendar failed")
        return _FakeResult(
            ["calendar_date", "is_trading_day"],
            self.trade_rows,
        )

    def query_history_k_data_plus(
        self,
        code,
        fields,
        start_date,
        end_date,
        frequency,
        adjustflag,
    ):
        self.history_calls.append(
            {
                "code": code,
                "start_date": start_date,
                "end_date": end_date,
                "frequency": frequency,
                "adjustflag": adjustflag,
            }
        )
        return _FakeResult(fields.split(","), self.history_rows)


def _seed_state(
    path, raw_dir, *, checked_until="2026-06-12", data_end_date="2026-06-12"
):
    store = DownloadStateStore(path)
    store.upsert(
        source="baostock_cn",
        adjust_mode="backward",
        code="sz.000001",
        raw_dir=raw_dir,
        data_end_date=data_end_date,
        checked_until=checked_until,
        last_status="seed",
    )
    store.save()


def _read_state(path, raw_dir):
    return DownloadStateStore(path).get(
        source="baostock_cn",
        adjust_mode="backward",
        code="sz.000001",
        raw_dir=raw_dir,
    )


def test_bootstraps_missing_state_from_existing_csv(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw_data_back_adjust"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "2026-06-09", "code": "sz000001", "open": 1},
            {"date": "2026-06-10", "code": "sz000001", "open": 2},
        ]
    ).to_csv(raw_dir / "sz000001.csv", index=False)
    fake_bs = _FakeBaostock()
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    download_stock_data(
        "2026-01-01",
        "2026-06-10",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="backward",
        download_state_path=state_path,
    )

    record = _read_state(state_path, raw_dir)
    assert record is not None
    assert record.data_end_date == "2026-06-10"
    assert record.checked_until == "2026-06-10"
    assert fake_bs.history_calls == []


def test_existing_state_takes_precedence_over_csv_last_date(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw_data_back_adjust"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "2026-06-13", "code": "sz000001", "open": 1},
        ]
    ).to_csv(raw_dir / "sz000001.csv", index=False)
    _seed_state(
        state_path, raw_dir, checked_until="2026-06-10", data_end_date="2026-06-10"
    )
    fake_bs = _FakeBaostock(
        trade_rows=[
            ["2026-06-11", "1"],
            ["2026-06-12", "1"],
        ]
    )
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    download_stock_data(
        "2026-01-01",
        "2026-06-12",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="backward",
        download_state_path=state_path,
    )

    assert fake_bs.history_calls[0]["start_date"] == "2026-06-11"


def test_no_trading_days_skips_history_request_and_advances_checked_until(
    tmp_path, monkeypatch
):
    raw_dir = tmp_path / "raw_data_back_adjust"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    _seed_state(state_path, raw_dir)
    fake_bs = _FakeBaostock(
        trade_rows=[
            ["2026-06-13", "0"],
            ["2026-06-14", "0"],
        ]
    )
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    download_stock_data(
        "2026-01-01",
        "2026-06-14",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="backward",
        download_state_path=state_path,
    )

    record = _read_state(state_path, raw_dir)
    assert record is not None
    assert record.data_end_date == "2026-06-12"
    assert record.checked_until == "2026-06-14"
    assert record.last_status == "no_trading_days"
    assert fake_bs.history_calls == []


def test_trading_day_download_updates_data_end_date(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw_data_back_adjust"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    _seed_state(state_path, raw_dir)
    fake_bs = _FakeBaostock(
        trade_rows=[
            ["2026-06-13", "1"],
            ["2026-06-14", "0"],
        ],
        history_rows=[
            [
                "2026-06-13",
                "sz.000001",
                "1",
                "2",
                "1",
                "2",
                "1",
                "100",
                "200",
                "0.1",
                "1",
                "1.0",
                "10",
                "1",
                "2",
                "3",
                "0",
            ]
        ],
    )
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    download_stock_data(
        "2026-01-01",
        "2026-06-14",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="backward",
        download_state_path=state_path,
    )

    record = _read_state(state_path, raw_dir)
    assert record is not None
    assert record.data_end_date == "2026-06-13"
    assert record.checked_until == "2026-06-14"
    assert record.last_status == "updated"


def test_trade_calendar_failure_falls_back_to_history_request(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw_data_back_adjust"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    _seed_state(state_path, raw_dir)
    fake_bs = _FakeBaostock(trade_error=True)
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    download_stock_data(
        "2026-01-01",
        "2026-06-14",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="backward",
        download_state_path=state_path,
    )

    record = _read_state(state_path, raw_dir)
    assert record is not None
    assert record.checked_until == "2026-06-14"
    assert record.last_status == "empty"
    assert fake_bs.history_calls[0]["start_date"] == "2026-06-13"


def test_baostock_parallel_price_factor_splits_factor_flow(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw_data_no_adjust"
    factor_dir = tmp_path / "adjust_factors"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    fake_bs = _FakeBaostock(
        trade_rows=[["2026-06-13", "1"]],
        history_rows=[
            [
                "2026-06-13",
                "sz.000001",
                "1",
                "2",
                "1",
                "2",
                "1",
                "100",
                "200",
                "0.1",
                "1",
                "1.0",
                "10",
                "1",
                "2",
                "3",
                "0",
            ]
        ],
    )
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    started = {}

    def fake_start(codes, end_date, factor_path, download_starts):
        started["codes"] = codes
        started["end_date"] = end_date
        started["factor_path"] = factor_path
        started["download_starts"] = download_starts
        return object(), object()

    def fake_finish(_process, _queue):
        return {
            "factor_probed": 1,
            "factor_refreshed": 1,
            "factor_skipped": 0,
            "errors": 0,
        }

    def fail_sync_factor(*_args, **_kwargs):
        raise AssertionError("sync factor path should be skipped in parallel mode")

    monkeypatch.setattr(
        "alphapilot.systems.data.prepare_cn._start_parallel_adjust_factor_process",
        fake_start,
    )
    monkeypatch.setattr(
        "alphapilot.systems.data.prepare_cn._finish_parallel_adjust_factor_process",
        fake_finish,
    )
    monkeypatch.setattr(
        "alphapilot.systems.data.prepare_cn._maybe_download_adjust_factors",
        fail_sync_factor,
    )
    monkeypatch.setattr(
        "alphapilot.systems.data.prepare_cn._ensure_factor_coverage_for_prices",
        lambda *_args, **_kwargs: 0,
    )

    download_stock_data(
        "2026-01-01",
        "2026-06-13",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="none",
        factor_dir=factor_dir,
        download_state_path=state_path,
        parallel_price_factor=True,
    )

    assert started["codes"] == ["sz.000001"]
    assert started["end_date"] == "2026-06-13"
    assert started["factor_path"] == factor_dir
    assert started["download_starts"] == {"sz.000001": "2026-01-01"}
    record = DownloadStateStore(state_path).get(
        source="baostock_cn",
        adjust_mode="none",
        code="sz.000001",
        raw_dir=raw_dir,
    )
    assert record is not None
    assert record.last_status == "updated"


def test_baostock_parallel_ignored_for_adjusted_download(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw_data_back_adjust"
    state_path = tmp_path / "download_state.csv"
    raw_dir.mkdir()
    fake_bs = _FakeBaostock(trade_rows=[["2026-06-13", "1"]])
    monkeypatch.setattr("alphapilot.systems.data.prepare_cn.bs", fake_bs)

    def fail_start(*_args, **_kwargs):
        raise AssertionError("parallel factor process should not start")

    monkeypatch.setattr(
        "alphapilot.systems.data.prepare_cn._start_parallel_adjust_factor_process",
        fail_start,
    )

    download_stock_data(
        "2026-01-01",
        "2026-06-13",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="backward",
        download_state_path=state_path,
        parallel_price_factor=True,
    )

    assert fake_bs.history_calls
