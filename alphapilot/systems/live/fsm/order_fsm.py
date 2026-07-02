"""Order lifecycle FSM — enum + active-set + guarded transitions (vn.py-style).

The canonical :class:`~alphapilot.systems.live.types.OrderStatus` enum plus the
transition table here express the order state machine. The OMS advances an order
through it as broker acks/fills arrive; the guard prevents regressions (e.g.
``ALLTRADED -> NOTTRADED``) that would corrupt position/cash accounting.
"""

from __future__ import annotations

from alphapilot.systems.live.fsm.base import IllegalTransition, check_transition
from alphapilot.systems.live.types import Order, OrderStatus

S = OrderStatus

# ``current -> {reachable}``. Active states include themselves (idempotent
# refresh / additional partial fills). Terminal states reach nothing.
ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    S.SUBMITTING: {S.SUBMITTING, S.NOTTRADED, S.PARTTRADED, S.ALLTRADED, S.CANCELLED, S.REJECTED},
    S.NOTTRADED: {S.NOTTRADED, S.PARTTRADED, S.ALLTRADED, S.CANCELLED, S.REJECTED},
    S.PARTTRADED: {S.PARTTRADED, S.ALLTRADED, S.CANCELLED, S.REJECTED},
    S.ALLTRADED: set(),
    S.CANCELLED: set(),
    S.REJECTED: set(),
}

TERMINAL: frozenset[OrderStatus] = frozenset({S.ALLTRADED, S.CANCELLED, S.REJECTED})


def is_terminal(status: OrderStatus) -> bool:
    return status in TERMINAL


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED.get(current, set())


def status_for_fill(volume: float, traded: float) -> OrderStatus:
    """Derive the fill status from cumulative ``traded`` vs order ``volume``."""
    if traded <= 0:
        return OrderStatus.NOTTRADED
    if traded >= volume:
        return OrderStatus.ALLTRADED
    return OrderStatus.PARTTRADED


def advance(order: Order, target: OrderStatus, *, traded: float | None = None, message: str = "") -> Order:
    """Validate + apply a transition on ``order`` in place. Raises on illegal moves.

    ``traded`` (cumulative) must be monotonic and within ``[0, volume]``.
    """
    check_transition(ALLOWED, order.status, target, label="order")
    if traded is not None:
        if traded < order.traded - 1e-9:
            raise IllegalTransition(
                f"traded volume regressed: {order.traded} -> {traded} (order {order.order_id})"
            )
        order.traded = min(float(traded), order.volume)
    order.status = target
    if message:
        order.message = message
    return order
