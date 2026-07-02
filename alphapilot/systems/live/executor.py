"""Executor — turn a target book / order intents into concrete OrderRequests.

Reconciliation diffs the :class:`TargetPortfolio` against the **real** positions in
the OMS (not a simulated roll), respecting board lots and — for sells — the T+1
sellable quantity. The resulting requests are handed to the engine's guarded
:meth:`~alphapilot.systems.live.engine.LiveEngine.submit` (which applies risk), or
to an execution algo for timed placement (call auction / TWAP).
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from alphapilot.systems.live.targets import TargetPortfolio
from alphapilot.systems.live.types import OrderRequest, normalize_symbol, symbol_key


def _floor_lot(volume: float, lot: int) -> float:
    if lot and lot > 0:
        return float(math.floor(volume / lot) * lot)
    return float(math.floor(volume)) if volume > 0 else 0.0


def reconcile(target: TargetPortfolio, oms, *, lot_size: int = 100) -> list[OrderRequest]:
    """Diff target shares vs real OMS positions -> buy/sell requests (lot-rounded).

    Sells are capped at the sellable (T+1, non-frozen) quantity from the OMS.
    Instruments held but absent from the target are fully liquidated (target 0).
    """
    tgt: dict[str, float] = {}
    meta: dict[str, tuple[str, Any, float]] = {}
    for code, shares in target.holdings.items():
        c, ex = normalize_symbol(code)
        key = symbol_key(c, ex)
        tgt[key] = float(shares)
        meta[key] = (c, ex, float(target.prices.get(code, 0.0)))

    current = {p.key: p for p in oms.get_positions()}
    reqs: list[OrderRequest] = []
    for key in sorted(set(tgt) | set(current)):
        target_shares = tgt.get(key, 0.0)
        pos = current.get(key)
        cur = pos.volume if pos else 0.0
        delta = target_shares - cur
        if abs(delta) < max(lot_size, 1):
            continue
        if key in meta:
            code, exchange, price = meta[key]
        else:
            code, exchange, price = pos.code, pos.exchange, 0.0

        if delta > 0:
            vol = _floor_lot(delta, lot_size)
            if vol > 0:
                reqs.append(OrderRequest.buy(code, exchange, vol, price, reference=f"{target.date}:{key}:B"))
        else:
            sellable = oms.available_shares(key)
            vol = _floor_lot(min(abs(delta), sellable), lot_size)
            if vol > 0:
                reqs.append(OrderRequest.sell(code, exchange, vol, price, reference=f"{target.date}:{key}:S"))
    return reqs


def orders_from_intents(
    intents: Iterable[Any], oms, prices: dict[str, float], *, lot_size: int = 100
) -> list[OrderRequest]:
    """Translate timing :class:`OrderIntent` objects into concrete requests.

    Supports ``buy`` / ``sell`` / ``close`` (share quantities) and the
    ``target_percent`` / ``target_shares`` rebalancing actions (sized against the
    OMS equity / current holding).
    """
    reqs: list[OrderRequest] = []
    for intent in intents:
        code, exchange = normalize_symbol(intent.instrument)
        key = symbol_key(code, exchange)
        price = float(prices.get(intent.instrument) or prices.get(key) or 0.0)
        pos = oms.get_position(key)
        current = pos.volume if pos else 0.0
        action = intent.action

        if action == "buy" and intent.quantity:
            vol = _floor_lot(intent.quantity, lot_size)
            if vol > 0:
                reqs.append(OrderRequest.buy(code, exchange, vol, price))
        elif action == "sell" and intent.quantity:
            vol = _floor_lot(min(intent.quantity, oms.available_shares(key)), lot_size)
            if vol > 0:
                reqs.append(OrderRequest.sell(code, exchange, vol, price))
        elif action == "close":
            vol = _floor_lot(oms.available_shares(key), lot_size)
            if vol > 0:
                reqs.append(OrderRequest.sell(code, exchange, vol, price))
        elif action in ("target_percent", "target_shares"):
            target_shares = _target_shares(intent, oms, price, lot_size)
            delta = target_shares - current
            if delta >= lot_size:
                reqs.append(OrderRequest.buy(code, exchange, _floor_lot(delta, lot_size), price))
            elif -delta >= lot_size:
                vol = _floor_lot(min(-delta, oms.available_shares(key)), lot_size)
                if vol > 0:
                    reqs.append(OrderRequest.sell(code, exchange, vol, price))
    return reqs


def _target_shares(intent: Any, oms, price: float, lot_size: int) -> float:
    if intent.action == "target_shares" and intent.quantity is not None:
        return _floor_lot(intent.quantity, lot_size)
    pct = intent.target_percent or 0.0
    equity = oms.account.balance if (oms.account and oms.account.balance > 0) else oms.buying_power()
    if price <= 0 or equity <= 0:
        return 0.0
    return _floor_lot((pct * equity) / price, lot_size)
