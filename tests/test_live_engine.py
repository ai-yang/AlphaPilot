"""Phase 2 integration tests: LiveEngine end-to-end against Paper/Sim brokers.

All deterministic and offline — no vn.py, no broker SDK, no wall-clock waiting.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from alphapilot.systems.live.brokers.paper import PaperBroker
from alphapilot.systems.live.brokers.sim import SimBroker
from alphapilot.systems.live.clock import SimulatedClock
from alphapilot.systems.live.config import LiveConfig, RunMode
from alphapilot.systems.live.engine import LiveEngine
from alphapilot.systems.live.ledger import Ledger
from alphapilot.systems.live.types import Exchange, OrderRequest, OrderStatus

KEY = "600000.SSE"


def _engine(tmp_path: Path, broker, mode: str = RunMode.PAPER, clock=None) -> LiveEngine:
    cfg = LiveConfig(mode=mode, ledger_dir=tmp_path / "ledger")
    return LiveEngine(cfg, broker, ledger=Ledger(tmp_path / "ledger"),
                      now_fn=clock or SimulatedClock(datetime(2026, 7, 1, 10, 0)))


def _kinds(engine: LiveEngine) -> set[str]:
    return {e["kind"] for e in engine.ledger.events()}


def test_paper_buy_end_to_end(tmp_path: Path) -> None:
    broker = PaperBroker(cash=100_000.0, prices={KEY: 10.0}, open_cost=0.0, min_cost=0.0)
    engine = _engine(tmp_path, broker)
    engine.connect({})
    assert engine.oms.buying_power() == 100_000.0

    order_id = engine.submit(OrderRequest.buy("600000", Exchange.SSE, volume=1000, price=10.0))
    assert order_id is not None

    pos = engine.oms.get_position(KEY)
    assert pos.volume == 1000
    assert pos.yd_volume == 0                      # bought today -> not sellable (T+1)
    assert engine.oms.buying_power() == 90_000.0   # 100k - 1000*10
    assert engine.oms.get_order(order_id).status is OrderStatus.ALLTRADED
    assert {"connected", "submit", "order", "trade"} <= _kinds(engine)


def test_dry_run_submits_nothing(tmp_path: Path) -> None:
    broker = PaperBroker(cash=100_000.0, prices={KEY: 10.0})
    engine = _engine(tmp_path, broker, mode=RunMode.DRY_RUN)
    engine.connect({})
    assert engine.submit(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0)) is None
    assert engine.oms.get_position(KEY) is None
    assert "dry_run_intent" in _kinds(engine)


def test_sim_reject(tmp_path: Path) -> None:
    broker = SimBroker(cash=100_000.0, prices={KEY: 10.0}, reject_codes={"600000"})
    engine = _engine(tmp_path, broker)
    engine.connect({})
    order_id = engine.submit(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0))
    assert engine.oms.get_order(order_id).status is OrderStatus.REJECTED
    assert engine.oms.get_position(KEY) is None
    assert engine.oms.get_active_orders() == []


def test_sim_partial_then_cancel(tmp_path: Path) -> None:
    broker = SimBroker(cash=100_000.0, prices={KEY: 10.0}, partial_ratio=0.5,
                       open_cost=0.0, min_cost=0.0)
    engine = _engine(tmp_path, broker)
    engine.connect({})
    order_id = engine.submit(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0))

    order = engine.oms.get_order(order_id)
    assert order.status is OrderStatus.PARTTRADED
    assert order.traded == 500 and order.is_active()
    assert engine.oms.get_position(KEY).volume == 500

    engine.cancel(order_id)
    assert engine.oms.get_order(order_id).status is OrderStatus.CANCELLED
    assert engine.oms.get_active_orders() == []


def test_kill_switch_blocks_and_flattens(tmp_path: Path) -> None:
    broker = SimBroker(cash=100_000.0, prices={KEY: 10.0}, partial_ratio=0.5,
                       open_cost=0.0, min_cost=0.0)
    engine = _engine(tmp_path, broker)
    engine.connect({})
    order_id = engine.submit(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0))
    assert engine.oms.get_order(order_id).is_active()   # 500 still working

    engine.halt("panic")
    # working order cancelled by the kill-switch...
    assert engine.oms.get_order(order_id).status is OrderStatus.CANCELLED
    # ...and further submits are blocked
    assert engine.submit(OrderRequest.buy("000001", Exchange.SZSE, 100, 12.0)) is None
    assert "halt" in _kinds(engine)

    engine.resume()
    assert engine.runmode.can_submit_orders()


def test_disconnect_halts_then_reconcile_resumes(tmp_path: Path) -> None:
    broker = PaperBroker(cash=100_000.0, prices={KEY: 10.0})
    engine = _engine(tmp_path, broker)
    engine.connect({})

    engine.handle_disconnect("socket drop")
    assert engine.runmode.halted
    assert engine.submit(OrderRequest.buy("600000", Exchange.SSE, 100, 10.0)) is None

    engine.reconcile_and_resume()
    assert not engine.runmode.halted
    assert engine.connection.is_ready()
    assert {"disconnected", "reconciled"} <= _kinds(engine)


def test_engine_applies_risk_gate(tmp_path: Path) -> None:
    from alphapilot.systems.live.config import RiskLimits
    from alphapilot.systems.live.risk import RiskGate

    broker = PaperBroker(cash=5_000.0, prices={KEY: 10.0}, open_cost=0.0, min_cost=0.0)
    cfg = LiveConfig(mode=RunMode.PAPER, ledger_dir=tmp_path / "ledger")
    gate = RiskGate(
        RiskLimits(max_order_value=1e12, max_daily_value=1e15, max_position_pct=1.0,
                   price_guard_pct=0.1, max_orders_per_day=1000, lot_size=100),
        enforce_session=False,
    )
    engine = LiveEngine(cfg, broker, ledger=Ledger(tmp_path / "ledger"),
                        now_fn=SimulatedClock(datetime(2026, 7, 1, 10, 0)), risk=gate)
    engine.connect({})
    # 1000 * 10 = 10000 > buying power 5000 -> risk gate rejects, order never routed
    assert engine.submit(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0)) is None
    assert engine.oms.get_position(KEY) is None
    assert "rejected" in _kinds(engine)


def test_t_plus_one_roll_via_broker_snapshot(tmp_path: Path) -> None:
    broker = PaperBroker(cash=100_000.0, prices={KEY: 10.0}, open_cost=0.0, min_cost=0.0)
    engine = _engine(tmp_path, broker)
    engine.connect({})
    engine.submit(OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0))
    assert engine.oms.available_shares(KEY) == 0        # today's buy not sellable

    broker.roll_new_day()          # next trading day at the broker
    broker.query_position()        # broker re-publishes authoritative snapshot
    assert engine.oms.available_shares(KEY) == 1000     # now sellable
