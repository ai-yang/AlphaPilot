"""Broker abstractions for later live-trading adapters."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from alphapilot.systems.timing.base import ExecutionReport, OrderIntent, OrderStatus


@dataclass
class PaperBroker:
    """Minimal mock broker that records submitted intents as accepted reports."""

    cash: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    reports: list[ExecutionReport] = field(default_factory=list)

    def submit_order(self, intent: OrderIntent) -> ExecutionReport:
        report = ExecutionReport(
            order_id=uuid.uuid4().hex,
            status=OrderStatus.SUBMITTED,
            instrument=intent.instrument,
            datetime=intent.datetime,
            action=intent.action,
            message="paper broker accepted intent",
        )
        self.reports.append(report)
        return report

    def cancel_order(self, order_id: str) -> ExecutionReport:
        report = ExecutionReport(
            order_id=order_id,
            status=OrderStatus.CANCELLED,
            instrument="",
            datetime="",
            action="close",
            message="paper broker cancelled intent",
        )
        self.reports.append(report)
        return report

    def query_account(self) -> dict[str, Any]:
        return {"cash": self.cash}

    def query_positions(self) -> dict[str, float]:
        return dict(self.positions)
