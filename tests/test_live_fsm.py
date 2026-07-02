"""Phase 1 unit tests: the four guarded state machines (incl. illegal-transition rejection)."""

from __future__ import annotations

from datetime import datetime

import pytest

from alphapilot.systems.live.config import RunMode
from alphapilot.systems.live.fsm import order_fsm
from alphapilot.systems.live.fsm.base import IllegalTransition
from alphapilot.systems.live.fsm.connection_fsm import ConnectionMachine, ConnectionState
from alphapilot.systems.live.fsm.runmode_fsm import RunModeMachine
from alphapilot.systems.live.fsm.session_fsm import (
    SessionClock,
    SessionState,
    can_cancel_at,
    session_state_at,
)
from alphapilot.systems.live.types import Direction, Exchange, Order, OrderStatus


# --------------------------------------------------------------------------- #
# order_fsm
# --------------------------------------------------------------------------- #
def _order() -> Order:
    return Order(order_id="o1", code="600000", exchange=Exchange.SSE,
                 direction=Direction.LONG, volume=1000, status=OrderStatus.SUBMITTING)


def test_order_fsm_legal_lifecycle() -> None:
    o = _order()
    order_fsm.advance(o, OrderStatus.NOTTRADED)
    order_fsm.advance(o, OrderStatus.PARTTRADED, traded=300)
    assert o.traded == 300 and o.is_active()
    order_fsm.advance(o, OrderStatus.ALLTRADED, traded=1000)
    assert o.status is OrderStatus.ALLTRADED and not o.is_active()
    assert order_fsm.is_terminal(o.status)


def test_order_fsm_rejects_regression() -> None:
    o = _order()
    order_fsm.advance(o, OrderStatus.ALLTRADED, traded=1000)
    with pytest.raises(IllegalTransition):
        order_fsm.advance(o, OrderStatus.NOTTRADED)   # can't un-fill a filled order


def test_order_fsm_rejects_traded_regression() -> None:
    o = _order()
    order_fsm.advance(o, OrderStatus.PARTTRADED, traded=500)
    with pytest.raises(IllegalTransition):
        order_fsm.advance(o, OrderStatus.PARTTRADED, traded=200)  # traded went backwards


def test_status_for_fill() -> None:
    assert order_fsm.status_for_fill(1000, 0) is OrderStatus.NOTTRADED
    assert order_fsm.status_for_fill(1000, 400) is OrderStatus.PARTTRADED
    assert order_fsm.status_for_fill(1000, 1000) is OrderStatus.ALLTRADED


# --------------------------------------------------------------------------- #
# session_fsm
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "hhmm,state",
    [
        ((9, 0), SessionState.PRE_OPEN),
        ((9, 20), SessionState.CALL_AUCTION_OPEN),
        ((10, 0), SessionState.CONTINUOUS_AM),
        ((12, 0), SessionState.LUNCH_BREAK),
        ((14, 0), SessionState.CONTINUOUS_PM),
        ((14, 58), SessionState.CALL_AUCTION_CLOSE),
        ((15, 30), SessionState.POST_CLOSE),
    ],
)
def test_session_state_at(hhmm, state) -> None:
    dt = datetime(2026, 7, 1, hhmm[0], hhmm[1])
    assert session_state_at(dt, is_trading_day=True) is state


def test_session_state_non_trading_day_is_closed() -> None:
    assert session_state_at(datetime(2026, 7, 1, 10, 0), is_trading_day=False) is SessionState.CLOSED


def test_session_cancel_freeze_window() -> None:
    # cancels allowed before 09:20, frozen 09:20–09:25
    assert can_cancel_at(datetime(2026, 7, 1, 9, 18), SessionState.CALL_AUCTION_OPEN)
    assert not can_cancel_at(datetime(2026, 7, 1, 9, 22), SessionState.CALL_AUCTION_OPEN)
    assert can_cancel_at(datetime(2026, 7, 1, 10, 0), SessionState.CONTINUOUS_AM)


def test_session_clock_advances_forward_over_a_day() -> None:
    now = {"t": datetime(2026, 7, 1, 9, 0)}
    clock = SessionClock(now_fn=lambda: now["t"])
    assert clock.state is SessionState.PRE_OPEN
    seq = [
        (datetime(2026, 7, 1, 9, 20), SessionState.CALL_AUCTION_OPEN, True),
        (datetime(2026, 7, 1, 10, 0), SessionState.CONTINUOUS_AM, True),
        (datetime(2026, 7, 1, 12, 0), SessionState.LUNCH_BREAK, False),
        (datetime(2026, 7, 1, 14, 0), SessionState.CONTINUOUS_PM, True),
        (datetime(2026, 7, 1, 14, 58), SessionState.CALL_AUCTION_CLOSE, True),
        (datetime(2026, 7, 1, 15, 30), SessionState.POST_CLOSE, False),
    ]
    for t, state, submittable in seq:
        now["t"] = t
        assert clock.tick() is state
        assert clock.can_submit() is submittable


def test_session_clock_rejects_backward_jump() -> None:
    clock = SessionClock(now_fn=lambda: datetime(2026, 7, 1, 15, 30))
    clock.tick()  # POST_CLOSE
    clock._now_fn = lambda: datetime(2026, 7, 1, 10, 0)  # jump back to morning
    with pytest.raises(IllegalTransition):
        clock.tick()


# --------------------------------------------------------------------------- #
# connection_fsm
# --------------------------------------------------------------------------- #
def test_connection_legal_path_and_ready() -> None:
    c = ConnectionMachine()
    c.transition(ConnectionState.CONNECTING)
    c.transition(ConnectionState.CONNECTED)
    c.transition(ConnectionState.LOGGED_IN)
    assert c.is_ready()
    c.transition(ConnectionState.DISCONNECTED)  # drop
    assert not c.is_ready()


def test_connection_rejects_skipping_states() -> None:
    c = ConnectionMachine()
    with pytest.raises(IllegalTransition):
        c.transition(ConnectionState.LOGGED_IN)  # can't log in before connecting


# --------------------------------------------------------------------------- #
# runmode_fsm
# --------------------------------------------------------------------------- #
def test_runmode_ladder_and_direct_live_rejected() -> None:
    m = RunModeMachine(RunMode.DRY_RUN)
    with pytest.raises(IllegalTransition):
        m.set_mode(RunMode.LIVE)             # must pass through PAPER
    m.set_mode(RunMode.PAPER)
    m.set_mode(RunMode.LIVE)
    assert m.mode == RunMode.LIVE


def test_runmode_killswitch_blocks_submission() -> None:
    m = RunModeMachine(RunMode.PAPER)
    assert m.can_submit_orders()
    m.halt("manual kill-switch")
    assert not m.can_submit_orders()
    assert m.halt_reason == "manual kill-switch"
    m.resume()
    assert m.can_submit_orders()


def test_runmode_dry_run_never_submits() -> None:
    m = RunModeMachine(RunMode.DRY_RUN)
    assert not m.can_submit_orders()
    assert m.is_dry_run()
