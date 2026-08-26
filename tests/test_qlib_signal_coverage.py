"""Contracts for typed single-IC coverage and leaderboard ordering."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from alphapilot.systems.backtest.engines.qlib_signal import (
    _single_ic_options_from_params,
    compute_factor_ic_table,
)
from alphapilot.systems.backtest.pipelines.factor_evaluation import (
    _has_single_ic_label,
)
from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams
from alphapilot.systems.backtest.types import SingleICCoverageOptions


def _ranked_panel() -> tuple[pd.DataFrame, pd.Series]:
    index = pd.MultiIndex.from_product(
        [pd.date_range("2024-01-01", periods=3), ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    label_values = np.tile([1.0, 2.0, 3.0, 4.0], 3)
    frame = pd.DataFrame(
        {
            "weak": np.tile([1.0, 2.0, 4.0, 3.0], 3),
            "strong_negative": -label_values,
        },
        index=index,
    )
    return frame, pd.Series(label_values, index=index, name="label")


def test_single_ic_keeps_historical_absolute_ic_ranking_by_default() -> None:
    frame, label = _ranked_panel()

    table = compute_factor_ic_table(frame, label=label)

    assert table["factor_name"].tolist() == ["strong_negative", "weak"]
    assert table.loc[0, "IC"] == pytest.approx(-1.0)
    assert abs(table.loc[1, "IC"]) < abs(table.loc[0, "IC"])


def test_single_ic_preserves_candidate_order_only_when_requested() -> None:
    frame, label = _ranked_panel()
    options = SingleICCoverageOptions(preserve_candidate_order=True)

    table = compute_factor_ic_table(frame, label=label, options=options)

    assert table["factor_name"].tolist() == ["weak", "strong_negative"]


def test_single_ic_typed_options_apply_coverage_and_reverse_index_alignment() -> None:
    frame, label = _ranked_panel()
    frame.iloc[0, 0] = np.inf
    options = SingleICCoverageOptions(
        min_stocks_per_day=3,
        min_days=3,
        min_overlap_ratio=0.8,
    )

    table = compute_factor_ic_table(
        frame[["weak"]],
        label=label.reorder_levels(["instrument", "datetime"]),
        options=options,
    )

    row = table.iloc[0]
    assert bool(row["coverage_valid"]) is True
    assert row["factor_inf_rows"] == 1
    assert row["coverage_rows"] == 11
    assert row["coverage_overlap_ratio"] == pytest.approx(11 / 12)
    assert row["coverage_min_stocks_per_day"] == 3
    assert row["coverage_min_days"] == 3


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"min_stocks_per_day": 1}, ValueError),
        ({"min_stocks_per_day": True}, TypeError),
        ({"min_days": 0}, ValueError),
        ({"min_days": False}, TypeError),
        ({"min_overlap_ratio": -0.01}, ValueError),
        ({"min_overlap_ratio": 1.01}, ValueError),
        ({"min_overlap_ratio": math.nan}, ValueError),
        ({"min_overlap_ratio": math.inf}, ValueError),
        ({"preserve_candidate_order": "false"}, TypeError),
    ],
)
def test_single_ic_options_reject_invalid_values(kwargs, error_type) -> None:  # noqa: ANN001
    with pytest.raises(error_type):
        SingleICCoverageOptions(**kwargs)


def test_single_ic_config_is_typed_and_has_no_hidden_holdout_thresholds() -> None:
    defaults = _single_ic_options_from_params({"label_expression": "$close"})
    assert defaults == SingleICCoverageOptions()

    default_params = QlibYamlParams.defaults_for("combined")
    assert default_params.label_expression
    assert default_params.single_ic_label_expression is None
    assert _has_single_ic_label(default_params) is False

    explicit_label = QlibYamlParams.merge_patch(
        default_params,
        {"single_ic_label_expression": " Ref($close,-6)/Ref($close,-1)-1 "},
    )
    assert explicit_label.single_ic_label_expression == (
        "Ref($close,-6)/Ref($close,-1)-1"
    )
    assert _has_single_ic_label(explicit_label) is True

    params = QlibYamlParams.merge_patch(
        QlibYamlParams.defaults_for("combined"),
        {
            "single_ic_options": {
                "min_stocks_per_day": 20,
                "min_days": 60,
                "min_overlap_ratio": 0.5,
                "preserve_candidate_order": True,
            }
        },
    )

    assert isinstance(params.single_ic_options, SingleICCoverageOptions)
    assert params.single_ic_options == SingleICCoverageOptions(
        min_stocks_per_day=20,
        min_days=60,
        min_overlap_ratio=0.5,
        preserve_candidate_order=True,
    )
    assert _single_ic_options_from_params(params) == params.single_ic_options


def test_single_ic_accepts_unnamed_panel_indexes_and_inclusive_intraday_end() -> None:
    dates = pd.to_datetime(
        [
            "2024-01-02 09:35",
            "2024-01-02 09:35",
            "2024-01-02 15:00",
            "2024-01-02 15:00",
        ]
    )
    index = pd.MultiIndex.from_arrays(
        [dates, ["A", "B", "A", "B"]], names=[None, None]
    )
    factor = pd.DataFrame({"factor": [1.0, 2.0, 1.0, 2.0]}, index=index)
    label = pd.Series([1.0, 2.0, 1.0, 2.0], index=index)

    table = compute_factor_ic_table(
        factor,
        label=label,
        start="2024-01-02",
        end="2024-01-02",
    )

    assert table.loc[0, "coverage_rows"] == 4
    assert table.loc[0, "coverage_days_eligible"] == 1
    assert table.loc[0, "n_periods"] == 2
