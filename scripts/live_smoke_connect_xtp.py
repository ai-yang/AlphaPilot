"""Gated XTP real-connect smoke — run inside the live image against the XTP
公网测试环境 (simulation servers). Query-only by default; pass --order to also
place + cancel one tiny far-from-market limit order.

Usage (credentials via env, never files):

    docker compose --profile live run --rm \
      -e ALPHAPILOT_LIVE_XTP_ACCOUNT=... \
      -e ALPHAPILOT_LIVE_XTP_PASSWORD=... \
      -e ALPHAPILOT_LIVE_XTP_CLIENT_ID=1 \
      -e ALPHAPILOT_LIVE_XTP_SOFTWARE_KEY=... \
      -e ALPHAPILOT_LIVE_XTP_QUOTE_HOST=... -e ALPHAPILOT_LIVE_XTP_QUOTE_PORT=... \
      -e ALPHAPILOT_LIVE_XTP_TRADE_HOST=... -e ALPHAPILOT_LIVE_XTP_TRADE_PORT=... \
      live python scripts/live_smoke_connect_xtp.py [--order] [--symbol 600000]

Checks: TD+MD login, account/positions arrive, contracts load, one tick after
subscribing; with --order: submit a limit buy ~10% below last price (1 lot),
wait for the ack, cancel it, and verify the cancel.
"""

from __future__ import annotations

import argparse
import sys
import time

from alphapilot.systems.live.brokers.registry import (
    build_connect_setting,
    missing_setting_fields,
)
from alphapilot.systems.live.brokers.vnpy_adapter import VnpyBrokerAdapter
from alphapilot.systems.live.oms import OMS
from alphapilot.systems.live.types import Exchange, OrderRequest, OrderType


def wait_for(predicate, timeout: float, what: str) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            print(f"  [ok] {what}")
            return True
        time.sleep(0.5)
    print(f"  [TIMEOUT] {what}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", action="store_true", help="also place+cancel a tiny far-off limit order")
    parser.add_argument("--symbol", default="600000", help="test symbol (SSE code)")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    missing = missing_setting_fields("xtp")
    if missing:
        print("Missing XTP credentials in env:")
        for name in missing:
            print(f"  {name}")
        return 2

    setting = build_connect_setting("xtp")
    print(f"Connecting XTP (trade {setting['交易地址']}:{setting['交易端口']}, "
          f"quote {setting['行情地址']}:{setting['行情端口']}) ...")

    adapter = VnpyBrokerAdapter("XTP")
    oms = OMS()
    adapter.register_callback(oms)
    adapter.connect(setting)

    ok = True
    ok &= wait_for(lambda: oms.account is not None, args.timeout, "account snapshot received")
    ok &= wait_for(lambda: len(oms.contracts) > 0, args.timeout, "contracts received")
    if oms.account:
        print(f"  buying_power={oms.account.available:.2f} balance={oms.account.balance:.2f}")
    print(f"  positions={len(oms.get_positions())} contracts={len(oms.contracts)}")

    adapter.subscribe([args.symbol])
    key = f"{args.symbol}.SSE"
    ok &= wait_for(lambda: oms.get_tick(key) is not None, args.timeout, f"tick for {args.symbol}")
    tick = oms.get_tick(key)
    if tick:
        print(f"  last_price={tick.last_price} bid1={tick.bid_price_1} ask1={tick.ask_price_1}")

    if args.order:
        if tick is None or tick.last_price <= 0:
            print("  [skip] no tick -> not placing an order")
        else:
            price = round(tick.last_price * 0.9, 2)   # far below market: won't fill
            req = OrderRequest.buy(args.symbol, Exchange.SSE, 100, price, type=OrderType.LIMIT,
                                   reference="smoke")
            print(f"Placing 1-lot limit buy {args.symbol} @ {price} (far off market) ...")
            order_id = adapter.send_order(req)
            ok &= wait_for(lambda: oms.get_order(order_id) is not None, args.timeout, "order ack")
            order = oms.get_order(order_id)
            if order and order.is_active():
                adapter.cancel_order(order.create_cancel())
                ok &= wait_for(
                    lambda: not oms.get_order(order_id).is_active(), args.timeout, "cancel confirmed"
                )

    adapter.close()
    print("XTP CONNECT SMOKE:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
