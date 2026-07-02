"""Phase 3 unit tests: executor reconcile / intent translation + TargetPortfolio bridge."""

from __future__ import annotations

from alphapilot.systems.live.executor import orders_from_intents, reconcile
from alphapilot.systems.live.oms import OMS
from alphapilot.systems.live.targets import TargetPortfolio
from alphapilot.systems.live.types import Account, Direction, Position


def _oms(cash=1_000_000.0, positions=None) -> OMS:
    oms = OMS()
    oms.on_account(Account(account_id="acc", balance=cash, available=cash))
    for code, (vol, yd) in (positions or {}).items():
        from alphapilot.systems.live.types import normalize_symbol
        c, ex = normalize_symbol(code)
        oms.on_position(Position(code=c, exchange=ex, volume=vol, yd_volume=yd))
    return oms


def test_reconcile_buys_sells_and_liquidates() -> None:
    target = TargetPortfolio(
        date="2026-07-01",
        holdings={"SH600000": 1000, "SZ000001": 500},
        prices={"SH600000": 10.0, "SZ000001": 20.0},
    )
    oms = _oms(positions={"SH600000": (300, 300), "SZ000002": (200, 200)})  # 000002 not in target
    reqs = {r.code: r for r in reconcile(target, oms, lot_size=100)}

    assert reqs["600000"].direction == Direction.LONG and reqs["600000"].volume == 700
    assert reqs["000001"].direction == Direction.LONG and reqs["000001"].volume == 500
    assert reqs["000002"].direction == Direction.SHORT and reqs["000002"].volume == 200  # liquidated


def test_reconcile_sell_capped_by_t_plus_one() -> None:
    target = TargetPortfolio(date="2026-07-01", holdings={}, prices={})
    oms = _oms(positions={"SH600000": (1000, 300)})   # hold 1000 but only 300 sellable today
    reqs = reconcile(target, oms, lot_size=100)
    assert len(reqs) == 1
    assert reqs[0].direction == Direction.SHORT and reqs[0].volume == 300


def test_reconcile_skips_sub_lot_delta() -> None:
    target = TargetPortfolio(date="2026-07-01", holdings={"SH600000": 350}, prices={"SH600000": 10.0})
    oms = _oms(positions={"SH600000": (300, 300)})    # delta 50 < 1 lot -> no order
    assert reconcile(target, oms, lot_size=100) == []


def test_orders_from_intents() -> None:
    from alphapilot.systems.timing.base import OrderIntent

    oms = _oms(cash=100_000.0, positions={"SZ000001": (500, 500)})
    intents = [
        OrderIntent(datetime="d", instrument="SH600000", action="buy", quantity=300),
        OrderIntent(datetime="d", instrument="SZ000001", action="close"),
    ]
    reqs = {r.code: r for r in orders_from_intents(intents, oms, prices={"SH600000": 10.0}, lot_size=100)}
    assert reqs["600000"].direction == Direction.LONG and reqs["600000"].volume == 300
    assert reqs["000001"].direction == Direction.SHORT and reqs["000001"].volume == 500


def test_orders_from_intents_target_percent() -> None:
    from alphapilot.systems.timing.base import OrderIntent

    oms = _oms(cash=100_000.0)   # equity 100k, price 10 => 30% => 3000 shares
    intents = [OrderIntent(datetime="d", instrument="SH600000", action="target_percent", target_percent=0.3)]
    reqs = orders_from_intents(intents, oms, prices={"SH600000": 10.0}, lot_size=100)
    assert len(reqs) == 1 and reqs[0].volume == 3000


def test_to_target_portfolio_bridge() -> None:
    import pandas as pd

    from alphapilot.systems.backtest.live.service import to_target_portfolio
    from alphapilot.systems.backtest.live.types import DailyTradeResult, PortfolioState

    holdings = pd.DataFrame([
        {"instrument": "SH600000", "amount": 1000, "price": 10.0},
        {"instrument": "SZ000001", "amount": 500, "price": 20.0},
    ])
    result = DailyTradeResult(
        date="2026-07-01", trades=None, holdings=holdings, scores=[],
        new_state=PortfolioState(date="2026-07-01", cash=1000.0, positions={}),
        info={"strategy": "my_strat"},
    )
    target = to_target_portfolio(result)
    assert target.source == "my_strat"
    assert target.holdings == {"SH600000": 1000.0, "SZ000001": 500.0}
    assert target.prices["SH600000"] == 10.0
