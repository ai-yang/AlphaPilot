"""Contracts shared by the GP, RL, and AFF AlphaForge miners."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import alphapilot.modules.alphaforge  # noqa: F401 - installs vendored paths
from alphapilot.modules.alphaforge.data_adapter import (
    LoadedTrainingData,
    TargetSpec,
    TrainingSpec,
    get_train_data,
)


def test_training_spec_exact_dates_override_legacy_years() -> None:
    exact = TrainingSpec.resolve(
        train_start=True,  # ignored because the exact pair is authoritative
        train_end_year="ignored",  # type: ignore[arg-type]
        train_start_date=" 2017-06-06 ",
        train_end_date="2023-11-30",
    )
    legacy = TrainingSpec.resolve(train_start=2012, train_end_year=2015)

    assert exact.requested_range == ("2017-06-06", "2023-11-30")
    assert exact.source == "explicit_dates"
    assert legacy.requested_range == ("2012-01-01", "2015-12-31")
    assert legacy.source == "legacy_years"


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2020-01-01", None, "provided together"),
        (None, "2020-12-31", "provided together"),
        ("", "2020-12-31", "non-empty ISO date"),
        ("2020-01-01", " ", "non-empty ISO date"),
        ("2020-1-1", "2020-12-31", "YYYY-MM-DD"),
        ("2020-12-31", "2020-01-01", "cannot exceed"),
    ],
)
def test_training_spec_rejects_partial_blank_invalid_or_reversed_exact_dates(
    start: str | None,
    end: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TrainingSpec.resolve(train_start_date=start, train_end_date=end)


@pytest.mark.parametrize("value", [True, "2020", 0, 10_000])
def test_training_spec_validates_legacy_years(value: object) -> None:
    with pytest.raises(ValueError, match="year"):
        TrainingSpec.resolve(train_end_year=value)  # type: ignore[arg-type]


def test_target_spec_normalizes_before_loading_and_derives_future_padding() -> None:
    target = TargetSpec(5, " CLOSE ")

    assert target.horizon == 5
    assert target.price == "close"
    assert target.required_future_days == 6
    assert target.qlib_expression == "Ref($close,-6)/Ref($close,-1)-1"
    assert str(target.build_expression()) == "((Ref(close,-6)/Ref(close,-1))-1)"

    long_horizon = TargetSpec(60, "vwap")
    assert long_horizon.required_future_days == 61


@pytest.mark.parametrize(
    ("horizon", "price"),
    [(True, "close"), (0, "close"), (-1, "close"), (5, ""), (5, "open")],
)
def test_target_spec_rejects_invalid_contract(horizon: object, price: str) -> None:
    with pytest.raises(ValueError):
        TargetSpec(horizon, price)  # type: ignore[arg-type]


def test_get_train_data_builds_only_one_slice_with_target_padding(monkeypatch) -> None:
    from alphapilot.modules.alphaforge import data_adapter

    calls: list[dict] = []
    stock_data = SimpleNamespace(
        effective_start_time="2017-06-07",
        effective_end_time="2023-11-29",
    )

    def fake_build_stock_data(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return stock_data

    monkeypatch.setattr(data_adapter, "build_stock_data", fake_build_stock_data)
    training = TrainingSpec.resolve(
        train_start_date="2017-06-06",
        train_end_date="2023-11-30",
    )
    target = TargetSpec(5, "close")
    loaded = get_train_data(
        SimpleNamespace(),
        training_spec=training,
        target_spec=target,
        instruments="test_market",
        qlib_dir="/provider",
        device=object(),
    )

    assert len(calls) == 1
    assert calls[0]["start_time"] == "2017-06-06"
    assert calls[0]["end_time"] == "2023-11-30"
    assert calls[0]["max_future_days"] == 6
    assert loaded.data is stock_data
    assert loaded.data_split_metadata() == {
        "train": {
            "requested": ["2017-06-06", "2023-11-30"],
            "effective": ["2017-06-07", "2023-11-29"],
        }
    }


def test_stock_data_exposes_the_calendar_range_effectively_used(monkeypatch) -> None:
    from qlib import data as qlib_data
    from qlib.data.dataset import loader as qlib_loader
    from alphagen_qlib.stock_data import StockData

    calendar = np.asarray(pd.bdate_range("2024-01-01", periods=10))

    class FakeDataAPI:
        @staticmethod
        def calendar(*, freq):  # noqa: ANN001, ANN205
            assert freq == "day"
            return calendar

    class FakeLoader:
        def __init__(self, *, config, freq):  # noqa: ANN001
            assert config == ["$close"]
            assert freq == "day"

        def load(self, instrument, start, end):  # noqa: ANN001, ANN201
            assert instrument == "market"
            assert pd.Timestamp(start) == pd.Timestamp(calendar[0])
            assert pd.Timestamp(end) == pd.Timestamp(calendar[-1])
            return "loaded"

    monkeypatch.setattr(qlib_data, "D", FakeDataAPI)
    monkeypatch.setattr(qlib_loader, "QlibDataLoader", FakeLoader)
    stock = StockData.__new__(StockData)
    stock._instrument = "market"
    stock._start_time = "2020-01-01"
    stock._end_time = "2030-01-01"
    stock.max_backtrack_days = 2
    stock.max_future_days = 1
    stock.freq = "day"
    stock._effective_start_time = None
    stock._effective_end_time = None

    assert stock._load_exprs(["$close"]) == "loaded"
    assert stock.effective_start_time == "2024-01-03"
    assert stock.effective_end_time == "2024-01-11"


def _runner_classes():
    from alphapilot.modules.alphaforge_aff.miner import AFFMiner
    from alphapilot.modules.alphaforge_search.runners.gp_runner import GPRunner
    from alphapilot.modules.alphaforge_search.runners.rl_runner import RLRunner

    return GPRunner, RLRunner, AFFMiner


@pytest.mark.parametrize("runner_class", _runner_classes())
def test_all_miners_resolve_the_same_contract_before_run(runner_class) -> None:  # noqa: ANN001
    runner = runner_class(
        context=SimpleNamespace(),
        train_end_year="ignored",
        train_start_date="2018-01-02",
        train_end_date="2021-12-30",
        target_horizon=5,
        target_price=" CLOSE ",
    )

    assert runner.training_spec == TrainingSpec(
        "2018-01-02", "2021-12-30", "explicit_dates"
    )
    assert runner.target_spec == TargetSpec(5, "close")


@pytest.mark.parametrize("runner_class", _runner_classes())
def test_all_miners_reject_invalid_contract_in_constructor(runner_class) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="provided together"):
        runner_class(context=SimpleNamespace(), train_start_date="2020-01-01")
    with pytest.raises(ValueError, match="positive integer"):
        runner_class(context=SimpleNamespace(), target_horizon=0)


def test_all_miner_run_paths_load_training_only() -> None:
    for runner_class in _runner_classes():
        source = inspect.getsource(runner_class.run)
        assert "get_train_data(" in source
        assert "get_data_splits" not in source


def test_rl_metadata_records_requested_and_effective_train_only(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    from alphapilot.modules.alphaforge_search import module as search_module
    from alphapilot.modules.alphaforge_search.runners import rl_runner

    class FakeRunner:
        def __init__(self, **kwargs):  # noqa: ANN003
            training = TrainingSpec.resolve(
                train_end_year=kwargs["train_end_year"],
                train_start_date=kwargs["train_start_date"],
                train_end_date=kwargs["train_end_date"],
            )
            target = TargetSpec(kwargs["target_horizon"], kwargs["target_price"])
            self.training_data = LoadedTrainingData(
                data=object(),
                training_spec=training,
                target_spec=target,
                effective_start_date="2017-06-07",
                effective_end_date="2023-11-29",
            )
        def run(self):  # noqa: ANN201
            return [], []

    monkeypatch.setattr(rl_runner, "RLRunner", FakeRunner)
    module = search_module.AlphaForgeSearchModule()
    module.context = SimpleNamespace(
        config=SimpleNamespace(
            data=SimpleNamespace(qlib_data_dir=str(tmp_path / "provider"))
        )
    )
    captured: dict = {}

    def fake_emit(_exprs, _scores, **kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(module, "_emit", fake_emit)

    module.mine_rl(
        train_end_year=1900,
        train_start_date="2017-06-06",
        train_end_date="2023-11-30",
        target_horizon=5,
        target_price=" CLOSE ",
        qlib_dir=str(tmp_path / "provider"),
        save=False,
    )

    metadata = captured["research_metadata"]
    assert metadata["data_split"] == {
        "train": {
            "requested": ["2017-06-06", "2023-11-30"],
            "effective": ["2017-06-07", "2023-11-29"],
        }
    }
    assert "validation" not in metadata["data_split"]
    assert "test" not in metadata["data_split"]
    assert metadata["target_expression"] == "Ref($close,-6)/Ref($close,-1)-1"
    assert metadata["search_config"]["training_source"] == "explicit_dates"
    assert "train_end_year" not in metadata["search_config"]
