from __future__ import annotations

import pytest


@pytest.mark.parametrize("frequency", ["1day", "5min"])
def test_feedback_selects_cost_aware_predictive_metrics_at_any_frequency(
    frequency: str,
) -> None:
    from alphapilot.modules.alpha_mining.qlib.developer.feedback import (
        _select_important_metrics,
    )

    gross = [
        f"{frequency}.excess_return_without_cost.max_drawdown",
        f"{frequency}.excess_return_without_cost.information_ratio",
        f"{frequency}.excess_return_without_cost.annualized_return",
    ]
    with_cost = [
        f"{frequency}.excess_return_with_cost.max_drawdown",
        f"{frequency}.excess_return_with_cost.information_ratio",
        f"{frequency}.excess_return_with_cost.annualized_return",
    ]
    predictive = ["IC", "ICIR", "Rank IC", "Rank ICIR", "RankIC", "RankICIR"]
    index = [
        "irrelevant.metric",
        *reversed(with_cost),
        f"{frequency}.turnover",
        *reversed(gross),
        "average_daily_turnover",
        *reversed(predictive),
    ]

    selected = _select_important_metrics(index)
    assert selected == gross + with_cost + predictive + ["average_daily_turnover"]
    assert f"{frequency}.turnover" not in selected
