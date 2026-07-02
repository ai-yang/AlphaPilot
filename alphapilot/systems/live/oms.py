"""OMS — order management / state projection from the gateway event stream.

The OMS is the in-process *single source of truth* for live state, built purely
by reducing the normalized callbacks a gateway pushes (mirrors vn.py's
``OmsEngine``). It implements :class:`~alphapilot.systems.live.gateway.GatewayCallback`
so it can be installed directly as a gateway's sink.

Split of authority (so nothing is double-counted):
* **positions/cost** come from *trades* (:class:`PositionBook.update_trade`);
* **frozen shares** come from working *sell orders* (:class:`PositionBook.update_order`);
* **cash / buying power** come from the broker's *account* snapshots;
* an **order**'s cumulative ``traded`` is taken from the broker's order snapshot
  (authoritative), while illegal/regressing transitions are rejected by the
  order FSM and dropped (kept at the more-advanced state).
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from alphapilot.systems.live.fsm import order_fsm
from alphapilot.systems.live.position import PositionBook
from alphapilot.systems.live.types import (
    Account,
    Contract,
    LogEvent,
    Order,
    Position,
    TickData,
    Trade,
)


class OMS:
    """Stateful projection of orders / trades / positions / account / quotes."""

    def __init__(self, log_capacity: int = 500) -> None:
        self.orders: dict[str, Order] = {}
        self.active_orders: dict[str, Order] = {}
        self.trades: dict[str, Trade] = {}
        self.positions = PositionBook()
        self.account: Account | None = None
        self.contracts: dict[str, Contract] = {}
        self.ticks: dict[str, TickData] = {}
        self.logs: Deque[LogEvent] = deque(maxlen=log_capacity)

    # ---- GatewayCallback -------------------------------------------------- #
    def on_order(self, order: Order) -> None:
        prior = self.orders.get(order.order_id)
        if prior is not None and not order_fsm.can_transition(prior.status, order.status):
            # Reject illegal/regressing broker updates; keep the advanced state.
            if prior.status != order.status:
                self.logs.append(
                    LogEvent(
                        msg=(
                            f"ignored illegal order transition {prior.status.name}->"
                            f"{order.status.name} for {order.order_id}"
                        ),
                        level="warning",
                        gateway=order.gateway,
                    )
                )
            return
        self.orders[order.order_id] = order
        if order.is_active():
            self.active_orders[order.order_id] = order
        else:
            self.active_orders.pop(order.order_id, None)
        self.positions.update_order(order)

    def on_trade(self, trade: Trade) -> None:
        if trade.trade_id in self.trades:
            return  # dedup — each fill counted once
        self.trades[trade.trade_id] = trade
        self.positions.update_trade(trade)

    def on_position(self, position: Position) -> None:
        self.positions.update_position(position)

    def on_account(self, account: Account) -> None:
        self.account = account

    def on_contract(self, contract: Contract) -> None:
        self.contracts[contract.key] = contract

    def on_tick(self, tick: TickData) -> None:
        self.ticks[tick.key] = tick

    def on_log(self, log: LogEvent) -> None:
        self.logs.append(log)

    # ---- queries ---------------------------------------------------------- #
    def get_order(self, order_id: str) -> Order | None:
        return self.orders.get(order_id)

    def get_active_orders(self) -> list[Order]:
        return list(self.active_orders.values())

    def get_trades(self) -> list[Trade]:
        return list(self.trades.values())

    def get_position(self, key: str) -> Position | None:
        return self.positions.get(key)

    def get_positions(self) -> list[Position]:
        return self.positions.all_positions()

    def available_shares(self, key: str) -> float:
        return self.positions.available(key)

    def get_contract(self, key: str) -> Contract | None:
        return self.contracts.get(key)

    def get_tick(self, key: str) -> TickData | None:
        return self.ticks.get(key)

    def buying_power(self) -> float:
        return self.account.available if self.account else 0.0

    # ---- day roll --------------------------------------------------------- #
    def roll_new_day(self) -> None:
        """Roll T+1 (today's buys become sellable) and drop the day's dead orders."""
        self.positions.roll_new_day()
        self.active_orders = {
            oid: o for oid, o in self.active_orders.items() if o.is_active()
        }
