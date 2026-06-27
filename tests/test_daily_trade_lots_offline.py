"""Tier 1 (offline): board-lot (trade_unit) handling for the daily-trade rebalance.

Pure-function coverage for the lot constraint added to ``live/rebalance.py`` + the
``QlibYamlParams.trade_unit`` schema field — no market data, no qlib backtest.
"""

from __future__ import annotations

from alphapilot.systems.backtest.live.rebalance import (
    _lot_size,
    _round_to_lot,
    build_exchange_kwargs,
)
from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams


def test_trade_unit_defaults_to_one_lot() -> None:
    params = QlibYamlParams.defaults_for("combined")
    assert params.trade_unit == 100
    assert _lot_size(params) == 100


def test_round_to_lot_floors_to_whole_lots() -> None:
    assert _round_to_lot(3810.67, 100) == 3800
    assert _round_to_lot(150, 100) == 100
    assert _round_to_lot(99, 100) == 0  # sub-lot drops to zero
    assert _round_to_lot(2000, 100) == 2000


def test_round_to_lot_passthrough_when_disabled() -> None:
    assert _round_to_lot(3810.67, 0) == 3810.67
    assert _lot_size(QlibYamlParams.defaults_for("combined").model_copy(update={"trade_unit": 0})) == 0


def test_build_exchange_kwargs_includes_trade_unit_only_when_positive() -> None:
    params = QlibYamlParams.defaults_for("combined")
    assert build_exchange_kwargs(params)["trade_unit"] == 100

    disabled = params.model_copy(update={"trade_unit": 0})
    assert "trade_unit" not in build_exchange_kwargs(disabled)

    custom = params.model_copy(update={"trade_unit": 200})
    assert build_exchange_kwargs(custom)["trade_unit"] == 200


def test_trade_unit_is_inert_for_qrun_templates() -> None:
    # Guard the isolation promise: the qrun (mining / backtest) templates must NOT reference
    # trade_unit, so adding the schema field cannot change factor mining / backtest configs.
    from pathlib import Path

    import alphapilot.systems.backtest.qlib_yaml as qy

    tpl_dir = Path(qy.__file__).parent / "templates"
    for tpl in tpl_dir.glob("*.j2"):
        assert "trade_unit" not in tpl.read_text(encoding="utf-8"), f"{tpl.name} references trade_unit"
