"""Daily live-trade signal: one-step-forward inference + rebalance reusing the backtest stack."""

from __future__ import annotations

from alphapilot.systems.backtest.live.portfolio_state import (
    init_state,
    load_state,
    save_state,
    state_to_account,
)
from alphapilot.systems.backtest.live.service import generate_daily_signal
from alphapilot.systems.backtest.live.types import (
    DailySignalRequest,
    DailyTradeResult,
    PortfolioState,
)

__all__ = [
    "DailySignalRequest",
    "DailyTradeResult",
    "PortfolioState",
    "generate_daily_signal",
    "load_state",
    "save_state",
    "init_state",
    "state_to_account",
]
