"""Offline tests for frequency-aware qlib YAML config + de-hardcoded artifact names."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from alphapilot.systems.backtest.qlib_yaml.generator import render_yaml_text
from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams


# --------------------------------------------------------------------------- #
# Schema: freq field, ann_scaler derivation, time_per_step
# --------------------------------------------------------------------------- #
def test_day_defaults_unchanged() -> None:
    p = QlibYamlParams.defaults_for("baseline")
    assert p.freq == "day"
    assert p.ann_scaler == 252
    assert p.time_per_step == "day"


def test_minute_derives_ann_scaler_and_time_per_step() -> None:
    p = QlibYamlParams.merge_patch(QlibYamlParams.defaults_for("baseline"), {"freq": "5min"})
    assert p.freq == "5min"
    assert p.ann_scaler == 252 * 48
    assert p.time_per_step == "5min"


def test_explicit_ann_scaler_is_respected() -> None:
    p = QlibYamlParams.merge_patch(
        QlibYamlParams.defaults_for("baseline"), {"freq": "5min", "ann_scaler": 300}
    )
    assert p.ann_scaler == 300


def test_freq_alias_normalized_and_invalid_rejected() -> None:
    p = QlibYamlParams.merge_patch(QlibYamlParams.defaults_for("baseline"), {"freq": "5"})
    assert p.freq == "5min"
    with pytest.raises(Exception):  # pydantic ValidationError wraps the ValueError
        QlibYamlParams.merge_patch(QlibYamlParams.defaults_for("baseline"), {"freq": "1min"})


def test_llm_schema_hint_includes_freq() -> None:
    assert "freq" in QlibYamlParams.defaults_for("baseline").llm_schema_hint()


# --------------------------------------------------------------------------- #
# Template rendering
# --------------------------------------------------------------------------- #
def test_day_render_has_no_loader_freq_and_time_per_step_day() -> None:
    text = render_yaml_text(QlibYamlParams.defaults_for("baseline"))
    doc = yaml.safe_load(text)
    assert doc["port_analysis_config"]["executor"]["kwargs"]["time_per_step"] == "day"
    # Daily must not emit a loader ``freq`` key (keeps output byte-identical to before).
    assert list(doc["data_handler_config"]["data_loader"]["kwargs"].keys()) == ["config"]
    assert "ann_scaler: 252" in text


def test_minute_render_emits_freq_and_time_per_step() -> None:
    p = QlibYamlParams.merge_patch(QlibYamlParams.defaults_for("baseline"), {"freq": "5min"})
    text = render_yaml_text(p)
    doc = yaml.safe_load(text)
    assert doc["port_analysis_config"]["executor"]["kwargs"]["time_per_step"] == "5min"
    assert doc["data_handler_config"]["data_loader"]["kwargs"]["freq"] == "5min"
    assert "ann_scaler: {}".format(252 * 48) in text


def test_combined_minute_render_nested_loader_freq() -> None:
    p = QlibYamlParams.merge_patch(QlibYamlParams.defaults_for("combined"), {"freq": "30min"})
    text = render_yaml_text(p)
    doc = yaml.safe_load(text)
    nested = doc["data_handler_config"]["data_loader"]["kwargs"]["dataloader_l"]
    qlib_loader = next(d for d in nested if d["class"].endswith("QlibDataLoader"))
    assert qlib_loader["kwargs"]["freq"] == "30min"


# --------------------------------------------------------------------------- #
# De-hardcoded portfolio artifact lookup
# --------------------------------------------------------------------------- #
def test_portfolio_artifact_lookup_is_freq_tolerant(tmp_path: Path) -> None:
    from alphapilot.systems.backtest.portfolio_artifacts import _find_portfolio_artifact

    # Daily file is found via the legacy name.
    (tmp_path / "report_normal_1day.pkl").write_bytes(b"x")
    assert _find_portfolio_artifact(tmp_path, "report").name == "report_normal_1day.pkl"

    # Intraday file is found when only the minute-tagged name exists.
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    (ws2 / "positions_normal_5min.pkl").write_bytes(b"x")
    assert _find_portfolio_artifact(ws2, "positions").name == "positions_normal_5min.pkl"

    assert _find_portfolio_artifact(tmp_path / "empty", "report") is None


# --------------------------------------------------------------------------- #
# Feedback metric selection is freq-agnostic
# --------------------------------------------------------------------------- #
def test_feedback_metric_selection_any_freq() -> None:
    from alphapilot.modules.alpha_mining.qlib.developer.feedback import _select_important_metrics

    day_index = [
        "1day.excess_return_without_cost.max_drawdown",
        "1day.excess_return_without_cost.information_ratio",
        "1day.excess_return_without_cost.annualized_return",
        "IC",
        "irrelevant.metric",
    ]
    selected = _select_important_metrics(day_index)
    assert selected == [
        "1day.excess_return_without_cost.max_drawdown",
        "1day.excess_return_without_cost.information_ratio",
        "1day.excess_return_without_cost.annualized_return",
        "IC",
    ]

    minute_index = [m.replace("1day.", "5min.") for m in day_index[:3]] + ["IC"]
    selected_min = _select_important_metrics(minute_index)
    assert selected_min[0] == "5min.excess_return_without_cost.max_drawdown"
    assert "IC" in selected_min


# --------------------------------------------------------------------------- #
# FactorDataSpec fingerprint folds in intraday freq only
# --------------------------------------------------------------------------- #
def test_factor_data_spec_fingerprint_freq(tmp_path: Path) -> None:
    from alphapilot.systems.data.factor_h5 import FactorDataSpec

    day = FactorDataSpec(qlib_dir=tmp_path, market="m")
    day_explicit = FactorDataSpec(qlib_dir=tmp_path, market="m", freq="day")
    five = FactorDataSpec(qlib_dir=tmp_path, market="m", freq="5min")

    # Daily fingerprint unchanged whether freq is omitted or explicitly "day".
    assert day.fingerprint() == day_explicit.fingerprint()
    # Intraday must not collide with the daily cache.
    assert five.fingerprint() != day.fingerprint()
