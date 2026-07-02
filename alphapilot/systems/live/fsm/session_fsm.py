"""Trading-session clock FSM (A-share schedule).

The session state machine gates *what is legal when*: opening call-auction orders
(09:15–09:25) must only go in the auction window; continuous-session cancels are
only legal 09:30–11:30 / 13:00–14:57; the closing call auction is 14:57–15:00.
The execution algos (call-auction / TWAP) key off this state.

The clock is **injected** (``now_fn``) so tests drive a full trading day with a
simulated clock instead of waiting on the wall clock; the trading-day predicate
(``is_trading_day_fn``) lets a real calendar be plugged in later.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Callable

from alphapilot.systems.live.fsm.base import check_transition


class SessionState(str, Enum):
    PRE_OPEN = "pre_open"                 # before 09:15
    CALL_AUCTION_OPEN = "call_auction_open"   # 09:15–09:30 (incl. 09:25–09:30 cold period)
    CONTINUOUS_AM = "continuous_am"       # 09:30–11:30
    LUNCH_BREAK = "lunch_break"           # 11:30–13:00
    CONTINUOUS_PM = "continuous_pm"       # 13:00–14:57
    CALL_AUCTION_CLOSE = "call_auction_close"  # 14:57–15:00
    POST_CLOSE = "post_close"             # after 15:00 on a trading day
    CLOSED = "closed"                     # non-trading day


# Ordered intraday windows: (start_inclusive, end_exclusive, state).
_WINDOWS: list[tuple[time, time, SessionState]] = [
    (time(0, 0), time(9, 15), SessionState.PRE_OPEN),
    (time(9, 15), time(9, 30), SessionState.CALL_AUCTION_OPEN),
    (time(9, 30), time(11, 30), SessionState.CONTINUOUS_AM),
    (time(11, 30), time(13, 0), SessionState.LUNCH_BREAK),
    (time(13, 0), time(14, 57), SessionState.CONTINUOUS_PM),
    (time(14, 57), time(15, 0), SessionState.CALL_AUCTION_CLOSE),
    (time(15, 0), time(23, 59, 59), SessionState.POST_CLOSE),
]

# Legal forward transitions across a day (plus CLOSED on non-trading days).
_ORDER = [
    SessionState.PRE_OPEN,
    SessionState.CALL_AUCTION_OPEN,
    SessionState.CONTINUOUS_AM,
    SessionState.LUNCH_BREAK,
    SessionState.CONTINUOUS_PM,
    SessionState.CALL_AUCTION_CLOSE,
    SessionState.POST_CLOSE,
]
ALLOWED: dict[SessionState, set[SessionState]] = {}
for _i, _s in enumerate(_ORDER):
    # A state may stay put, advance to any later state (clock can jump on coarse
    # polling), or drop to CLOSED (day rolls over / market holiday detected).
    ALLOWED[_s] = set(_ORDER[_i:]) | {SessionState.CLOSED}
ALLOWED[SessionState.CLOSED] = {SessionState.CLOSED, SessionState.PRE_OPEN}
# End of day rolls over to the next trading day's pre-open (or a holiday -> CLOSED).
ALLOWED[SessionState.POST_CLOSE] |= {SessionState.PRE_OPEN}


def session_state_at(dt: datetime, is_trading_day: bool = True) -> SessionState:
    """The session state at wall-clock ``dt`` (``CLOSED`` on non-trading days)."""
    if not is_trading_day:
        return SessionState.CLOSED
    t = dt.time()
    for start, end, state in _WINDOWS:
        if start <= t < end:
            return state
    return SessionState.POST_CLOSE


def can_submit(state: SessionState) -> bool:
    """Orders may be submitted in the auction windows and continuous sessions."""
    return state in (
        SessionState.CALL_AUCTION_OPEN,
        SessionState.CONTINUOUS_AM,
        SessionState.CONTINUOUS_PM,
        SessionState.CALL_AUCTION_CLOSE,
    )


def can_cancel_at(dt: datetime, state: SessionState) -> bool:
    """Cancels are legal in continuous sessions, and in the opening auction only
    before 09:20 (09:20–09:25 is the no-cancel freeze)."""
    if state in (SessionState.CONTINUOUS_AM, SessionState.CONTINUOUS_PM):
        return True
    if state == SessionState.CALL_AUCTION_OPEN:
        return dt.time() < time(9, 20)
    return False


class SessionClock:
    """A guarded session state machine driven by an injected clock."""

    def __init__(
        self,
        now_fn: Callable[[], datetime] = datetime.now,
        is_trading_day_fn: Callable[[datetime], bool] | None = None,
    ) -> None:
        self._now_fn = now_fn
        self._is_trading_day_fn = is_trading_day_fn or (lambda _dt: True)
        self.state: SessionState = self.current_state()

    def current_state(self) -> SessionState:
        now = self._now_fn()
        return session_state_at(now, self._is_trading_day_fn(now))

    def tick(self) -> SessionState:
        """Re-read the clock and advance the machine (validating the transition)."""
        target = self.current_state()
        if target != self.state:
            check_transition(ALLOWED, self.state, target, label="session")
            self.state = target
        return self.state

    def can_submit(self) -> bool:
        return can_submit(self.state)

    def can_cancel(self) -> bool:
        return can_cancel_at(self._now_fn(), self.state)
