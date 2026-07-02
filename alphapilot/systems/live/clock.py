"""Clocks for the session FSM / engine.

The engine and algos read *the current time* through an injected clock so tests
can drive a whole trading day deterministically (``SimulatedClock``) instead of
sleeping against the wall clock (``WallClock``).
"""

from __future__ import annotations

from datetime import datetime, timedelta


class WallClock:
    """Real time (naive local)."""

    def now(self) -> datetime:
        return datetime.now()

    def __call__(self) -> datetime:
        return self.now()


class SimulatedClock:
    """A controllable clock for tests / replay."""

    def __init__(self, start: datetime) -> None:
        self._t = start

    def now(self) -> datetime:
        return self._t

    def __call__(self) -> datetime:
        return self._t

    def set(self, t: datetime) -> None:
        self._t = t

    def advance(self, delta: timedelta) -> datetime:
        self._t = self._t + delta
        return self._t
