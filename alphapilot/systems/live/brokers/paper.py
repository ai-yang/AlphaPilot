"""PaperBroker — a deterministic in-process gateway that simulates fills.

It implements the same :class:`~alphapilot.systems.live.gateway.BrokerGateway`
port as a real broker, so the OMS / risk gate / executor / engine exercise the
*exact same code path* against it as they will against EMT/XTP. Fills are
synchronous and deterministic (fill the whole order at the limit price, or at the
last known price for market orders), which makes end-to-end tests reproducible.

It keeps its **own** account truth (cash + long-only positions with T+1), and
pushes normalized ``on_order`` / ``on_trade`` / ``on_account`` / ``on_position``
callbacks — emitting the trade *before* the authoritative position snapshot so a
downstream OMS never double-counts.
"""

from __future__ import annotations

import uuid
from copy import copy
from dataclasses import dataclass

from alphapilot.systems.live.gateway import BrokerGateway
from alphapilot.systems.live.types import (
    Account,
    CancelRequest,
    Direction,
    Exchange,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Trade,
    normalize_symbol,
)


@dataclass
class _Holding:
    code: str
    exchange: Exchange
    volume: float = 0.0
    yd_volume: float = 0.0
    price: float = 0.0


@dataclass
class FillDecision:
    """How the (sim) broker responds to an order. See :class:`PaperBroker._decide`."""

    fill_volume: float
    fill_price: float
    reject: bool = False
    reason: str = ""


