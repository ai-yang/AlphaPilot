"""Shared types and protocols for timing strategies and live-ready execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

import pandas as pd

OrderAction = Literal["buy", "sell", "target_percent", "target_shares", "close"]


@dataclass(frozen=True)
class OrderIntent:
    """Strategy output that can be consumed by backtest or live adapters."""

    datetime: pd.Timestamp | str
    instrument: str
    action: OrderAction
    quantity: float | None = None
    target_percent: float | None = None
    reason: str = ""


@dataclass
class PortfolioState:
    """Cash and long-only positions for timing backtests."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    cost_basis: dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimingContext:
    """Runtime context passed to strategies."""

    params: dict[str, Any] = field(default_factory=dict)
    freq: str = "day"
    metadata: dict[str, Any] = field(default_factory=dict)


class TimingStrategy(Protocol):
    """Batch strategy interface used by the v1 timing backtest engine."""

    name: str

    def generate_signals(self, bars: pd.DataFrame, context: TimingContext) -> pd.DataFrame:
        """Return columns ``datetime/instrument/signal/target_percent/score/reason``."""


class EventTimingStrategy(Protocol):
    """Event-style protocol reserved for later live/vn.py integration."""

    name: str

    def on_bar(self, bar: pd.Series, context: TimingContext) -> list[OrderIntent]:
        """Return order intents for one bar."""


class OrderStatus(str, Enum):
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ExecutionReport:
    order_id: str
    status: OrderStatus
    instrument: str
    datetime: pd.Timestamp | str
    action: OrderAction
    filled_quantity: float = 0.0
    price: float | None = None
    cost: float = 0.0
    message: str = ""


class BrokerGateway(Protocol):
    """Live-trading adapter boundary; vn.py can implement this later."""

    def submit_order(self, intent: OrderIntent) -> ExecutionReport:
        """Submit one order intent."""

    def cancel_order(self, order_id: str) -> ExecutionReport:
        """Cancel one order."""

    def query_account(self) -> dict[str, Any]:
        """Return account snapshot."""

    def query_positions(self) -> dict[str, float]:
        """Return current positions."""


@dataclass
class TimingBacktestRequest:
    strategy_name: str
    symbols: list[str] | str | None = None
    stock_csv: str | Path | None = None
    code_column: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    freq: str = "day"
    data_dir: str | Path | None = None
    adjust_mode: str = "backward"
    cash: float = 100000.0
    target_percent: float = 1.0
    open_cost: float = 0.0002
    close_cost: float = 0.0008
    min_cost: float = 5.0
    slippage: float = 0.0
    trade_unit: int = 100
    strategy_params: dict[str, Any] = field(default_factory=dict)
    output_dir: str | Path | None = None


@dataclass
class TimingBacktestResult:
    summary: dict[str, Any]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    signals: pd.DataFrame
    artifact_dir: Path
