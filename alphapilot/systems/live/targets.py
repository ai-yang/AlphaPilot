"""TargetPortfolio — the first-class hand-off from *decision* to *execution*.

The daily selection strategy decides a target book (which instruments to hold and
how many shares) and the timing strategy emits order intents; both are turned into
a broker-agnostic :class:`TargetPortfolio`, which the executor reconciles against
the **real** account. Decoupling "what to hold" from "how it filled in a
simulation" is exactly the interface change the plan calls for: the live executor
must diff against real positions from the OMS, never against a simulated roll.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class TargetPortfolio:
    """A desired end-of-run holding book.

    ``holdings`` maps instrument code (any accepted symbol form) -> target shares.
    ``prices`` are reference/limit prices per code (for limit orders & valuation).
    """

    date: str
    holdings: dict[str, float] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    cash: float | None = None
    source: str = ""
    market: str | None = None

    @classmethod
    def from_holdings(
        cls,
        date: str,
        records: Iterable[dict[str, Any]],
        *,
        source: str = "",
        market: str | None = None,
    ) -> "TargetPortfolio":
        """Build from ``[{instrument, amount, price}, ...]`` (e.g. daily_trade holdings)."""
        holdings: dict[str, float] = {}
        prices: dict[str, float] = {}
        for row in records:
            code = row.get("instrument") or row.get("code")
            if code is None:
                continue
            amount = float(row.get("amount", 0) or 0)
            if amount <= 0:
                continue
            holdings[str(code)] = amount
            px = row.get("price")
            if px is not None:
                try:
                    prices[str(code)] = float(px)
                except (TypeError, ValueError):
                    pass
        return cls(date=date, holdings=holdings, prices=prices, source=source, market=market)
