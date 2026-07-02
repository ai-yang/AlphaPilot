"""Live-image smoke: gateways import + MainEngine wiring + adapter load. No server connection.

Run inside the live image (Dockerfile.live). Exits non-zero if any required
piece fails, so it can gate the docker build. Which gateways are required is
controlled by LIVE_SMOKE_REQUIRE (comma list, default "xtp,emt").
"""

from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    require = {
        name.strip().lower()
        for name in os.getenv("LIVE_SMOKE_REQUIRE", "xtp,emt").split(",")
        if name.strip()
    }
    results: dict[str, str] = {}
    failed = False

    from vnpy.event import EventEngine
    from vnpy.trader.engine import MainEngine

    gateway_classes = []

    if "xtp" in require:
        try:
            from vnpy_xtp import XtpGateway

            gateway_classes.append(XtpGateway)
            results["import vnpy_xtp"] = "OK"
        except Exception:
            results["import vnpy_xtp"] = "FAIL\n" + traceback.format_exc()
            failed = True

    if "emt" in require:
        try:
            from vnpy_emt import EmtGateway

            gateway_classes.append(EmtGateway)
            results["import vnpy_emt"] = "OK"
        except Exception:
            results["import vnpy_emt"] = "FAIL\n" + traceback.format_exc()
            failed = True

    # Wire the gateways into a real MainEngine (constructs the C++ API wrapper
    # objects — proves the compiled bindings load and link at runtime).
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    for gateway_class in gateway_classes:
        try:
            main_engine.add_gateway(gateway_class)
            results[f"add_gateway {gateway_class.__name__}"] = "OK"
        except Exception:
            results[f"add_gateway {gateway_class.__name__}"] = "FAIL\n" + traceback.format_exc()
            failed = True

    # AlphaPilot's broker port + adapter import (no vnpy connect).
    try:
        from alphapilot.systems.live.brokers.vnpy_adapter import VnpyBrokerAdapter  # noqa: F401

        results["import alphapilot adapter"] = "OK"
    except Exception:
        results["import alphapilot adapter"] = "FAIL\n" + traceback.format_exc()
        failed = True

    try:
        main_engine.close()
    except Exception:  # noqa: BLE001 - shutdown is best-effort in the smoke
        pass

    print("=" * 60)
    for key, value in results.items():
        print(f"{key}: {value}")
    print("=" * 60)
    print("SMOKE", "FAILED" if failed else "PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
