"""Load / save / roll the daily portfolio state (cash + holdings) as JSON.

The state file is maintained by the tool: it reads yesterday's state, runs one trading
day, and writes today's state back (auto-roll). The qlib account seed format
(``{"cash": x, "SH600000": shares, ...}``) is produced by :func:`state_to_account`.
"""

from __future__ import annotations

import json
from pathlib import Path

from alphapilot.systems.backtest.live.types import PortfolioState


def load_state(path: str | Path) -> PortfolioState | None:
    p = Path(path).expanduser()
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return PortfolioState(
        date=str(data.get("date", "")),
        cash=float(data["cash"]),
        positions={str(k): float(v) for k, v in (data.get("positions") or {}).items()},
        metadata=dict(data.get("metadata") or {}),
    )


def save_state(state: PortfolioState, path: str | Path) -> Path:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "date": state.date,
                "cash": state.cash,
                "positions": state.positions,
                "metadata": state.metadata,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


def init_state(
    cash: float,
    *,
    positions: dict[str, float] | None = None,
    date: str = "",
    metadata: dict | None = None,
) -> PortfolioState:
    """First-run seed: starting cash + optional opening holdings."""
    return PortfolioState(
        date=date,
        cash=float(cash),
        positions={str(k): float(v) for k, v in (positions or {}).items() if v},
        metadata=dict(metadata or {}),
    )


def state_to_account(state: PortfolioState) -> dict:
    """qlib ``create_account_instance`` seed.

    Uses the documented ``{"cash": cash, <stock>: {"amount": shares}, ...}`` form. qlib only
    auto-wraps *int* scalar amounts, so floats must be pre-wrapped; the missing price is filled
    by ``Position.fill_stock_value`` from the close before the backtest start.
    """
    account: dict[str, object] = {"cash": float(state.cash)}
    for code, shares in state.positions.items():
        if shares and float(shares) > 0:
            account[code] = {"amount": float(shares)}
    return account
