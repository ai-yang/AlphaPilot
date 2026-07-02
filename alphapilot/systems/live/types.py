"""Normalized, broker-agnostic domain objects for the live-trading subsystem.

This module is the *single source of truth* for the objects that flow between the
broker gateway, the OMS, the risk gate and the executor. It is deliberately
dependency-light (stdlib + dataclasses only) so it can be imported anywhere —
including from ``systems/timing`` and the kernel — **without pulling vn.py, qlib
or any broker SDK**. Concrete gateways (paper / sim / vn.py) translate their
native structures into these types at the boundary, mirroring vn.py's approach of
normalizing every gateway into ``OrderData/TradeData/PositionData/...`` keyed by a
uniform ``vt_symbol`` / ``vt_orderid``.

The A-share domain is the initial focus (SSE / SZSE / BSE, long-only, T+1, board
lots), but the enums and dataclasses carry the ``direction`` / ``offset`` fields
needed to extend to margin / futures later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    """Order / position direction."""

    LONG = "long"
    SHORT = "short"
    NET = "net"


class Offset(str, Enum):
    """Open/close offset. A-shares use ``NONE``; futures use the rest."""

    NONE = "none"
    OPEN = "open"
    CLOSE = "close"
    CLOSETODAY = "close_today"
    CLOSEYESTERDAY = "close_yesterday"


class OrderType(str, Enum):
    """Supported order price types (extend with FAK/FOK later)."""

    LIMIT = "limit"
    MARKET = "market"


class Exchange(str, Enum):
    """Exchanges relevant to the A-share market (extensible)."""

    SSE = "SSE"       # 上交所
    SZSE = "SZSE"     # 深交所
    BSE = "BSE"       # 北交所
    UNKNOWN = "UNKNOWN"


class Product(str, Enum):
    EQUITY = "equity"
    FUND = "fund"      # ETF / LOF
    BOND = "bond"
    INDEX = "index"
    OPTION = "option"


class OrderStatus(str, Enum):
    """Order lifecycle states — aligned with vn.py's ``Status`` (6 states).

    ``SUBMITTED`` / ``FILLED`` are kept as **back-compat aliases** of
    ``SUBMITTING`` / ``ALLTRADED`` so the pre-existing ``systems/timing`` code
    that referenced the old 4-state enum keeps working unchanged.
    """

    SUBMITTING = "submitting"   # local, not yet acknowledged by the broker
    NOTTRADED = "nottraded"     # accepted by the exchange, no fill yet
    PARTTRADED = "parttraded"   # partially filled
    ALLTRADED = "alltraded"     # fully filled
    CANCELLED = "cancelled"     # cancelled (any remaining volume withdrawn)
    REJECTED = "rejected"       # rejected by risk gate / broker / exchange

    # --- back-compat aliases (old timing names) ---
    SUBMITTED = "submitting"
    FILLED = "alltraded"


# Orders in these states are still "working" and may still fill or be cancelled.
ACTIVE_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.SUBMITTING, OrderStatus.NOTTRADED, OrderStatus.PARTTRADED}
)


def is_active(status: OrderStatus) -> bool:
    """True if an order in ``status`` is still working (mirrors vn.py's is_active)."""
    return status in ACTIVE_STATUSES


# --------------------------------------------------------------------------- #
# Symbol helpers
# --------------------------------------------------------------------------- #
def infer_exchange(code: str) -> Exchange:
    """Infer the A-share exchange from a 6-digit board code.

    SSE: 60xxxx / 68xxxx (科创板) / 5xxxxx (基金) / 11xxxx (债).
    SZSE: 00xxxx / 30xxxx (创业板) / 15xxxx / 16xxxx / 12xxxx.
    BSE: 8xxxxx / 4xxxxx / 920xxx.
    """
    c = code.strip()
    if not c[:1].isdigit():
        return Exchange.UNKNOWN
    if c[0] == "6" or c[0] == "5" or c.startswith("11"):
        return Exchange.SSE
    if c[0] in ("0", "3", "1", "2"):
        return Exchange.SZSE
    if c[0] in ("8", "4") or c.startswith("920"):
        return Exchange.BSE
    return Exchange.UNKNOWN


def normalize_symbol(symbol: str) -> tuple[str, Exchange]:
    """Parse a symbol in any common form into ``(code6, exchange)``.

    Accepts ``600000``, ``SH600000`` / ``sh600000``, ``sh.600000``,
    ``600000.SH``, ``SSE.600000`` etc. Falls back to inferring the exchange
    from the numeric code when no prefix/suffix is present.
    """
    raw = symbol.strip().upper().replace(" ", "")
    prefix_map = {"SH": Exchange.SSE, "SZ": Exchange.SZSE, "BJ": Exchange.BSE}

    for sep in (".", "-", "_"):
        if sep in raw:
            a, b = raw.split(sep, 1)
            if a.isdigit():          # 600000.SH
                code, tag = a, b
            else:                    # SH.600000 / SSE.600000
                code, tag = b, a
            code = "".join(ch for ch in code if ch.isdigit())
            ex = prefix_map.get(tag[:2]) or _exchange_from_tag(tag) or infer_exchange(code)
            return code, ex

    for pfx, ex in prefix_map.items():
        if raw.startswith(pfx) and raw[len(pfx):].isdigit():
            return raw[len(pfx):], ex

    code = "".join(ch for ch in raw if ch.isdigit())
    return code, infer_exchange(code)


def _exchange_from_tag(tag: str) -> Optional[Exchange]:
    try:
        return Exchange(tag)
    except ValueError:
        return None


def symbol_key(code: str, exchange: Exchange) -> str:
    """Uniform instrument key (vn.py's ``vt_symbol`` analogue): ``600000.SSE``."""
    return f"{code}.{exchange.value}"


# --------------------------------------------------------------------------- #
# Contracts / requests / stateful objects
# --------------------------------------------------------------------------- #
@dataclass
class Contract:
    """Static instrument metadata (board lot, price tick) — needed for rounding."""

    code: str
    exchange: Exchange
    name: str = ""
    product: Product = Product.EQUITY
    size: float = 1.0
    price_tick: float = 0.01
    lot_size: int = 100          # A-share board lot
    gateway: str = ""

    @property
    def key(self) -> str:
        return symbol_key(self.code, self.exchange)


@dataclass
class OrderRequest:
    """An intent to trade, before it is accepted by any broker.

    ``reference`` carries the caller's idempotency key (client order id) so the
    risk gate can dedup and the ledger can trace an intent end-to-end.
    """

    code: str
    exchange: Exchange
    direction: Direction
    volume: float
    price: float = 0.0
    type: OrderType = OrderType.LIMIT
    offset: Offset = Offset.NONE
    reference: str = ""

    @property
    def key(self) -> str:
        return symbol_key(self.code, self.exchange)

    @property
    def is_buy(self) -> bool:
        return self.direction == Direction.LONG

    @property
    def is_sell(self) -> bool:
        return self.direction == Direction.SHORT

    @classmethod
    def buy(cls, code: str, exchange: Exchange, volume: float, price: float = 0.0,
            type: OrderType = OrderType.LIMIT, reference: str = "") -> "OrderRequest":
        """A-share buy = (Direction.LONG, Offset.NONE), matching the EMT/XTP side map."""
        return cls(code=code, exchange=exchange, direction=Direction.LONG,
                   volume=volume, price=price, type=type, reference=reference)

    @classmethod
    def sell(cls, code: str, exchange: Exchange, volume: float, price: float = 0.0,
             type: OrderType = OrderType.LIMIT, reference: str = "") -> "OrderRequest":
        """A-share sell = (Direction.SHORT, Offset.NONE)."""
        return cls(code=code, exchange=exchange, direction=Direction.SHORT,
                   volume=volume, price=price, type=type, reference=reference)

    def create_order(self, order_id: str, gateway: str, status: OrderStatus = OrderStatus.SUBMITTING) -> "Order":
        return Order(
            order_id=order_id,
            code=self.code,
            exchange=self.exchange,
            direction=self.direction,
            offset=self.offset,
            type=self.type,
            price=self.price,
            volume=self.volume,
            traded=0.0,
            status=status,
            gateway=gateway,
            reference=self.reference,
            datetime=datetime.now(),
        )


@dataclass
class CancelRequest:
    order_id: str
    code: str
    exchange: Exchange


@dataclass
class Order:
    """A live order tracked through its lifecycle (see :class:`OrderStatus`)."""

    order_id: str
    code: str
    exchange: Exchange
    direction: Direction
    volume: float
    price: float = 0.0
    type: OrderType = OrderType.LIMIT
    offset: Offset = Offset.NONE
    traded: float = 0.0
    status: OrderStatus = OrderStatus.SUBMITTING
    gateway: str = ""
    reference: str = ""
    datetime: Optional[datetime] = None
    message: str = ""

    @property
    def key(self) -> str:
        return symbol_key(self.code, self.exchange)

    @property
    def remaining(self) -> float:
        return max(self.volume - self.traded, 0.0)

    def is_active(self) -> bool:
        return is_active(self.status)

    def create_cancel(self) -> CancelRequest:
        return CancelRequest(order_id=self.order_id, code=self.code, exchange=self.exchange)


@dataclass
class Trade:
    """A single fill of an order."""

    trade_id: str
    order_id: str
    code: str
    exchange: Exchange
    direction: Direction
    volume: float
    price: float
    offset: Offset = Offset.NONE
    gateway: str = ""
    datetime: Optional[datetime] = None

    @property
    def key(self) -> str:
        return symbol_key(self.code, self.exchange)


@dataclass
class Position:
    """Holding of one instrument, with A-share T+1 accounting.

    ``yd_volume`` is the sellable (yesterday) portion; ``volume - yd_volume`` is
    today's non-sellable portion; ``frozen`` is the amount locked by working sell
    orders. Mirrors vn.py's ``PositionData`` + ``PositionHolding`` split.
    """

    code: str
    exchange: Exchange
    direction: Direction = Direction.LONG
    volume: float = 0.0
    yd_volume: float = 0.0
    frozen: float = 0.0
    price: float = 0.0          # average cost
    pnl: float = 0.0
    gateway: str = ""

    @property
    def key(self) -> str:
        return symbol_key(self.code, self.exchange)

    @property
    def available(self) -> float:
        """Sellable now = yesterday's holding not already frozen by sell orders."""
        return max(self.yd_volume - self.frozen, 0.0)


@dataclass
class Account:
    account_id: str
    balance: float = 0.0        # total assets snapshot (cash + optional securities)
    frozen: float = 0.0
    available: float = 0.0      # buying power
    gateway: str = ""


@dataclass
class TickData:
    """Minimal real-time quote (extend with full depth later)."""

    code: str
    exchange: Exchange
    datetime: Optional[datetime] = None
    last_price: float = 0.0
    pre_close: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    limit_up: float = 0.0
    limit_down: float = 0.0
    bid_price_1: float = 0.0
    ask_price_1: float = 0.0
    bid_volume_1: float = 0.0
    ask_volume_1: float = 0.0
    gateway: str = ""

    @property
    def key(self) -> str:
        return symbol_key(self.code, self.exchange)


@dataclass
class LogEvent:
    """A gateway log line surfaced to the engine (connection msgs, errors)."""

    msg: str
    level: str = "info"
    gateway: str = ""
    datetime: Optional[datetime] = field(default_factory=datetime.now)