class PaperBroker(BrokerGateway):
    """Deterministic simulated broker (full fills)."""

    name = "paper"
    exchanges = [Exchange.SSE, Exchange.SZSE, Exchange.BSE]

    def __init__(
        self,
        cash: float = 1_000_000.0,
        prices: dict[str, float] | None = None,
        *,
        open_cost: float = 0.0003,
        close_cost: float = 0.0013,
        min_cost: float = 5.0,
        account_id: str = "paper",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.cash = float(cash)
        self.account_id = account_id
        self.open_cost = open_cost
        self.close_cost = close_cost
        self.min_cost = min_cost
        self._prices: dict[str, float] = dict(prices or {})
        self._holdings: dict[str, _Holding] = {}
        self._working: dict[str, Order] = {}
        self._seq = 0

    # ---- test/seed helpers ----------------------------------------------- #
    def set_prices(self, prices: dict[str, float]) -> None:
        for code, px in prices.items():
            self._prices[self._key(code)] = float(px)

    def seed_position(self, code: str, volume: float, price: float, *, sellable: bool = True) -> None:
        c, ex = normalize_symbol(code)
        key = f"{c}.{ex.value}"
        self._holdings[key] = _Holding(
            code=c, exchange=ex, volume=float(volume),
            yd_volume=float(volume) if sellable else 0.0, price=float(price),
        )

    @staticmethod
    def _key(code: str) -> str:
        c, ex = normalize_symbol(code)
        return f"{c}.{ex.value}"

    # ---- BrokerGateway --------------------------------------------------- #
    def connect(self, setting: dict) -> None:
        if "cash" in setting:
            self.cash = float(setting["cash"])
        self._emit_log("paper broker connected")
        self.query_account()
        self.query_position()

    def close(self) -> None:
        self._emit_log("paper broker closed")

    def send_order(self, req: OrderRequest) -> str:
        self._seq += 1
        order_id = f"{self.name}-{self._seq}-{uuid.uuid4().hex[:6]}"
        order = req.create_order(order_id, self.name, status=OrderStatus.SUBMITTING)
        self._emit_order(copy(order))

        decision = self._decide(req)
        if decision.reject:
            self._advance(order, OrderStatus.REJECTED, message=decision.reason)
            return order_id

        # accepted by the "exchange"
        self._advance(order, OrderStatus.NOTTRADED)

        if decision.fill_volume > 0:
            trade = self._apply_fill(req, order, decision)
            self._emit_trade(trade)
            order.traded = min(order.traded + decision.fill_volume, order.volume)
            status = (
                OrderStatus.ALLTRADED if order.traded >= order.volume - 1e-9
                else OrderStatus.PARTTRADED
            )
            self._advance(order, status)
            # authoritative snapshots AFTER the trade (so the OMS overwrites, never doubles)
            self._emit_account_snapshot()
            self._emit_position_snapshot(req.code, req.exchange)

        if order.is_active():
            self._working[order_id] = order
        else:
            self._working.pop(order_id, None)
        return order_id

    def cancel_order(self, req: CancelRequest) -> None:
        order = self._working.get(req.order_id)
        if order is None or not order.is_active():
            self._emit_log(f"cancel ignored: {req.order_id} not working", level="warning")
            return
        self._advance(order, OrderStatus.CANCELLED, message="cancelled by user")
        self._working.pop(req.order_id, None)

    def query_account(self) -> None:
        self._emit_account_snapshot()

    def query_position(self) -> None:
        for h in self._holdings.values():
            if h.volume > 0:
                self._emit_position_of(h)

    # ---- fill policy (overridden by SimBroker) --------------------------- #
    def _decide(self, req: OrderRequest) -> FillDecision:
        """Default: full fill at the resolved price."""
        return FillDecision(fill_volume=req.volume, fill_price=self._fill_price(req))

    def _fill_price(self, req: OrderRequest) -> float:
        if req.type == OrderType.LIMIT and req.price > 0:
            return req.price
        return self._prices.get(req.key, req.price)

    # ---- internals ------------------------------------------------------- #
    def _advance(self, order: Order, status: OrderStatus, *, message: str = "") -> None:
        order.status = status
        if message:
            order.message = message
        # Emit a *copy* so the OMS never aliases the broker's mutable order (a
        # shared reference would make ``prior is current`` and defeat the FSM guard).
        self._emit_order(copy(order))

    def _apply_fill(self, req: OrderRequest, order: Order, decision: FillDecision) -> Trade:
        key = req.key
        holding = self._holdings.setdefault(key, _Holding(code=req.code, exchange=req.exchange))
        vol, px = decision.fill_volume, decision.fill_price
        if req.direction == Direction.LONG:                      # buy
            gross = vol * px
            fee = max(gross * self.open_cost, self.min_cost)
            self.cash -= gross + fee
            new_vol = holding.volume + vol
            if new_vol > 0:
                holding.price = (holding.price * holding.volume + gross) / new_vol
            holding.volume = new_vol                              # today's buy: yd unchanged
        else:                                                    # sell
            gross = vol * px
            fee = max(gross * self.close_cost, self.min_cost)
            self.cash += gross - fee
            holding.volume = max(holding.volume - vol, 0.0)
            holding.yd_volume = max(holding.yd_volume - vol, 0.0)
        return Trade(
            trade_id=uuid.uuid4().hex, order_id=order.order_id, code=req.code,
            exchange=req.exchange, direction=req.direction, volume=vol, price=px,
            gateway=self.name,
        )

    def _emit_account_snapshot(self) -> None:
        self._emit_account(Account(
            account_id=self.account_id, balance=self._equity(),
            available=self.cash, frozen=0.0, gateway=self.name,
        ))

    def _equity(self) -> float:
        mkt = sum(h.volume * self._prices.get(k, h.price) for k, h in self._holdings.items())
        return self.cash + mkt

    def _emit_position_snapshot(self, code: str, exchange: Exchange) -> None:
        key = f"{code}.{exchange.value}"
        holding = self._holdings.get(key)
        if holding is not None:
            self._emit_position_of(holding)

    def _emit_position_of(self, h: _Holding) -> None:
        self._emit_position(Position(
            code=h.code, exchange=h.exchange, direction=Direction.LONG,
            volume=h.volume, yd_volume=h.yd_volume, price=h.price, gateway=self.name,
        ))

    def roll_new_day(self) -> None:
        """Advance T+1: today's buys become sellable; drop dead working orders."""
        for h in self._holdings.values():
            h.yd_volume = h.volume
        self._working.clear()
