"""Phase 3 unit tests: the pre-trade risk gate, rule by rule."""

from __future__ import annotations

from datetime import datetime

from alphapilot.systems.live.config import RiskLimits, RunMode
from alphapilot.systems.live.fsm.runmode_fsm import RunModeMachine
from alphapilot.systems.live.fsm.session_fsm import SessionClock
from alphapilot.systems.live.oms import OMS
from alphapilot.systems.live.risk import RiskGate
from alphapilot.systems.live.types import Account, Exchange, OrderRequest, Position, TickData


def _permissive() -> RiskLimits:
    return RiskLimits(
        max_order_value=1e12, max_daily_value=1e15, max_position_pct=1.0,
        price_guard_pct=0.1, max_orders_per_day=1000, lot_size=100,
    )


def _oms(cash: float = 1_000_000.0, ticks=None, positions=None) -> OMS:
    oms = OMS()
    oms.on_account(Account(account_id="acc", balance=cash, available=cash))
    for code, px in (ticks or {}).items():
        c, ex = _split(code)
        oms.on_tick(TickData(code=c, exchange=ex, last_price=px))
    for code, (vol, yd) in (positions or {}).items():
        c, ex = _split(code)
        oms.on_position(Position(code=c, exchange=ex, volume=vol, yd_volume=yd))
    return oms


def _split(code: str):
    from alphapilot.systems.live.types import normalize_symbol
    return normalize_symbol(code)


def _ctx():
    return SessionClock(now_fn=lambda: datetime(2026, 7, 1, 10, 0)), RunModeMachine(RunMode.PAPER)


def test_valid_buy_passes() -> None:
    gate = RiskGate(_permissive(), enforce_session=False)
    oms = _oms(ticks={"600000": 10.0})
    session, mode = _ctx()
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0), oms, session, mode)
    assert v.ok


def test_lot_size_rejected() -> None:
    gate = RiskGate(_permissive(), enforce_session=False)
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 150, 10.0), _oms(), *_ctx())
    assert not v.ok and v.rule == "lot_size"


def test_insufficient_cash_rejected() -> None:
    gate = RiskGate(_permissive(), enforce_session=False)
    oms = _oms(cash=5_000.0, ticks={"600000": 10.0})
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0), oms, *_ctx())
    assert not v.ok and v.rule == "insufficient_cash"


def test_insufficient_position_rejected_t_plus_one() -> None:
    gate = RiskGate(_permissive(), enforce_session=False)
    oms = _oms(positions={"600000": (1000, 300)})   # 1000 held, only 300 sellable
    v = gate.check(OrderRequest.sell("600000", Exchange.SSE, 500, 10.0), oms, *_ctx())
    assert not v.ok and v.rule == "insufficient_position"
    # selling within the sellable amount is fine
    ok = gate.check(OrderRequest.sell("600000", Exchange.SSE, 300, 10.0), oms, *_ctx())
    assert ok.ok


def test_price_guard_rejects_fat_finger() -> None:
    gate = RiskGate(_permissive(), enforce_session=False)
    oms = _oms(ticks={"600000": 10.0})
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 100, 12.0), oms, *_ctx())  # +20% vs ref
    assert not v.ok and v.rule == "price_guard"


def test_max_order_value_rejected() -> None:
    limits = _permissive()
    limits.max_order_value = 5_000.0
    gate = RiskGate(limits, enforce_session=False)
    oms = _oms(ticks={"600000": 10.0})
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0), oms, *_ctx())
    assert not v.ok and v.rule == "max_order_value"


def test_max_position_pct_rejected() -> None:
    limits = _permissive()
    limits.max_position_pct = 0.3
    gate = RiskGate(limits, enforce_session=False)
    oms = _oms(cash=100_000.0, ticks={"600000": 10.0})
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 4000, 10.0), oms, *_ctx())  # 40k / 100k
    assert not v.ok and v.rule == "max_position_pct"


def test_duplicate_reference_rejected() -> None:
    gate = RiskGate(_permissive(), enforce_session=False)
    oms = _oms(ticks={"600000": 10.0})
    req = OrderRequest.buy("600000", Exchange.SSE, 100, 10.0, reference="cid-1")
    assert gate.check(req, oms, *_ctx()).ok
    dup = gate.check(OrderRequest.buy("600000", Exchange.SSE, 100, 10.0, reference="cid-1"), oms, *_ctx())
    assert not dup.ok and dup.rule == "duplicate"


def test_max_orders_per_day_rejected() -> None:
    limits = _permissive()
    limits.max_orders_per_day = 1
    gate = RiskGate(limits, enforce_session=False)
    oms = _oms(ticks={"600000": 10.0})
    assert gate.check(OrderRequest.buy("600000", Exchange.SSE, 100, 10.0), oms, *_ctx()).ok
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 100, 10.0), oms, *_ctx())
    assert not v.ok and v.rule == "max_orders_per_day"


def test_session_gate_when_enforced() -> None:
    gate = RiskGate(_permissive(), enforce_session=True)
    oms = _oms(ticks={"600000": 10.0})
    lunch = SessionClock(now_fn=lambda: datetime(2026, 7, 1, 12, 0))  # LUNCH_BREAK
    v = gate.check(OrderRequest.buy("600000", Exchange.SSE, 100, 10.0), oms, lunch, RunModeMachine(RunMode.PAPER))
    assert not v.ok and v.rule == "session"
