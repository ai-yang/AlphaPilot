"""Phase 1 unit tests: PositionBook (T+1 / frozen) and OMS projection."""

from __future__ import annotations

from alphapilot.systems.live.oms import OMS
from alphapilot.systems.live.position import PositionBook
from alphapilot.systems.live.types import (
    Account,
    Direction,
    Exchange,
    Order,
    OrderStatus,
    Trade,
)

KEY = "600000.SSE"


def _sell_order(order_id: str, volume: float, traded: float, status: OrderStatus) -> Order:
    return Order(order_id=order_id, code="600000", exchange=Exchange.SSE,
                 direction=Direction.SHORT, volume=volume, traded=traded, status=status)


def _sell_trade(trade_id: str, volume: float, price: float = 10.0) -> Trade:
    return Trade(trade_id=trade_id, order_id="s1", code="600000", exchange=Exchange.SSE,
                 direction=Direction.SHORT, volume=volume, price=price)


def _buy_trade(trade_id: str, volume: float, price: float) -> Trade:
    return Trade(trade_id=trade_id, order_id="b1", code="600000", exchange=Exchange.SSE,
                 direction=Direction.LONG, volume=volume, price=price)


# --------------------------------------------------------------------------- #
# PositionBook
# --------------------------------------------------------------------------- #
def test_buy_today_is_not_sellable_until_roll() -> None:
    book = PositionBook()
    book.seed("600000", volume=600, price=9.0)          # yesterday's holding
    assert book.available(KEY) == 600

    book.update_trade(_buy_trade("t1", volume=400, price=11.0))
    pos = book.get(KEY)
    assert pos.volume == 1000
    assert pos.yd_volume == 600                          # today's buy not sellable
    assert book.available(KEY) == 600
    # weighted average cost: (600*9 + 400*11) / 1000 = 9.8
    assert round(pos.price, 4) == 9.8

    book.roll_new_day()
    assert book.available(KEY) == 1000                   # now all sellable


def test_working_sell_freezes_shares_and_fills_consistently() -> None:
    book = PositionBook()
    book.seed("600000", volume=600, price=9.0)

    # place a working sell for 100 -> 100 frozen, 500 available
    book.update_order(_sell_order("s1", volume=100, traded=0, status=OrderStatus.NOTTRADED))
    assert book.get(KEY).frozen == 100
    assert book.available(KEY) == 500

    # partial fill 40: totals drop, remaining 60 still frozen
    book.update_trade(_sell_trade("f1", 40))
    book.update_order(_sell_order("s1", volume=100, traded=40, status=OrderStatus.PARTTRADED))
    assert book.get(KEY).yd_volume == 560
    assert book.get(KEY).frozen == 60
    assert book.available(KEY) == 500

    # fill the rest: order terminal, frozen released
    book.update_trade(_sell_trade("f2", 60))
    book.update_order(_sell_order("s1", volume=100, traded=100, status=OrderStatus.ALLTRADED))
    assert book.get(KEY).volume == 500
    assert book.get(KEY).frozen == 0
    assert book.available(KEY) == 500


# --------------------------------------------------------------------------- #
# OMS
# --------------------------------------------------------------------------- #
def test_oms_tracks_active_orders_and_positions() -> None:
    oms = OMS()
    oms.on_account(Account(account_id="acc", available=100000.0, balance=100000.0))
    assert oms.buying_power() == 100000.0

    o = Order(order_id="o1", code="000001", exchange=Exchange.SZSE,
              direction=Direction.LONG, volume=500, status=OrderStatus.NOTTRADED)
    oms.on_order(o)
    assert len(oms.get_active_orders()) == 1

    oms.on_trade(Trade(trade_id="tr1", order_id="o1", code="000001", exchange=Exchange.SZSE,
                       direction=Direction.LONG, volume=500, price=12.0))
    filled = Order(order_id="o1", code="000001", exchange=Exchange.SZSE,
                   direction=Direction.LONG, volume=500, traded=500, status=OrderStatus.ALLTRADED)
    oms.on_order(filled)

    assert oms.get_active_orders() == []                 # moved out of active set
    assert oms.get_position("000001.SZSE").volume == 500


def test_oms_dedups_trades() -> None:
    oms = OMS()
    tr = Trade(trade_id="dup", order_id="o1", code="600000", exchange=Exchange.SSE,
               direction=Direction.LONG, volume=100, price=10.0)
    oms.on_trade(tr)
    oms.on_trade(tr)                                      # same trade id again
    assert len(oms.get_trades()) == 1
    assert oms.get_position(KEY).volume == 100


def test_oms_rejects_illegal_order_regression() -> None:
    oms = OMS()
    oms.on_order(Order(order_id="o1", code="600000", exchange=Exchange.SSE,
                       direction=Direction.LONG, volume=100, traded=100, status=OrderStatus.ALLTRADED))
    # broker (buggily) sends a stale NOTTRADED snapshot for the same order
    oms.on_order(Order(order_id="o1", code="600000", exchange=Exchange.SSE,
                       direction=Direction.LONG, volume=100, status=OrderStatus.NOTTRADED))
    assert oms.get_order("o1").status is OrderStatus.ALLTRADED
    assert any("illegal order transition" in log.msg for log in oms.logs)


def test_oms_roll_new_day() -> None:
    oms = OMS()
    oms.positions.seed("600000", volume=0, price=0.0)
    oms.on_trade(_buy_trade("t1", volume=300, price=10.0))
    assert oms.available_shares(KEY) == 0                 # bought today
    oms.roll_new_day()
    assert oms.available_shares(KEY) == 300
