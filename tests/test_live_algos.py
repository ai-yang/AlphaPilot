"""Phase 3 integration tests: execution algos driven by a simulated session clock."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alphapilot.systems.live.algos import AlgoState, CallAuctionAlgo, TwapAlgo
from alphapilot.systems.live.brokers.paper import PaperBroker
from alphapilot.systems.live.clock import SimulatedClock
from alphapilot.systems.live.config import LiveConfig, RunMode
from alphapilot.systems.live.engine import LiveEngine
from alphapilot.systems.live.ledger import Ledger
from alphapilot.systems.live.types import Exchange, OrderRequest

KEY = "600000.SSE"


def _engine(tmp_path: Path, clock: SimulatedClock) -> LiveEngine:
    broker = PaperBroker(cash=1_000_000.0, prices={KEY: 10.0}, open_cost=0.0, min_cost=0.0)
    cfg = LiveConfig(mode=RunMode.PAPER, ledger_dir=tmp_path / "ledger")
    engine = LiveEngine(cfg, broker, ledger=Ledger(tmp_path / "ledger"), now_fn=clock)
    engine.connect({})
    return engine


def test_call_auction_algo_places_only_in_the_auction_window(tmp_path: Path) -> None:
    clock = SimulatedClock(datetime(2026, 7, 1, 9, 0))          # PRE_OPEN
    engine = _engine(tmp_path, clock)
    algo = CallAuctionAlgo(engine, [OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0)], window="open")

    assert algo.step() == AlgoState.ARMED                        # pre-open: nothing yet
    assert engine.oms.get_position(KEY) is None

    clock.set(datetime(2026, 7, 1, 9, 20))                       # opening call auction
    assert algo.step() == AlgoState.SUBMITTED
    assert engine.oms.get_position(KEY).volume == 1000

    clock.set(datetime(2026, 7, 1, 10, 0))                       # continuous -> algo done
    assert algo.step() == AlgoState.DONE


def test_twap_slices_across_continuous_session(tmp_path: Path) -> None:
    clock = SimulatedClock(datetime(2026, 7, 1, 10, 0))          # CONTINUOUS_AM
    engine = _engine(tmp_path, clock)
    algo = TwapAlgo(engine, OrderRequest.buy("600000", Exchange.SSE, 1000, 10.0), slices=4)

    assert algo._child_volumes == [300, 300, 200, 200]          # 10 lots split 4 ways
    for _ in range(4):
        algo.step()
    assert algo.state == AlgoState.DONE
    assert algo.remaining_children == 0
    assert engine.oms.get_position(KEY).volume == 1000
    assert len(algo.order_ids) == 4
