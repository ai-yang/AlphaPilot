"""Reusable, broker-agnostic live-trading subsystem.

Public surface is the normalized domain (:mod:`.types`), the broker port
(:mod:`.gateway`) and the config (:mod:`.config`). Concrete brokers, OMS, FSMs,
risk gate and executor live in submodules and are imported on demand so that
``import alphapilot.systems.live`` stays light and free of vn.py / broker SDKs.
"""

from alphapilot.systems.live.config import LiveConfig, RiskLimits, RunMode
from alphapilot.systems.live.gateway import BrokerGateway, GatewayCallback
from alphapilot.systems.live.types import (
    ACTIVE_STATUSES,
    Account,
    CancelRequest,
    Contract,
    Direction,
    Exchange,
    Offset,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Product,
    TickData,
    Trade,
    infer_exchange,
    is_active,
    normalize_symbol,
    symbol_key,
)

__all__ = [
    "ACTIVE_STATUSES",
    "Account",
    "BrokerGateway",
    "CancelRequest",
    "Contract",
    "Direction",
    "Exchange",
    "GatewayCallback",
    "LiveConfig",
    "Offset",
    "Order",
    "OrderRequest",
    "OrderStatus",
    "OrderType",
    "Position",
    "Product",
    "RiskLimits",
    "RunMode",
    "TickData",
    "Trade",
    "infer_exchange",
    "is_active",
    "normalize_symbol",
    "symbol_key",
]
