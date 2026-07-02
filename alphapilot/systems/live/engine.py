"""LiveEngine — the event-loop hub of the live-trading subsystem.

Ownership:
* installs itself as the gateway's callback sink, fanning every normalized event
  into the :class:`OMS` (state) and the :class:`Ledger` (audit);
* owns the safety FSMs (:class:`RunModeMachine`, :class:`ConnectionMachine`,
  :class:`SessionClock`);
* exposes the single guarded path for acting on the market — :meth:`submit` /
  :meth:`cancel` / :meth:`halt` / :meth:`reconcile_and_resume`.

The engine is broker-agnostic: it talks only to the :class:`BrokerGateway` port,
so PAPER (PaperBroker), SIM (SimBroker) and LIVE (VnpyBrokerAdapter) all run the
same logic. The clock is injected so a whole trading day can be simulated in tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from alphapilot.systems.live.config import LiveConfig, RunMode
from alphapilot.systems.live.fsm.connection_fsm import ConnectionMachine, ConnectionState
from alphapilot.systems.live.fsm.runmode_fsm import RunModeMachine
from alphapilot.systems.live.fsm.session_fsm import SessionClock
from alphapilot.systems.live.gateway import BrokerGateway
from alphapilot.systems.live.ledger import Ledger
from alphapilot.systems.live.oms import OMS
from alphapilot.systems.live.types import (
    Account,
    Contract,
    LogEvent,
    Order,
    OrderRequest,
    Position,
    TickData,
    Trade,
)


class LiveEngine:
    """Coordinates gateway, OMS, audit ledger and the safety state machines."""

    def __init__(
        self,
        config: LiveConfig,
        gateway: BrokerGateway,
        *,
        now_fn: Callable[[], Any] | None = None,
        is_trading_day_fn: Callable[[Any], bool] | None = None,
        ledger: Ledger | None = None,
        risk: Any = None,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.oms = OMS()
        self.runmode = RunModeMachine(config.mode)
        self.connection = ConnectionMachine()
        self.session = SessionClock(now_fn or datetime.now, is_trading_day_fn)
        self.ledger = ledger or Ledger(config.ledger_dir)
        self.risk = risk  # installed in Phase 3; None => no pre-trade checks
        gateway.register_callback(self)

    # ---- GatewayCallback (fan-out to OMS + ledger) ----------------------- #
    def on_order(self, order: Order) -> None:
        self.oms.on_order(order)
        self.ledger.record("order", order)

    def on_trade(self, trade: Trade) -> None:
        self.oms.on_trade(trade)
        self.ledger.record("trade", trade)

    def on_position(self, position: Position) -> None:
        self.oms.on_position(position)

    def on_account(self, account: Account) -> None:
        self.oms.on_account(account)

    def on_contract(self, contract: Contract) -> None:
        self.oms.on_contract(contract)

    def on_tick(self, tick: TickData) -> None:
        self.oms.on_tick(tick)

    def on_log(self, log: LogEvent) -> None:
        self.oms.on_log(log)

    # ---- lifecycle ------------------------------------------------------- #
    def connect(self, setting: dict | None = None) -> None:
        self.connection.transition(ConnectionState.CONNECTING)
        try:
            self.gateway.connect(setting or {})
        except Exception as exc:  # noqa: BLE001 - surface as connection error
            self.connection.transition(ConnectionState.ERROR)
            self.ledger.record("connect_error", {"error": str(exc)})
            raise
        self.connection.transition(ConnectionState.CONNECTED)
        self.connection.transition(ConnectionState.LOGGED_IN)
        self.ledger.record("connected", {"broker": self.gateway.name, "mode": self.config.mode})

    def close(self) -> None:
        self.gateway.close()
        if self.connection.state != ConnectionState.DISCONNECTED:
            self.connection.transition(ConnectionState.DISCONNECTED)
        self.ledger.record("closed", {"broker": self.gateway.name})

    # ---- guarded actions ------------------------------------------------- #
    def submit(self, req: OrderRequest) -> str | None:
        """The single guarded submission path.

        Returns the broker order id, or ``None`` when the order was not routed
        (dry-run, halted, or rejected by the risk gate — all audited).
        """
        if self.runmode.is_dry_run():
            self.ledger.record("dry_run_intent", req)
            return None
        if not self.runmode.can_submit_orders():
            self.ledger.record("blocked", {"reason": f"halted:{self.runmode.halt_reason}", "req": _req(req)})
            return None
        if self.risk is not None:
            verdict = self.risk.check(req, self.oms, self.session, self.runmode)
            if not verdict.ok:
                self.ledger.record("rejected", {"reason": verdict.reason, "req": _req(req)})
                return None
        order_id = self.gateway.send_order(req)
        self.ledger.record("submit", {"order_id": order_id, "req": _req(req)})
        return order_id

    def cancel(self, order: Order | str) -> None:
        if isinstance(order, str):
            found = self.oms.get_order(order)
            if found is None:
                self.ledger.record("cancel_miss", {"order_id": order})
                return
            order = found
        self.gateway.cancel_order(order.create_cancel())
        self.ledger.record("cancel", {"order_id": order.order_id})

    # ---- safety controls ------------------------------------------------- #
    def halt(self, reason: str = "manual") -> None:
        """Kill-switch: stop new orders and cancel every working order."""
        self.runmode.halt(reason)
        self.ledger.record("halt", {"reason": reason})
        for order in self.oms.get_active_orders():
            try:
                self.gateway.cancel_order(order.create_cancel())
            except Exception as exc:  # noqa: BLE001 - best-effort flatten of working orders
                self.ledger.record("halt_cancel_error", {"order_id": order.order_id, "error": str(exc)})

    def resume(self) -> None:
        self.runmode.resume()
        self.ledger.record("resume", {})

    def handle_disconnect(self, reason: str = "disconnected") -> None:
        """Gateway dropped: halt immediately (no new orders until reconciled)."""
        if self.connection.state != ConnectionState.DISCONNECTED:
            self.connection.transition(ConnectionState.DISCONNECTED)
        self.runmode.halt(reason)
        self.ledger.record("disconnected", {"reason": reason})

    def reconcile_and_resume(self) -> None:
        """After reconnect: re-query the real account/positions, then resume."""
        self.connection.transition(ConnectionState.CONNECTING)
        self.gateway.connect({})
        self.connection.transition(ConnectionState.CONNECTED)
        self.connection.transition(ConnectionState.LOGGED_IN)
        self.gateway.query_account()
        self.gateway.query_position()
        self.runmode.resume()
        self.ledger.record("reconciled", {"buying_power": self.oms.buying_power()})

    # ---- introspection --------------------------------------------------- #
    def tick_session(self):
        return self.session.tick()

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.runmode.mode,
            "halted": self.runmode.halted,
            "connection": self.connection.state.value,
            "session": self.session.state.value,
            "buying_power": self.oms.buying_power(),
            "active_orders": len(self.oms.get_active_orders()),
            "positions": len(self.oms.get_positions()),
        }


def _req(req: OrderRequest) -> dict[str, Any]:
    return {
        "code": req.code, "exchange": req.exchange.value, "direction": req.direction.value,
        "volume": req.volume, "price": req.price, "type": req.type.value, "reference": req.reference,
    }
