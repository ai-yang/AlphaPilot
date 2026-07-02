"""Gateway connection FSM.

A dropped connection is a safety event: the engine must stop sending new orders
immediately and, on reconnect, reconcile the real account **before** resuming.
This machine tracks the connection lifecycle so the engine can enforce that.
"""

from __future__ import annotations

from enum import Enum

from alphapilot.systems.live.fsm.base import check_transition


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"       # socket up, not yet logged in
    LOGGED_IN = "logged_in"       # ready to trade
    ERROR = "error"


ALLOWED: dict[ConnectionState, set[ConnectionState]] = {
    ConnectionState.DISCONNECTED: {ConnectionState.CONNECTING},
    ConnectionState.CONNECTING: {ConnectionState.CONNECTED, ConnectionState.ERROR, ConnectionState.DISCONNECTED},
    ConnectionState.CONNECTED: {ConnectionState.LOGGED_IN, ConnectionState.ERROR, ConnectionState.DISCONNECTED},
    ConnectionState.LOGGED_IN: {ConnectionState.DISCONNECTED, ConnectionState.ERROR},
    ConnectionState.ERROR: {ConnectionState.CONNECTING, ConnectionState.DISCONNECTED},
}


class ConnectionMachine:
    """Guarded connection state machine."""

    def __init__(self) -> None:
        self.state = ConnectionState.DISCONNECTED

    def transition(self, target: ConnectionState) -> ConnectionState:
        check_transition(ALLOWED, self.state, target, label="connection")
        self.state = target
        return self.state

    def is_ready(self) -> bool:
        return self.state == ConnectionState.LOGGED_IN
