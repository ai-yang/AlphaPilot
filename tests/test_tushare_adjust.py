from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from alphapilot.systems.data.prepare_tushare import download_cn_data


class FakeTushareClient:
    def __init__(self) -> None:
        self.daily_calls: list[dict[str, str]] = []
        self.adj_calls: list[dict[str, str]] = []
        self.pro_bar_calls: list[dict[str, str]] = []

    def trade_cal(self, exchange: str, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"cal_date": "20260610", "is_open": 1},
            {"cal_date": "20260611", "is_open": 1},
        ]
        return pd.DataFrame(row for row in rows if start_date <= row["cal_date"] <= end_date)

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.daily_calls.append(
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}
        )
        return self._bars(open_values=[10.0, 20.0], close_values=[11.0, 22.0])

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.adj_calls.append(
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}
        )
        return pd.DataFrame(
            [
                {"trade_date": "20260610", "adj_factor": 1.0},
                {"trade_date": "20260611", "adj_factor": 2.0},
            ]
        )

    def pro_bar(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
        adj: str,
        freq: str,
        asset: str,
    ) -> pd.DataFrame:
        self.pro_bar_calls.append(
            {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "adj": adj,
                "freq": freq,
                "asset": asset,
            }
        )
        if adj == "qfq":
            return self._bars(open_values=[5.0, 20.0], close_values=[5.5, 22.0])
        if adj == "hfq":
            return self._bars(open_values=[10.0, 40.0], close_values=[11.0, 44.0])
        raise AssertionError(f"unexpected adj={adj!r}")

    @staticmethod
    def _bars(open_values: list[float], close_values: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260610",
                    "open": open_values[0],
                    "high": open_values[0] + 2,
                    "low": open_values[0] - 1,
                    "close": close_values[0],
                    "pre_close": open_values[0],
                    "vol": 1000,
                    "amount": 10000,
                    "pct_chg": 10.0,
                },
                {
                    "trade_date": "20260611",
                    "open": open_values[1],
                    "high": open_values[1] + 4,
                    "low": open_values[1] - 2,
                    "close": close_values[1],
                    "pre_close": close_values[0],
                    "vol": 2000,
                    "amount": 20000,
                    "pct_chg": 100.0,
                },
            ]
        )


@pytest.mark.parametrize(
    ("mode", "expected_adj", "expected_open", "expected_close", "expected_factor"),
    [
        # adj_factor = [1.0, 2.0]; qfq factor = adj / latest = [0.5, 1.0],
        # hfq factor = adj = [1.0, 2.0].
        ("forward", "qfq", [5.0, 20.0], [5.5, 22.0], [0.5, 1.0]),
        ("backward", "hfq", [10.0, 40.0], [11.0, 44.0], [1.0, 2.0]),
    ],
)
def test_tushare_download_adjusted_mode_uses_pro_bar_directly(
    tmp_path: Path,
    mode: str,
    expected_adj: str,
    expected_open: list[float],
    expected_close: list[float],
    expected_factor: list[float],
) -> None:
    client = FakeTushareClient()
    adjusted_dir = tmp_path / f"raw_{mode}"
    factor_dir = tmp_path / "factors"

    codes = download_cn_data(
        start_date="2026-06-10",
        end_date="2026-06-11",
        data_dir=adjusted_dir,
        symbols=["sz.000001"],
        factor_dir=factor_dir,
        adjust_mode=mode,
        client=client,
    )

    assert codes == ["sz.000001"]
    adjusted = pd.read_csv(adjusted_dir / "sz000001.csv")

    assert adjusted["open"].tolist() == expected_open
    assert adjusted["close"].tolist() == expected_close
    # Adjusted bars now carry the matching per-day adjust factor.
    assert adjusted["factor"].tolist() == expected_factor
    assert client.daily_calls == []
    assert len(client.pro_bar_calls) == 1
    assert client.pro_bar_calls[0]["adj"] == expected_adj
    # adj_factor is fetched and persisted in every mode now.
    assert len(client.adj_calls) == 1
    assert (factor_dir / "sz000001.csv").exists()
    assert not (tmp_path / "raw_none" / "sz000001.csv").exists()
