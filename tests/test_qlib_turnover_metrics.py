"""Frequency-safe daily-turnover contracts and Qlib reader integration."""

from __future__ import annotations

import runpy
import shutil
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from alphapilot.systems.backtest.artifacts import build_summary
from alphapilot.systems.backtest.report_metrics import average_daily_turnover
from alphapilot.systems.research.gates import EconomicGateConfig, evaluate_economic_gate


READ_EXP_PATHS = (
    "alphapilot/modules/alpha_mining/qlib/experiment/model_template/read_exp_res.py",
    "alphapilot/systems/backtest/qlib/templates/factor_template/read_exp_res.py",
    "alphapilot/systems/backtest/qlib/templates/model_template/read_exp_res.py",
    "important_data/factor_qlib_templates/read_exp_res.py",
)


def _intraday_report() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "return": [0.0010, 0.0020, 0.0015, 0.0025],
            "cost": [0.0, 0.0, 0.0, 0.0],
            "turnover": [0.1, 0.2, 0.3, 0.4],
            "account": [1001.0, 1003.0, 1004.5, 1007.0],
        },
        index=pd.to_datetime(
            [
                "2024-01-02 09:35",
                "2024-01-02 09:40",
                "2024-01-03 09:35",
                "2024-01-03 09:40",
            ]
        ),
    )


def test_average_daily_turnover_sums_bars_then_averages_days() -> None:
    report = _intraday_report()

    assert average_daily_turnover(report) == pytest.approx(0.5)
    assert report["turnover"].mean() == pytest.approx(0.25)
    assert build_summary(report)["平均日换手"] == pytest.approx(0.5)


def test_average_daily_turnover_keeps_daily_semantics() -> None:
    report = pd.DataFrame(
        {"turnover": [0.1, 0.3]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    assert average_daily_turnover(report) == pytest.approx(0.2)


def test_average_daily_turnover_accepts_named_datetime_multiindex() -> None:
    report = _intraday_report()
    report.index = pd.MultiIndex.from_arrays(
        [report.index, ["portfolio"] * len(report)],
        names=["datetime", "account"],
    )
    assert average_daily_turnover(report) == pytest.approx(0.5)


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -0.1])
def test_average_daily_turnover_rejects_partial_or_invalid_data(bad_value: float) -> None:
    report = _intraday_report()
    report.iloc[0, report.columns.get_loc("turnover")] = bad_value
    with pytest.raises(ValueError):
        average_daily_turnover(report)


def test_research_gate_uses_daily_aggregated_turnover() -> None:
    report = _intraday_report().rename(
        columns={"return": "net_return"}
    )
    report["benchmark_return"] = [0.0, 0.0002, 0.0, 0.0001]
    result = evaluate_economic_gate(
        report,
        baseline_metrics={"annualized_excess": -1.0, "information_ratio": -1.0},
        config=EconomicGateConfig(
            annualization=4,
            min_annualized_excess=-1.0,
            min_information_ratio=-1.0,
            max_drawdown=1.0,
            min_positive_six_month_ratio=0.0,
            max_average_daily_turnover=1.0,
            six_month_trading_days=1,
        ),
    )
    assert result["metrics"]["average_daily_turnover"] == pytest.approx(0.5)


def test_research_gate_rejects_partial_intraday_turnover() -> None:
    report = _intraday_report().rename(columns={"return": "net_return"})
    report["benchmark_return"] = 0.0
    report.iloc[0, report.columns.get_loc("turnover")] = np.nan

    with pytest.raises(ValueError, match="non-finite"):
        evaluate_economic_gate(
            report,
            baseline_metrics={
                "annualized_excess": -1.0,
                "information_ratio": -1.0,
            },
        )


def test_all_qlib_result_readers_are_synchronized() -> None:
    root = Path(__file__).resolve().parents[1]
    contents = [(root / path).read_bytes() for path in READ_EXP_PATHS]
    assert all(content == contents[0] for content in contents[1:])


@pytest.mark.parametrize(
    ("tag", "report", "expected"),
    [
        (
            "1day",
            pd.DataFrame(
                {"turnover": [0.1, 0.3]},
                index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
            ),
            0.2,
        ),
        ("5min", _intraday_report(), 0.5),
    ],
)
def test_result_reader_exports_average_daily_turnover(
    tmp_path, monkeypatch, tag: str, report: pd.DataFrame, expected: float
) -> None:  # noqa: ANN001
    root = Path(__file__).resolve().parents[1]
    reader = tmp_path / "read_exp_res.py"
    shutil.copy2(root / READ_EXP_PATHS[0], reader)
    calls: list[str] = []

    class FakeRecorder:
        info = {"end_time": 1}

        @staticmethod
        def list_metrics():
            return {"IC": 0.02}

        @staticmethod
        def load_object(key: str):
            calls.append(key)
            if key == f"portfolio_analysis/report_normal_{tag}.pkl":
                return report
            raise FileNotFoundError(key)

    recorder = FakeRecorder()

    class FakeR:
        @staticmethod
        def list_experiments():
            return ["experiment"]

        @staticmethod
        def list_recorders(*, experiment_name):  # noqa: ANN001
            assert experiment_name == "experiment"
            return ["recorder"]

        @staticmethod
        def get_recorder(*, recorder_id, experiment_name):  # noqa: ANN001
            assert recorder_id == "recorder"
            assert experiment_name == "experiment"
            return recorder

    qlib_module = ModuleType("qlib")
    qlib_module.init = lambda: None
    workflow_module = ModuleType("qlib.workflow")
    workflow_module.R = FakeR
    monkeypatch.setitem(sys.modules, "qlib", qlib_module)
    monkeypatch.setitem(sys.modules, "qlib.workflow", workflow_module)

    runpy.run_path(str(reader), run_name="__main__")

    metrics = pd.read_csv(tmp_path / "qlib_res.csv", index_col=0).iloc[:, 0]
    assert metrics["average_daily_turnover"] == pytest.approx(expected)
    pd.testing.assert_frame_equal(pd.read_pickle(tmp_path / "ret.pkl"), report)
    expected_probe = f"portfolio_analysis/report_normal_{tag}.pkl"
    assert expected_probe in calls
