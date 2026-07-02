"""Concrete broker gateways (adapters for the :class:`BrokerGateway` port).

* :class:`PaperBroker` / :class:`SimBroker` — in-process simulators (no SDK), used
  for development and the whole test suite.
* ``VnpyBrokerAdapter`` (added later) — the only adapter that imports vn.py, and
  only when running in LIVE mode.
"""

from alphapilot.systems.live.brokers.paper import FillDecision, PaperBroker
from alphapilot.systems.live.brokers.sim import SimBroker

__all__ = ["FillDecision", "PaperBroker", "SimBroker"]
