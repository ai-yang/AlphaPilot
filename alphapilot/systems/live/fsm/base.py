"""Shared helpers for the small guarded state machines.

We deliberately avoid a third-party FSM library (vn.py doesn't use one either):
each machine is a plain enum + a ``dict[State, set[State]]`` transition table +
a guard that **rejects illegal transitions**. Rejecting illegal transitions is a
safety property in its own right (a live-trading kill-switch that could silently
un-halt, or an order that regresses from ALLTRADED, is a bug we want to raise on),
and it is trivially unit-testable.
"""

from __future__ import annotations

from typing import Hashable, Mapping


class IllegalTransition(ValueError):
    """Raised when a state transition is not permitted by the machine's table."""


def check_transition(
    allowed: Mapping[Hashable, set], current: Hashable, target: Hashable, *, label: str = "state"
) -> None:
    """Raise :class:`IllegalTransition` unless ``current -> target`` is allowed.

    ``allowed[current]`` is the set of states reachable in one step from
    ``current`` (include ``current`` itself to permit idempotent refreshes).
    """
    permitted = allowed.get(current, set())
    if target not in permitted:
        raise IllegalTransition(
            f"illegal {label} transition: {getattr(current, 'name', current)} -> "
            f"{getattr(target, 'name', target)} (allowed: "
            f"{sorted(getattr(s, 'name', s) for s in permitted)})"
        )
