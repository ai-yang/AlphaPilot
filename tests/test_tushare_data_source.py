from __future__ import annotations

import pandas as pd

from alphapilot.adapters import get_data_source
from alphapilot.adapters.builtin.data_source.tushare_cn import TushareDataSourceAdapter
from alphapilot.systems.data.download_state import DownloadStateStore
from alphapilot.systems.data.prepare_tushare import (
    TUSHARE_SOURCE,
    baostock_to_tushare,
    download_tushare_data,
    tushare_to_baostock,
)


class _FakeTushareClient:
    def __init__(self, *, daily_rows=None, factor_rows=None, trade_rows=None):
        self.daily_rows = daily_rows or []
        self.factor_rows = factor_rows or []
        self.trade_rows = trade_rows or []
        self.daily_calls = []
        self.factor_calls = []

    def trade_cal(self, exchange, start_date, end_date):
        return pd.DataFrame(self.trade_rows, columns=["cal_date", "is_open"])

    def daily(self, ts_code, start_date, end_date):
        self.daily_calls.append(
            {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return pd.DataFrame(
            self.daily_rows,
            columns=[
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
                "vol",
                "amount",
            ],
        )

    def adj_factor(self, ts_code, start_date, end_date):
        self.factor_calls.append(
            {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return pd.DataFrame(
            self.factor_rows,
            columns=["ts_code", "trade_date", "adj_factor"],
        )


def test_tushare_code_conversion():
    assert baostock_to_tushare("sz.000001") == "000001.SZ"
    assert baostock_to_tushare("SH600000") == "600000.SH"
    assert tushare_to_baostock("000001.SZ") == "sz.000001"
    assert tushare_to_baostock("600000.SH") == "sh.600000"


def test_tushare_download_writes_normalized_price_factor_and_state(tmp_path):
    raw_dir = tmp_path / "tushare" / "raw_data_no_adjust"
    factor_dir = tmp_path / "tushare" / "adjust_factors"
    state_path = tmp_path / "tushare" / "download_state.csv"
    fake = _FakeTushareClient(
        trade_rows=[
            ["20260612", 1],
            ["20260613", 0],
        ],
        daily_rows=[
            [
                "000001.SZ",
                "20260612",
                10,
                11,
                9,
                10.5,
                10.1,
                0.4,
                3.96,
                12345,
                67890,
            ],
        ],
        factor_rows=[
            ["000001.SZ", "20260611", 2.0],
            ["000001.SZ", "20260612", 4.0],
        ],
    )

    codes = download_tushare_data(
        "2026-06-10",
        "2026-06-13",
        raw_dir,
        symbols=["000001.SZ"],
        adjust_mode="none",
        factor_dir=factor_dir,
        download_state_path=state_path,
        client=fake,
    )

    assert codes == ["sz.000001"]
    price_df = pd.read_csv(raw_dir / "sz000001.csv")
    assert list(price_df.columns) == [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turn",
        "tradestatus",
        "pctChg",
        "peTTM",
        "pbMRQ",
        "psTTM",
        "pcfNcfTTM",
        "isST",
    ]
    assert price_df.loc[0, "date"] == "2026-06-12"
    assert price_df.loc[0, "code"] == "sz000001"
    assert price_df.loc[0, "preclose"] == 10.1
    assert price_df.loc[0, "volume"] == 12345
    assert price_df.loc[0, "pctChg"] == 3.96

    factor_df = pd.read_csv(factor_dir / "sz000001.csv")
    assert list(factor_df.columns) == [
        "code",
        "dividOperateDate",
        "adjustFactor",
        "foreAdjustFactor",
        "backAdjustFactor",
    ]
    assert factor_df["dividOperateDate"].tolist() == ["2026-06-11", "2026-06-12"]
    assert factor_df["foreAdjustFactor"].tolist() == [0.5, 1.0]
    assert factor_df["backAdjustFactor"].tolist() == [2.0, 4.0]

    record = DownloadStateStore(state_path).get(
        source=TUSHARE_SOURCE,
        adjust_mode="none",
        code="sz.000001",
        raw_dir=raw_dir,
    )
    assert record is not None
    assert record.data_end_date == "2026-06-12"
    assert record.checked_until == "2026-06-13"
    assert record.last_status == "updated"
    assert fake.daily_calls[0]["ts_code"] == "000001.SZ"


def test_tushare_download_state_source_isolated_from_baostock(tmp_path):
    raw_dir = tmp_path / "tushare" / "raw_data_no_adjust"
    factor_dir = tmp_path / "tushare" / "adjust_factors"
    state_path = tmp_path / "tushare" / "download_state.csv"
    raw_dir.mkdir(parents=True)
    store = DownloadStateStore(state_path)
    store.upsert(
        source="baostock_cn",
        adjust_mode="none",
        code="sz.000001",
        raw_dir=raw_dir,
        data_end_date="2026-06-13",
        checked_until="2026-06-13",
        last_status="seed",
    )
    store.save()
    fake = _FakeTushareClient(
        trade_rows=[["20260612", 1]],
        daily_rows=[
            ["000001.SZ", "20260612", 1, 1, 1, 1, 1, 0, 0, 100, 100],
        ],
        factor_rows=[["000001.SZ", "20260612", 1.0]],
    )

    download_tushare_data(
        "2026-06-10",
        "2026-06-13",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="none",
        factor_dir=factor_dir,
        download_state_path=state_path,
        client=fake,
    )

    assert fake.daily_calls
    tushare_record = DownloadStateStore(state_path).get(
        source=TUSHARE_SOURCE,
        adjust_mode="none",
        code="sz.000001",
        raw_dir=raw_dir,
    )
    assert tushare_record is not None
    assert tushare_record.last_status == "updated"


def test_tushare_no_trading_days_skips_daily_request(tmp_path):
    raw_dir = tmp_path / "tushare" / "raw_data_no_adjust"
    factor_dir = tmp_path / "tushare" / "adjust_factors"
    state_path = tmp_path / "tushare" / "download_state.csv"
    raw_dir.mkdir(parents=True)
    store = DownloadStateStore(state_path)
    store.upsert(
        source=TUSHARE_SOURCE,
        adjust_mode="none",
        code="sz.000001",
        raw_dir=raw_dir,
        data_end_date="2026-06-12",
        checked_until="2026-06-12",
        last_status="seed",
    )
    store.save()
    fake = _FakeTushareClient(
        trade_rows=[
            ["20260613", 0],
            ["20260614", 0],
        ],
    )

    download_tushare_data(
        "2026-06-10",
        "2026-06-14",
        raw_dir,
        symbols=["sz.000001"],
        adjust_mode="none",
        factor_dir=factor_dir,
        download_state_path=state_path,
        client=fake,
    )

    record = DownloadStateStore(state_path).get(
        source=TUSHARE_SOURCE,
        adjust_mode="none",
        code="sz.000001",
        raw_dir=raw_dir,
    )
    assert record is not None
    assert record.checked_until == "2026-06-14"
    assert record.last_status == "no_trading_days"
    assert fake.daily_calls == []


def test_tushare_adapter_is_registered():
    assert isinstance(get_data_source("tushare_cn"), TushareDataSourceAdapter)
