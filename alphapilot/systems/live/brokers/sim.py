"""SimBroker — PaperBroker with configurable adverse behaviors for tests.

Adds the messy realities a deterministic full-fill broker glosses over:
* **rejects** for a configured set of codes (e.g. suspended / risk-flagged);
* **partial fills** (fill only a fraction, leaving the remainder working so a
  later cancel exercises the CANCELLED path);
* **price map** overrides for market-order fill prices.

Everything else (account/position/T+1 accounting, callbacks) is inherited.
"""

from __future__ import annotations

from alphapilot.systems.live.brokers.paper import FillDecision, PaperBroker
from alphapilot.systems.live.types import OrderRequest


class SimBroker(PaperBroker):
    """Paper broker whose fill policy can be tuned to reject / partially fill."""

    name = "sim"

    def __init__(
        self,
        *args,
        reject_codes: set[str] | None = None,
        partial_ratio: float = 1.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.reject_codes = set(reject_codes or set())
        self.partial_ratio = max(0.0, min(1.0, partial_ratio))

    def _decide(self, req: OrderRequest) -> FillDecision:
        if req.code in self.reject_codes:
            return FillDecision(0.0, 0.0, reject=True, reason=f"code {req.code} rejected by sim")
        price = self._fill_price(req)
        if self.partial_ratio >= 1.0:
            return FillDecision(req.volume, price)
        # Fill a whole-lot fraction, leaving the remainder working.
        filled = int(req.volume * self.partial_ratio)
        return FillDecision(float(filled), price)
