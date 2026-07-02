"""Configuration for the live-trading subsystem.

Dependency-light dataclass + environment overrides, matching the style of
:mod:`alphapilot.kernel.config`. Read standalone via :meth:`LiveConfig.load` (the
live process reads it directly), and later surfaced on ``AppConfig.live`` for the
CLI / portal.

Security note: broker credentials are **never** stored here with defaults — they
are pulled from the environment (or a secret store) at connect time by the
gateway. This object only carries non-secret knobs: run mode, which broker,
risk limits, session/calendar and ledger location.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class RunMode:
    """Run-mode ladder (see :mod:`alphapilot.systems.live.fsm.runmode_fsm`)."""

    DRY_RUN = "dry_run"   # compute + print intents, submit nothing
    PAPER = "paper"       # route to the in-process PaperBroker
    LIVE = "live"         # route to a real broker gateway


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


@dataclass
class RiskLimits:
    """Pre-trade risk limits enforced by :mod:`alphapilot.systems.live.risk`.

    All monetary limits are in account currency (CNY). ``<= 0`` disables a limit.
    """

    #: Max notional of a single order.
    max_order_value: float = field(default_factory=lambda: _env_float("ALPHAPILOT_LIVE_MAX_ORDER_VALUE", 200_000.0))
    #: Max total notional traded in one day (buys + sells).
    max_daily_value: float = field(default_factory=lambda: _env_float("ALPHAPILOT_LIVE_MAX_DAILY_VALUE", 2_000_000.0))
    #: Max fraction of account equity in a single instrument (0..1).
    max_position_pct: float = field(default_factory=lambda: _env_float("ALPHAPILOT_LIVE_MAX_POSITION_PCT", 0.30))
    #: Reject a limit price deviating more than this fraction from the reference.
    price_guard_pct: float = field(default_factory=lambda: _env_float("ALPHAPILOT_LIVE_PRICE_GUARD_PCT", 0.05))
    #: Max number of orders accepted in one day (throttle / runaway guard).
    max_orders_per_day: int = field(default_factory=lambda: _env_int("ALPHAPILOT_LIVE_MAX_ORDERS_PER_DAY", 1000))
    #: Board-lot size (A-shares = 100; 0 disables lot rounding).
    lot_size: int = field(default_factory=lambda: _env_int("ALPHAPILOT_LIVE_LOT_SIZE", 100))


@dataclass
class LiveConfig:
    """Top-level live-trading config."""

    #: One of ``RunMode.{DRY_RUN,PAPER,LIVE}``.
    mode: str = field(default_factory=lambda: _env("ALPHAPILOT_LIVE_MODE", RunMode.DRY_RUN))
    #: Which broker gateway to use in LIVE mode (``emt`` / ``xtp`` / …).
    broker: str = field(default_factory=lambda: _env("ALPHAPILOT_LIVE_BROKER", "paper"))
    #: Append-only order/trade audit ledger location.
    ledger_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_LIVE_LEDGER_DIR", Path.cwd() / "git_ignore_folder" / "live_ledger"
        )
    )
    #: Rolling live portfolio / reconciliation state location.
    state_dir: Path = field(
        default_factory=lambda: _env_path(
            "ALPHAPILOT_LIVE_STATE_DIR", Path.cwd() / "git_ignore_folder" / "live_state"
        )
    )
    #: IANA timezone for the trading session clock.
    timezone: str = field(default_factory=lambda: _env("ALPHAPILOT_TIMEZONE", "Asia/Shanghai"))
    risk: RiskLimits = field(default_factory=RiskLimits)

    @classmethod
    def load(cls) -> "LiveConfig":
        return cls()

    def summary(self) -> str:
        return (
            "LiveConfig("
            f"mode={self.mode}, broker={self.broker}, timezone={self.timezone}, "
            f"ledger_dir={self.ledger_dir}, "
            f"risk=[max_order_value={self.risk.max_order_value}, "
            f"max_position_pct={self.risk.max_position_pct}, "
            f"price_guard_pct={self.risk.price_guard_pct}, lot_size={self.risk.lot_size}]"
            ")"
        )
