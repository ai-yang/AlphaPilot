from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import yaml

from alphapilot.systems.backtest.workspace import QlibFBWorkspace


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    import alphapilot.systems.backtest.scoring_model_export as export
    import alphapilot.systems.backtest.workspace as workspace_module

    environment = SimpleNamespace(prepare=Mock(), run=Mock())
    monkeypatch.setattr(
        workspace_module, "QTDockerEnv", lambda **kwargs: environment
    )
    monkeypatch.setattr(export, "export_scoring_model_artifacts", Mock())
    return SimpleNamespace(workspace_path=tmp_path)


@pytest.mark.parametrize(
    "record_class",
    [
        "SignalRecord",
        "SigAnaRecord",
        "PortAnaRecord",
        "qlib.workflow.record_temp.PortAnaRecord",
    ],
)
def test_workspace_requires_portfolio_only_when_requested(
    workspace, record_class: str
) -> None:
    path = workspace.workspace_path
    (path / "conf.yaml").write_text(
        yaml.safe_dump({"task": {"record": [{"class": record_class}]}})
    )
    expected = pd.Series({"IC": 0.02, "Rank IC": 0.03}, name="0")
    expected.to_csv(path / "qlib_res.csv")

    actual = QlibFBWorkspace.execute(workspace)

    if record_class in ("SignalRecord", "SigAnaRecord"):
        pd.testing.assert_series_equal(actual, expected)
    else:
        assert actual is None


def test_signal_workspace_still_requires_metrics(workspace) -> None:
    (workspace.workspace_path / "conf.yaml").write_text(
        yaml.safe_dump({"task": {"record": [{"class": "SigAnaRecord"}]}})
    )
    assert QlibFBWorkspace.execute(workspace) is None


def test_portfolio_workspace_reads_returns_and_metrics(workspace, monkeypatch) -> None:
    import alphapilot.systems.backtest.workspace as workspace_module

    path = workspace.workspace_path
    (path / "custom.yaml").write_text(
        yaml.safe_dump({"task": {"record": [{"class": "PortAnaRecord"}]}})
    )
    expected = pd.Series({"IC": 0.02}, name="0")
    expected.to_csv(path / "qlib_res.csv")
    returns = pd.DataFrame({"return": [0.01, -0.02]})
    returns.to_pickle(path / "ret.pkl")
    log_object = Mock()
    monkeypatch.setattr(workspace_module.logger, "log_object", log_object)

    actual = QlibFBWorkspace.execute(workspace, qlib_config_name="custom.yaml")

    pd.testing.assert_series_equal(actual, expected)
    log_object.assert_called_once()
    pd.testing.assert_frame_equal(log_object.call_args.args[0], returns)
    assert log_object.call_args.kwargs["tag"] == "Quantitative Backtesting Chart"


def test_unspecified_records_keep_existing_portfolio_requirement(workspace) -> None:
    path = workspace.workspace_path
    (path / "conf.yaml").write_text(yaml.safe_dump({"task": {}}))
    pd.Series({"IC": 0.02}, name="0").to_csv(path / "qlib_res.csv")
    assert QlibFBWorkspace.execute(workspace) is None
