"""Tier 1 (offline): strategy creation from factor names.

Builds a strategy asset from factors already in the zoo and verifies the
record round-trips through the strategy store (create / list / get / delete).
No backtest here — that lives in the slow tier.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def seeded(engine):
    factor = engine.get_system("factor")
    factor.add_factor("sf1", "Mean($close,5)/$close-1")
    factor.add_factor("sf2", "$close/$open-1")
    return engine


def test_create_strategy_from_factors(seeded) -> None:
    strategy = seeded.get_system("strategy")
    record = strategy.create_strategy_from_factors(
        strategy_name="s1", factor_names=["sf1", "sf2"]
    )
    assert record.strategy_name == "s1"
    # Factor names resolve to their DSL expressions.
    assert record.factor_formulas == ["Mean($close,5)/$close-1", "$close/$open-1"]
    assert record.metadata.get("factor_names") == ["sf1", "sf2"]


def test_strategy_list_get_delete(seeded) -> None:
    strategy = seeded.get_system("strategy")
    strategy.create_strategy_from_factors(strategy_name="s1", factor_names=["sf1"])
    strategy.create_strategy_from_factors(strategy_name="s2", factor_names=["sf2"])

    names = {r.strategy_name for r in strategy.list_strategy_records()}
    assert {"s1", "s2"} <= names

    got = strategy.get_strategy("s1")
    assert got is not None and got.strategy_name == "s1"

    assert strategy.delete_strategy("s2") is True
    names_after = {r.strategy_name for r in strategy.list_strategy_records()}
    assert "s2" not in names_after


def test_create_with_unknown_factor_is_rejected(seeded) -> None:
    strategy = seeded.get_system("strategy")
    with pytest.raises(Exception):
        strategy.create_strategy_from_factors(
            strategy_name="bad", factor_names=["does_not_exist"]
        )
