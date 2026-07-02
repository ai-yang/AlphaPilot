"""Small guarded state machines for the live-trading subsystem.

Four focused FSMs (order lifecycle / session clock / connection / run-mode),
each a plain enum + transition table + guard. See the individual modules.
"""

from alphapilot.systems.live.fsm.base import IllegalTransition, check_transition
from alphapilot.systems.live.fsm.connection_fsm import ConnectionMachine, ConnectionState
from alphapilot.systems.live.fsm.runmode_fsm import RunModeMachine
from alphapilot.systems.live.fsm.session_fsm import (
    SessionClock,
    SessionState,
    can_cancel_at,
    can_submit,
    session_state_at,
)
from alphapilot.systems.live.fsm import order_fsm

__all__ = [
    "ConnectionMachine",
    "ConnectionState",
    "IllegalTransition",
    "RunModeMachine",
    "SessionClock",
    "SessionState",
    "can_cancel_at",
    "can_submit",
    "check_transition",
    "order_fsm",
    "session_state_at",
]
