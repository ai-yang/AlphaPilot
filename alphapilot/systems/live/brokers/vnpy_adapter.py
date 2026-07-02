"""VnpyBrokerAdapter — the single bridge from the AlphaPilot live port to vn.py.

This is the **only** module that touches vn.py, and it imports it lazily (inside
:func:`load_vnpy_binding`, called at connect time), so importing the live
subsystem never requires vn.py or a broker SDK. Any vn.py gateway (EMT, XTP, CTP,
…) plugs in by name — the whole stack above this adapter is unchanged, which is
what makes the live system reusable across brokers.

Translation is done by *enum name*: AlphaPilot and vn.py share the same member
names for the pieces we use (``Direction.LONG``, ``Offset.NONE``,
``OrderStatus/Status.ALLTRADED``, ``Exchange.SSE`` …), so we map with
`` EnumCls[member.name] `` in both directions. That keeps the conversions pure and
lets the adapter be unit-tested on macOS against a *fake* binding (see
``tests/test_live_vnpy_adapter.py``) without vn.py installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alphapilot.systems.live.gateway import BrokerGateway
from alphapilot.systems.live.types import (
    Account,
    CancelRequest,
    Contract,
    Direction,
    Exchange,
    Offset,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    TickData,
    Trade,
)


@dataclass
class VnpyBinding:
    """Everything vn.py-specific the adapter needs, gathered in one injectable place.

    A real one is built by :func:`load_vnpy_binding`; tests pass a fake with the
    same shape so the translation can be verified without vn.py.
    """

    main_engine: Any            # vnpy MainEngine (connect/send_order/cancel_order/subscribe/close)
    event_engine: Any           # vnpy EventEngine (register)
    gateway_name: str
    # vn.py classes / enums used to construct requests:
    OrderRequestCls: Any
    CancelRequestCls: Any
    SubscribeRequestCls: Any
    Direction: Any
    Offset: Any
    OrderType: Any
    Exchange: Any
    # vn.py event-type constants:
    EVENT_ORDER: str
    EVENT_TRADE: str
    EVENT_POSITION: str
    EVENT_ACCOUNT: str
    EVENT_CONTRACT: str
    EVENT_TICK: str


def _by_name(enum_cls, member, default):
    """Map an enum member across the two enum namespaces by member *name*."""
    name = getattr(member, "name", str(member))
    try:
        return enum_cls[name]
    except KeyError:
        return default


class VnpyBrokerAdapter(BrokerGateway):
    """Drives a vn.py gateway through the AlphaPilot :class:`BrokerGateway` port."""

    def __init__(
        self,
        gateway_name: str = "EMT",
        *,
        gateway_class: Any = None,
        binding: VnpyBinding | None = None,
    ) -> None:
        super().__init__(name=gateway_name.lower())
        self.gateway_name = gateway_name
        self._gateway_class = gateway_class
        self._binding = binding

    # ---- BrokerGateway --------------------------------------------------- #
    def connect(self, setting: dict) -> None:
        if not setting:
            # No explicit setting: build it from ALPHAPILOT_LIVE_<BROKER>_* env
            # variables via the broker registry (credentials never in code).
            from alphapilot.systems.live.brokers.registry import build_connect_setting

            setting = build_connect_setting(self.name)
        if self._binding is None:
            self._binding = load_vnpy_binding(self.gateway_name, self._gateway_class)
        self._register_handlers()
        self._binding.main_engine.connect(setting, self.gateway_name)
        self._emit_log(f"vnpy gateway {self.gateway_name} connect requested")

    def close(self) -> None:
        if self._binding is not None:
            self._binding.main_engine.close()

    def send_order(self, req: OrderRequest) -> str:
        b = self._binding
        vnpy_req = b.OrderRequestCls(
            symbol=req.code,
            exchange=_by_name(b.Exchange, req.exchange, None),
            direction=_by_name(b.Direction, req.direction, None),
            type=_by_name(b.OrderType, req.type, None),
            volume=req.volume,
            price=req.price,
            offset=_by_name(b.Offset, req.offset, None),
            reference=req.reference,
        )
        return b.main_engine.send_order(vnpy_req, self.gateway_name)

    def cancel_order(self, req: CancelRequest) -> None:
        b = self._binding
        orderid = req.order_id.split(".", 1)[1] if "." in req.order_id else req.order_id
        vnpy_req = b.CancelRequestCls(
            orderid=orderid,
            symbol=req.code,
            exchange=_by_name(b.Exchange, req.exchange, None),
        )
        b.main_engine.cancel_order(vnpy_req, self.gateway_name)

    def query_account(self) -> None:
        gw = self._get_gateway()
        if gw is not None and hasattr(gw, "query_account"):
            gw.query_account()

    def query_position(self) -> None:
        gw = self._get_gateway()
        if gw is not None and hasattr(gw, "query_position"):
            gw.query_position()

    def subscribe(self, codes: list[str]) -> None:
        from alphapilot.systems.live.types import normalize_symbol

        b = self._binding
        for code in codes:
            c, ex = normalize_symbol(code)
            req = b.SubscribeRequestCls(symbol=c, exchange=_by_name(b.Exchange, ex, None))
            b.main_engine.subscribe(req, self.gateway_name)

    # ---- vn.py event handlers (normalize -> push to callback) ------------ #
    def _register_handlers(self) -> None:
        ee = self._binding.event_engine
        ee.register(self._binding.EVENT_ORDER, self._on_order)
        ee.register(self._binding.EVENT_TRADE, self._on_trade)
        ee.register(self._binding.EVENT_POSITION, self._on_position)
        ee.register(self._binding.EVENT_ACCOUNT, self._on_account)
        ee.register(self._binding.EVENT_CONTRACT, self._on_contract)
        ee.register(self._binding.EVENT_TICK, self._on_tick)

    def _on_order(self, event: Any) -> None:
        self._emit_order(self.to_order(event.data))

    def _on_trade(self, event: Any) -> None:
        self._emit_trade(self.to_trade(event.data))

    def _on_position(self, event: Any) -> None:
        self._emit_position(self.to_position(event.data))

    def _on_account(self, event: Any) -> None:
        self._emit_account(self.to_account(event.data))

    def _on_contract(self, event: Any) -> None:
        self._emit_contract(self.to_contract(event.data))

    def _on_tick(self, event: Any) -> None:
        self._emit_tick(self.to_tick(event.data))

    def _get_gateway(self) -> Any:
        me = self._binding.main_engine
        getter = getattr(me, "get_gateway", None)
        return getter(self.gateway_name) if getter else None

    # ---- vn.py object -> normalized object (pure; testable) -------------- #
    def to_order(self, d: Any) -> Order:
        return Order(
            order_id=d.vt_orderid, code=d.symbol, exchange=_by_name(Exchange, d.exchange, Exchange.UNKNOWN),
            direction=_by_name(Direction, d.direction, Direction.LONG),
            offset=_by_name(Offset, d.offset, Offset.NONE),
            type=_by_name(OrderType, d.type, OrderType.LIMIT),
            price=float(d.price), volume=float(d.volume), traded=float(getattr(d, "traded", 0.0)),
            status=_by_name(OrderStatus, d.status, OrderStatus.SUBMITTING),
            gateway=getattr(d, "gateway_name", self.name), reference=getattr(d, "reference", ""),
        )

    def to_trade(self, d: Any) -> Trade:
        return Trade(
            trade_id=d.vt_tradeid, order_id=d.vt_orderid, code=d.symbol,
            exchange=_by_name(Exchange, d.exchange, Exchange.UNKNOWN),
            direction=_by_name(Direction, d.direction, Direction.LONG),
            offset=_by_name(Offset, d.offset, Offset.NONE),
            price=float(d.price), volume=float(d.volume), gateway=getattr(d, "gateway_name", self.name),
        )

    def to_position(self, d: Any) -> Position:
        return Position(
            code=d.symbol, exchange=_by_name(Exchange, d.exchange, Exchange.UNKNOWN),
            direction=_by_name(Direction, d.direction, Direction.LONG),
            volume=float(d.volume), yd_volume=float(getattr(d, "yd_volume", 0.0)),
            frozen=float(getattr(d, "frozen", 0.0)), price=float(getattr(d, "price", 0.0)),
            pnl=float(getattr(d, "pnl", 0.0)), gateway=getattr(d, "gateway_name", self.name),
        )

    def to_account(self, d: Any) -> Account:
        balance = float(getattr(d, "balance", 0.0))
        frozen = float(getattr(d, "frozen", 0.0))
        available = float(getattr(d, "available", balance - frozen))
        return Account(
            account_id=d.accountid, balance=balance, frozen=frozen, available=available,
            gateway=getattr(d, "gateway_name", self.name),
        )

    def to_contract(self, d: Any) -> Contract:
        return Contract(
            code=d.symbol, exchange=_by_name(Exchange, d.exchange, Exchange.UNKNOWN),
            name=getattr(d, "name", ""), size=float(getattr(d, "size", 1.0)),
            price_tick=float(getattr(d, "pricetick", 0.01)),
            lot_size=int(getattr(d, "min_volume", 100) or 100),
            gateway=getattr(d, "gateway_name", self.name),
        )

    def to_tick(self, d: Any) -> TickData:
        return TickData(
            code=d.symbol, exchange=_by_name(Exchange, d.exchange, Exchange.UNKNOWN),
            datetime=getattr(d, "datetime", None), last_price=float(getattr(d, "last_price", 0.0)),
            pre_close=float(getattr(d, "pre_close", 0.0)), open_price=float(getattr(d, "open_price", 0.0)),
            high_price=float(getattr(d, "high_price", 0.0)), low_price=float(getattr(d, "low_price", 0.0)),
            limit_up=float(getattr(d, "limit_up", 0.0)), limit_down=float(getattr(d, "limit_down", 0.0)),
            bid_price_1=float(getattr(d, "bid_price_1", 0.0)), ask_price_1=float(getattr(d, "ask_price_1", 0.0)),
            bid_volume_1=float(getattr(d, "bid_volume_1", 0.0)), ask_volume_1=float(getattr(d, "ask_volume_1", 0.0)),
            gateway=getattr(d, "gateway_name", self.name),
        )


def load_vnpy_binding(gateway_name: str, gateway_class: Any = None) -> VnpyBinding:
    """Import vn.py, build a MainEngine + EventEngine and add the named gateway.

    Linux/Windows only (vn.py + the broker SDK must be installed and, for
    source installs, compiled). Never imported at module load — only here.
    """
    from vnpy.event import EventEngine
    from vnpy.trader.engine import MainEngine
    from vnpy.trader.event import (
        EVENT_ACCOUNT,
        EVENT_CONTRACT,
        EVENT_ORDER,
        EVENT_POSITION,
        EVENT_TICK,
        EVENT_TRADE,
    )
    from vnpy.trader.constant import Direction as VnDirection
    from vnpy.trader.constant import Exchange as VnExchange
    from vnpy.trader.constant import Offset as VnOffset
    from vnpy.trader.constant import OrderType as VnOrderType
    from vnpy.trader.object import CancelRequest as VnCancelRequest
    from vnpy.trader.object import OrderRequest as VnOrderRequest
    from vnpy.trader.object import SubscribeRequest as VnSubscribeRequest

    if gateway_class is None:
        gateway_class = _resolve_gateway_class(gateway_name)

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(gateway_class)

    return VnpyBinding(
        main_engine=main_engine, event_engine=event_engine, gateway_name=gateway_name,
        OrderRequestCls=VnOrderRequest, CancelRequestCls=VnCancelRequest,
        SubscribeRequestCls=VnSubscribeRequest, Direction=VnDirection, Offset=VnOffset,
        OrderType=VnOrderType, Exchange=VnExchange,
        EVENT_ORDER=EVENT_ORDER, EVENT_TRADE=EVENT_TRADE, EVENT_POSITION=EVENT_POSITION,
        EVENT_ACCOUNT=EVENT_ACCOUNT, EVENT_CONTRACT=EVENT_CONTRACT, EVENT_TICK=EVENT_TICK,
    )


def _resolve_gateway_class(gateway_name: str) -> Any:
    """Import the vn.py gateway class for ``gateway_name`` via the broker registry.

    Adding a broker = one :func:`~alphapilot.systems.live.brokers.registry.register_broker`
    entry; nothing here changes.
    """
    from alphapilot.systems.live.brokers.registry import resolve_gateway_class

    return resolve_gateway_class(gateway_name)
