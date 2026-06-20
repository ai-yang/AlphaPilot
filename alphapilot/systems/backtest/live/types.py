"""Typed requests / results for the daily live-trade signal feature."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PortfolioState:
    """Portfolio snapshot *as of the close of* ``date`` (the input to the next day).

    ``positions`` maps instrument -> share amount. ``cash`` is available cash.
    """

    date: str
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DailySignalRequest:
    """Generate today's trades for a strategy given yesterday's portfolio state.

    Strategy source is either a saved asset (``strategy_name``) or a manual triple
    (``factor_path`` + ``model_pickle_path`` + ``yaml_params``). Manual fields, when set,
    override the asset-derived values.
    """

    strategy_name: str | None = None
    factor_path: str | Path | None = None
    model_pickle_path: str | Path | None = None
    yaml_params: Any = None
    date: str | None = None
    state_path: str | Path | None = None
    use_local: bool | None = None
    qlib_template_dir: str | None = None
    refresh_data: bool = False
    # First-run seed (used only when no prior state file exists):
    init_cash: float | None = None
    benchmark: str | None = None
    # Factor data binding (defaults resolve from the strategy asset metadata / market default):
    market: str | None = None
    factor_data_dir: str | Path | None = None


@dataclass
class DailyTradeResult:
    """Today's trade plan + resulting portfolio."""

    date: str
    trades: Any           # DataFrame: buy/sell rows (status 1=买入, -1=卖出)
    holdings: Any         # DataFrame: target holdings after the day
    scores: Any           # Series/DataFrame: today's per-stock model scores
    new_state: PortfolioState
    report: Any = None    # report_normal row (return/cost/turnover/account)
    info: dict[str, Any] = field(default_factory=dict)
