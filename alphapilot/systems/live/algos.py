"""Execution algorithms — small FSMs that place orders at the right time.

Each algo is a tiny state machine stepped by the engine's clock. The call-auction
algo places its whole plan inside the opening/closing call-auction window (what the
user asked for: "集合竞价买入卖出"); the TWAP algo slices one order across the
continuous session. Both submit through the engine's guarded ``submit`` (so the
risk gate still applies), and both are driven by :meth:`SessionClock.tick`, so a
simulated clock replays a whole day in a unit test.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from alphapilot.systems.live.fsm.session_fsm import SessionState
from alphapilot.systems.live.types import OrderRequest


class AlgoState(str, Enum):
    ARMED = "armed"
    SUBMITTED = "submitted"
    WORKING = "working"
    DONE = "done"


class CallAuctionAlgo:
    """Place a whole plan of requests inside a call-auction window.

    ``window="open"`` targets the 09:15–09:25 opening auction; ``"close"`` the
    14:57–15:00 closing auction.
    """

    def __init__(self, engine: Any, requests: list[OrderRequest], *, window: str = "open") -> None:
        self.engine = engine
        self.requests = list(requests)
        self.window = window
        self.state = AlgoState.ARMED
        self.order_ids: list[str] = []

    @property
    def _target_state(self) -> SessionState:
        return SessionState.CALL_AUCTION_OPEN if self.window == "open" else SessionState.CALL_AUCTION_CLOSE

    def step(self) -> AlgoState:
        session_state = self.engine.session.tick()
        if self.state == AlgoState.ARMED and session_state == self._target_state:
            for req in self.requests:
                oid = self.engine.submit(req)
                if oid:
                    self.order_ids.append(oid)
            self.state = AlgoState.SUBMITTED
        elif self.state == AlgoState.SUBMITTED and session_state != self._target_state:
            # auction window passed; the plan is placed (fills/uncrossed handled by OMS)
            self.state = AlgoState.DONE
        return self.state


class TwapAlgo:
    """Slice one order into ``slices`` children across the continuous session."""

    def __init__(self, engine: Any, request: OrderRequest, *, slices: int = 4, lot_size: int = 100) -> None:
        self.engine = engine
        self.request = request
        self.slices = max(1, int(slices))
        self.lot_size = lot_size
        self.state = AlgoState.ARMED
        self.submitted = 0
        self.order_ids: list[str] = []
        self._child_volumes = self._plan_children()

    def _plan_children(self) -> list[float]:
        lot = self.lot_size if self.lot_size > 0 else 1
        total_lots = int(self.request.volume // lot)
        if total_lots <= 0:
            return []
        base = total_lots // self.slices
        rem = total_lots - base * self.slices
        children: list[float] = []
        for i in range(self.slices):
            lots = base + (1 if i < rem else 0)
            if lots > 0:
                children.append(float(lots * lot))
        return children

    def step(self) -> AlgoState:
        session_state = self.engine.session.tick()
        continuous = session_state in (SessionState.CONTINUOUS_AM, SessionState.CONTINUOUS_PM)
        if self.submitted >= len(self._child_volumes):
            self.state = AlgoState.DONE
            return self.state
        if continuous:
            vol = self._child_volumes[self.submitted]
            child = OrderRequest(
                code=self.request.code, exchange=self.request.exchange,
                direction=self.request.direction, volume=vol, price=self.request.price,
                type=self.request.type, reference=f"{self.request.reference}:twap{self.submitted}",
            )
            oid = self.engine.submit(child)
            if oid:
                self.order_ids.append(oid)
            self.submitted += 1
            self.state = AlgoState.WORKING if self.submitted < len(self._child_volumes) else AlgoState.DONE
        return self.state

    @property
    def remaining_children(self) -> int:
        return max(len(self._child_volumes) - self.submitted, 0)
