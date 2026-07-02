"""PositionBook — per-instrument holding state with A-share T+1 accounting.

Mirrors vn.py's ``converter.PositionHolding`` (yd / td / frozen split) but
long-only and A-share focused:

* ``volume``     total shares held;
* ``yd_volume``  the *sellable* (yesterday) portion — today's buys are **not**
  sellable until they roll over (T+1);
* ``frozen``     shares locked by *working sell orders*;
* ``available = yd_volume - frozen``  is what can be sold right now.

Positions are advanced by trades (fills change ``volume`` / ``yd_volume`` / cost)
and by orders (working sells change ``frozen``). A real broker's position snapshot
(:meth:`update_position`) can overwrite the authoritative totals for reconciliation.
"""

from __future__ import annotations

from alphapilot.systems.live.types import (
    Direction,
    Order,
    Position,
    Trade,
    normalize_symbol,
)


class PositionBook:
    """Authoritative long-only holdings with T+1 sellable accounting."""

    def __init__(self) -> None:
        self._holdings: dict[str, Position] = {}
        # active working sell orders, kept to recompute per-symbol frozen shares.
        self._active_sells: dict[str, Order] = {}

    # ---- access ---------------------------------------------------------- #
    def get(self, key: str) -> Position | None:
        return self._holdings.get(key)

    def all_positions(self) -> list[Position]:
        return [p for p in self._holdings.values() if p.volume > 0]

    def available(self, key: str) -> float:
        pos = self._holdings.get(key)
        return pos.available if pos else 0.0

    def _get_or_create(self, code: str, exchange) -> Position:
        key = f"{code}.{exchange.value}"
        pos = self._holdings.get(key)
        if pos is None:
            pos = Position(code=code, exchange=exchange, direction=Direction.LONG)
            self._holdings[key] = pos
        return pos

    # ---- broker snapshot (reconciliation) -------------------------------- #
    def update_position(self, position: Position) -> None:
        """Overwrite authoritative totals from a broker position snapshot.

        ``frozen`` is *recomputed* from working sells afterwards (the broker's own
        frozen is honoured only as a floor via ``max``)."""
        pos = self._get_or_create(position.code, position.exchange)
        pos.volume = position.volume
        pos.yd_volume = position.yd_volume
        pos.price = position.price or pos.price
        pos.pnl = position.pnl
        pos.gateway = position.gateway or pos.gateway
        self._recompute_frozen(pos.key)
        pos.frozen = max(pos.frozen, position.frozen)

    # ---- order-driven frozen accounting ---------------------------------- #
    def update_order(self, order: Order) -> None:
        """Track working *sell* orders and recompute frozen shares for the symbol."""
        if order.direction != Direction.SHORT:
            return  # buys freeze cash (account-level), not shares
        if order.is_active():
            self._active_sells[order.order_id] = order
        else:
            self._active_sells.pop(order.order_id, None)
        self._get_or_create(order.code, order.exchange)
        self._recompute_frozen(order.key)

    def _recompute_frozen(self, key: str) -> None:
        pos = self._holdings.get(key)
        if pos is None:
            return
        pos.frozen = sum(
            o.remaining for o in self._active_sells.values() if o.key == key and o.is_active()
        )

    # ---- trade-driven totals --------------------------------------------- #
    def update_trade(self, trade: Trade) -> None:
        pos = self._get_or_create(trade.code, trade.exchange)
        if trade.direction == Direction.LONG:      # buy
            new_vol = pos.volume + trade.volume
            if new_vol > 0:
                pos.price = (pos.price * pos.volume + trade.price * trade.volume) / new_vol
            pos.volume = new_vol
            # today's buy is NOT added to yd_volume (T+1): stays non-sellable today.
        else:                                       # sell
            pos.volume = max(pos.volume - trade.volume, 0.0)
            pos.yd_volume = max(pos.yd_volume - trade.volume, 0.0)
            if pos.volume <= 1e-9:
                pos.volume = 0.0
                pos.price = 0.0

    # ---- day roll -------------------------------------------------------- #
    def roll_new_day(self) -> None:
        """Start of a new trading day: today's buys become sellable (yd = volume),
        and stale working-sell frozen is cleared (orders don't survive the day)."""
        self._active_sells.clear()
        for pos in self._holdings.values():
            pos.yd_volume = pos.volume
            pos.frozen = 0.0

    def seed(self, code: str, volume: float, price: float = 0.0, *, sellable: bool = True) -> Position:
        """Test/opening helper: seed a holding (``sellable`` => counts as yesterday's)."""
        c, ex = normalize_symbol(code)
        pos = self._get_or_create(c, ex)
        pos.volume = float(volume)
        pos.yd_volume = float(volume) if sellable else 0.0
        pos.price = float(price)
        return pos
