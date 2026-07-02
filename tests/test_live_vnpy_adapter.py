"""Phase 4: VnpyBrokerAdapter translation, verified against a *fake* vn.py binding.

No vn.py is installed here (macOS) — a fake binding with the same shape proves the
adapter maps requests and events both ways. On a Linux box, ``load_vnpy_binding``
supplies the real vn.py objects and the same adapter code runs unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace

from alphapilot.systems.live.brokers.vnpy_adapter import VnpyBinding, VnpyBrokerAdapter
from alphapilot.systems.live.types import (
    CancelRequest,
    Direction,
    Exchange,
    OrderRequest,
    OrderStatus,
)


# --- fake vn.py surface ----------------------------------------------------- #
class FEx(Enum):
    SSE = "SSE"; SZSE = "SZSE"; BSE = "BSE"; UNKNOWN = "U"


class FDir(Enum):
    LONG = 1; SHORT = 2; NET = 3


class FOff(Enum):
    NONE = 0; OPEN = 1; CLOSE = 2; CLOSETODAY = 3; CLOSEYESTERDAY = 4


class FType(Enum):
    LIMIT = 1; MARKET = 2


@dataclass
class FOrderReq:
    symbol: str; exchange: object; direction: object; type: object
    volume: float; price: float; offset: object; reference: str


@dataclass
class FCancelReq:
    orderid: str; symbol: str; exchange: object


@dataclass
class FSubReq:
    symbol: str; exchange: object


class FakeMainEngine:
    def __init__(self) -> None:
        self.sent: list = []
        self.cancelled: list = []
        self.subscribed: list = []
        self.connected = None
        self.closed = False
        self.qa = 0
        self.qp = 0
        self._gw = SimpleNamespace(query_account=self._qa, query_position=self._qp)

    def _qa(self):
        self.qa += 1

    def _qp(self):
        self.qp += 1

    def connect(self, setting, name):
        self.connected = (setting, name)

    def send_order(self, req, name):
        self.sent.append((req, name))
        return f"{name}.oid{len(self.sent)}"

    def cancel_order(self, req, name):
        self.cancelled.append((req, name))

    def subscribe(self, req, name):
        self.subscribed.append((req, name))

    def close(self):
        self.closed = True

    def get_gateway(self, name):
        return self._gw


class FakeEventEngine:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register(self, type_, handler):
        self.handlers.setdefault(type_, []).append(handler)

    def emit(self, type_, data):
        for h in self.handlers.get(type_, []):
            h(SimpleNamespace(type=type_, data=data))


class Collector:
    def __init__(self) -> None:
        self.orders, self.trades, self.positions = [], [], []
        self.accounts, self.contracts, self.ticks, self.logs = [], [], [], []

    def on_order(self, o): self.orders.append(o)
    def on_trade(self, t): self.trades.append(t)
    def on_position(self, p): self.positions.append(p)
    def on_account(self, a): self.accounts.append(a)
    def on_contract(self, c): self.contracts.append(c)
    def on_tick(self, t): self.ticks.append(t)
    def on_log(self, log): self.logs.append(log)


def _adapter():
    binding = VnpyBinding(
        main_engine=FakeMainEngine(), event_engine=FakeEventEngine(), gateway_name="EMT",
        OrderRequestCls=FOrderReq, CancelRequestCls=FCancelReq, SubscribeRequestCls=FSubReq,
        Direction=FDir, Offset=FOff, OrderType=FType, Exchange=FEx,
        EVENT_ORDER="eOrder", EVENT_TRADE="eTrade", EVENT_POSITION="ePos",
        EVENT_ACCOUNT="eAcct", EVENT_CONTRACT="eCon", EVENT_TICK="eTick",
    )
    adapter = VnpyBrokerAdapter("EMT", binding=binding)
    collector = Collector()
    adapter.register_callback(collector)
    adapter.connect({"账号": "x"})
    return adapter, binding, collector


# --- forward: our request -> vn.py request ---------------------------------- #
def test_send_order_translation() -> None:
    adapter, binding, _ = _adapter()
    oid = adapter.send_order(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0, reference="cid"))
    assert oid == "EMT.oid1"
    req, name = binding.main_engine.sent[0]
    assert name == "EMT"
    assert (req.symbol, req.exchange, req.direction, req.type) == ("600000", FEx.SSE, FDir.LONG, FType.LIMIT)
    assert req.volume == 1000 and req.price == 10.0 and req.offset == FOff.NONE and req.reference == "cid"


def test_sell_direction_maps_to_short() -> None:
    adapter, binding, _ = _adapter()
    adapter.send_order(OrderRequest.sell("000001", Exchange.SZSE, 500, 12.0))
    req, _ = binding.main_engine.sent[0]
    assert req.direction == FDir.SHORT and req.exchange == FEx.SZSE


def test_cancel_translation_strips_gateway_prefix() -> None:
    adapter, binding, _ = _adapter()
    adapter.cancel_order(CancelRequest(order_id="EMT.oid1", code="600000", exchange=Exchange.SSE))
    req, name = binding.main_engine.cancelled[0]
    assert req.orderid == "oid1" and req.symbol == "600000" and req.exchange == FEx.SSE


def test_query_and_subscribe_delegate() -> None:
    adapter, binding, _ = _adapter()
    adapter.query_account()
    adapter.query_position()
    adapter.subscribe(["600000", "sz.000001"])
    assert binding.main_engine.qa == 1 and binding.main_engine.qp == 1
    assert [r.symbol for r, _ in binding.main_engine.subscribed] == ["600000", "000001"]


# --- reverse: vn.py event -> normalized object ------------------------------ #
def test_order_event_normalized() -> None:
    adapter, binding, collector = _adapter()
    data = SimpleNamespace(
        vt_orderid="EMT.oid1", symbol="600000", exchange=SimpleNamespace(name="SSE"),
        direction=SimpleNamespace(name="LONG"), offset=SimpleNamespace(name="NONE"),
        type=SimpleNamespace(name="LIMIT"), price=10.0, volume=1000.0, traded=400.0,
        status=SimpleNamespace(name="PARTTRADED"), gateway_name="EMT", reference="cid",
    )
    binding.event_engine.emit("eOrder", data)
    order = collector.orders[0]
    assert order.order_id == "EMT.oid1" and order.code == "600000"
    assert order.exchange is Exchange.SSE and order.direction is Direction.LONG
    assert order.status is OrderStatus.PARTTRADED and order.traded == 400.0 and order.is_active()


def test_trade_and_account_events_normalized() -> None:
    adapter, binding, collector = _adapter()
    binding.event_engine.emit("eTrade", SimpleNamespace(
        vt_tradeid="EMT.t1", vt_orderid="EMT.oid1", symbol="600000",
        exchange=SimpleNamespace(name="SSE"), direction=SimpleNamespace(name="LONG"),
        offset=SimpleNamespace(name="NONE"), price=10.0, volume=1000.0, gateway_name="EMT"))
    binding.event_engine.emit("eAcct", SimpleNamespace(
        accountid="acc", balance=100000.0, frozen=0.0, available=95000.0, gateway_name="EMT"))
    assert collector.trades[0].trade_id == "EMT.t1" and collector.trades[0].volume == 1000.0
    assert collector.accounts[0].available == 95000.0


def test_position_event_carries_t_plus_one() -> None:
    adapter, binding, collector = _adapter()
    binding.event_engine.emit("ePos", SimpleNamespace(
        symbol="600000", exchange=SimpleNamespace(name="SSE"), direction=SimpleNamespace(name="LONG"),
        volume=1000.0, yd_volume=600.0, frozen=100.0, price=9.5, pnl=50.0, gateway_name="EMT"))
    pos = collector.positions[0]
    assert pos.volume == 1000.0 and pos.yd_volume == 600.0 and pos.available == 500.0
