"""The broker gateway *port* — the seam that makes the live system reusable.

Every broker (paper / sim / EMT / XTP / CTP …) is a :class:`BrokerGateway`
subclass. Everything above the gateway (OMS, risk gate, executor, engine)
depends *only* on this abstract port plus the normalized objects in
:mod:`alphapilot.systems.live.types` — never on a concrete broker SDK. This is
the same ports-and-adapters model vn.py uses with ``BaseGateway``: swap the
gateway, and the whole stack above it is unchanged.

Design notes
------------
* **Event-driven, not request/reply.** ``send_order`` returns a local order id
  immediately; fills/acks arrive later via the callback (``on_order`` /
  ``on_trade``). This matches how real broker APIs (and vn.py) behave, and lets
  the paper/sim brokers exercise the exact same code path as a real one.
* **Callback sink.** The engine installs a :class:`GatewayCallback` (normally the
  OMS) via :meth:`BrokerGateway.register_callback`. Gateways push normalized
  events through the ``_emit_*`` helpers, which are no-ops until a callback is
  registered (so a gateway can be constructed and unit-tested in isolation).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from alphapilot.systems.live.types import (
    Account,
    CancelRequest,
    Contract,
    LogEvent,
    Order,
    OrderRequest,
    Position,
    TickData,
    Trade,
)


@runtime_checkable
class GatewayCallback(Protocol):
    """The sink a gateway pushes normalized events into (implemented by the OMS)."""

    def on_order(self, order: Order) -> None: ...
    def on_trade(self, trade: Trade) -> None: ...
    def on_position(self, position: Position) -> None: ...
    def on_account(self, account: Account) -> None: ...
    def on_contract(self, contract: Contract) -> None: ...
    def on_tick(self, tick: TickData) -> None: ...
    def on_log(self, log: LogEvent) -> None: ...


class BrokerGateway(ABC):
    """Abstract broker adapter. Concrete brokers implement the abstract methods.

    Subclasses set :attr:`name`, :attr:`default_setting` (the connection fields a
    UI would render) and :attr:`exchanges` (supported exchanges).
    """

    #: Human-readable broker name (e.g. ``"paper"``, ``"emt"``, ``"xtp"``).
    name: str = ""
    #: Connection fields with default values (creds are supplied at connect time).
    default_setting: dict[str, object] = {}
    #: Exchanges this gateway can route to.
    exchanges: list = []

    def __init__(self, name: str | None = None) -> None:
        if name:
            self.name = name
        self._callback: GatewayCallback | None = None

    # ---- callback wiring -------------------------------------------------- #
    def register_callback(self, callback: GatewayCallback) -> None:
        """Install the event sink (the OMS). Called once by the engine."""
        self._callback = callback

    def _emit_order(self, order: Order) -> None:
        if self._callback is not None:
            self._callback.on_order(order)

    def _emit_trade(self, trade: Trade) -> None:
        if self._callback is not None:
            self._callback.on_trade(trade)

    def _emit_position(self, position: Position) -> None:
        if self._callback is not None:
            self._callback.on_position(position)

    def _emit_account(self, account: Account) -> None:
        if self._callback is not None:
            self._callback.on_account(account)

    def _emit_contract(self, contract: Contract) -> None:
        if self._callback is not None:
            self._callback.on_contract(contract)

    def _emit_tick(self, tick: TickData) -> None:
        if self._callback is not None:
            self._callback.on_tick(tick)

    def _emit_log(self, msg: str, level: str = "info") -> None:
        if self._callback is not None:
            self._callback.on_log(LogEvent(msg=msg, level=level, gateway=self.name))

    # ---- abstract broker interface --------------------------------------- #
    @abstractmethod
    def connect(self, setting: dict) -> None:
        """Connect + log in. On success, replay contracts/account/positions/orders
        through the callback (``on_contract`` / ``on_account`` / ``on_position`` /
        ``on_order`` / ``on_trade``)."""

    @abstractmethod
    def close(self) -> None:
        """Disconnect and release resources."""

    @abstractmethod
    def send_order(self, req: OrderRequest) -> str:
        """Submit one order. Return the local order id immediately; the order's
        progress is reported asynchronously via ``on_order`` / ``on_trade``."""

    @abstractmethod
    def cancel_order(self, req: CancelRequest) -> None:
        """Request cancellation of a working order (result via ``on_order``)."""

    @abstractmethod
    def query_account(self) -> None:
        """Refresh the account snapshot (result via ``on_account``)."""

    @abstractmethod
    def query_position(self) -> None:
        """Refresh positions (result via ``on_position``)."""

    def subscribe(self, codes: list[str]) -> None:  # noqa: B027 - optional
        """Subscribe to real-time quotes for ``codes`` (result via ``on_tick``).
        Optional: brokers without a quote feed may leave this a no-op."""

    def get_default_setting(self) -> dict[str, object]:
        return dict(self.default_setting)
