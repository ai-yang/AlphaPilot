"""Isolated FastAPI server used only by Portal Playwright interaction tests."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
RUN_ID = os.getenv("ALPHAPILOT_PORTAL_INTERACTION_RUN_ID") or time.strftime("%Y%m%d_%H%M%S")
QA_ROOT = Path(
    os.getenv(
        "ALPHAPILOT_PORTAL_QA_ROOT",
        REPO_ROOT / "git_ignore_folder" / "qa" / "portal_interaction" / RUN_ID,
    )
).resolve()


def configure_environment() -> None:
    if os.getenv("ALPHAPILOT_GENERATE_DOC_SCREENSHOTS") == "1":
        # The documentation fixture uses a fixed, non-user-specific /tmp path
        # so screenshots stay reproducible and never expose a developer home.
        shutil.rmtree(QA_ROOT, ignore_errors=True)
    paths = {
        "ALPHAPILOT_IMPORTANT_DATA_DIR": QA_ROOT / "important_data",
        "ALPHAPILOT_FACTOR_ZOO_DIR": QA_ROOT / "factor_zoo",
        "ALPHAPILOT_STRATEGY_PARAM_DIR": QA_ROOT / "strategy_zoo",
        "ALPHAPILOT_RAW_DATA_DIR": QA_ROOT / "raw",
        "ALPHAPILOT_ADJUST_FACTOR_DIR": QA_ROOT / "adjust_factors",
        "ALPHAPILOT_FACTOR_H5_CACHE_ROOT": QA_ROOT / "factor_cache",
        "ALPHAPILOT_LOG_DIR": QA_ROOT / "logs",
        "ALPHAPILOT_WORKSPACE_ROOT": QA_ROOT / "workspaces",
        "ALPHAPILOT_RUNS_DIR": QA_ROOT / "runs",
        "ALPHAPILOT_PORTAL_JOB_ROOT": QA_ROOT / "jobs",
        "ALPHAPILOT_PORTAL_SCHEDULE_ROOT": QA_ROOT / "schedules",
        "ALPHAPILOT_TRADE_SESSIONS_DIR": QA_ROOT / "trade_sessions",
        "ALPHAPILOT_NOTIFY_COMMAND_ROOT": QA_ROOT / "notify_commands",
        "ALPHAPILOT_LIVE_LEDGER_DIR": QA_ROOT / "live_ledger",
        "ALPHAPILOT_LIVE_STATE_DIR": QA_ROOT / "live_state",
        "ALPHAPILOT_LIVE_MARKET_DATA_DIR": QA_ROOT / "live_market",
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(
        {
            "ALPHAPILOT_PORTAL_ENV_PATH": str(QA_ROOT / "portal_env.json"),
            "ALPHAPILOT_PORTAL_RUNTIME_PATH": str(QA_ROOT / "portal_runtime.json"),
            "ALPHAPILOT_PORTAL_SETTINGS_PATH": str(QA_ROOT / "portal_settings.json"),
            "ALPHAPILOT_NOTIFY_CREDENTIALS_PATH": str(QA_ROOT / "notify.json"),
            "ALPHAPILOT_LIVE_MODE": "paper",
            "ALPHAPILOT_LIVE_BROKER": "paper",
            # Browser interaction tests exercise only the isolated PAPER
            # workflow. Operator authentication has dedicated API/unit
            # coverage; disabling it here avoids injecting a plaintext token
            # into Playwright traces, videos, or documentation screenshots.
            "ALPHAPILOT_OPERATOR_AUTH_REQUIRED": "false",
            "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false",
            "ALPHAPILOT_RESEARCH_AUTOSTART": "0",
            "ALPHAPILOT_TIMEZONE": "Asia/Shanghai",
            "USE_LOCAL": "True",
        }
    )
    if os.getenv("ALPHAPILOT_RUN_REAL_LLM") == "1":
        source = Path(os.getenv("ALPHAPILOT_QA_QLIB_SOURCE", REPO_ROOT / "git_ignore_folder" / "qa" / "full_20260710" / "qlib"))
        os.environ["ALPHAPILOT_QLIB_DATA_DIR"] = str(source)
    else:
        qlib = QA_ROOT / "qlib"
        qlib.mkdir(exist_ok=True)
        os.environ["ALPHAPILOT_QLIB_DATA_DIR"] = str(qlib)

    stock_dir = paths["ALPHAPILOT_IMPORTANT_DATA_DIR"] / "stock_lists"
    stock_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "important_data" / "stock_lists" / "test_stock_pool_30.csv", stock_dir / "test_stock_pool_30.csv")


def seed_backtest() -> None:
    import pandas as pd

    workspace = Path(os.environ["ALPHAPILOT_WORKSPACE_ROOT"]) / "browser-demo"
    workspace.mkdir(parents=True, exist_ok=True)
    index = pd.date_range("2026-01-05", periods=4, freq="B")
    pd.DataFrame(
        {
            "return": [0.01, -0.002, 0.004, 0.003],
            "bench": [0.003, -0.001, 0.002, 0.001],
            "cost": [0.0002, 0.0001, 0.0001, 0.0001],
            "turnover": [0.2, 0.1, 0.12, 0.08],
            "account": [10100.0, 10079.8, 10119.1, 10148.4],
            "value": [5000.0, 4900.0, 5100.0, 5050.0],
            "cash": [5100.0, 5179.8, 5019.1, 5098.4],
        },
        index=index,
    ).to_pickle(workspace / "ret.pkl")


def main() -> None:
    configure_environment()
    seed_backtest()
    import uvicorn
    from alphapilot.modules.portal.api import create_app

    static_dir = REPO_ROOT / "alphapilot" / "modules" / "portal" / "web" / "dist"
    app = create_app(static_dir=static_dir)
    from alphapilot.modules.portal.api import _engine
    from alphapilot.research.auth import AuthService
    from alphapilot.research.catalog import Catalog
    from alphapilot.research.common import SCOPES, atomic_json
    from alphapilot.research.migration import migrate
    from alphapilot.research.store import Store
    engine = _engine(app)
    # Bootstrap the disposable PAPER journal before concurrent page queries.
    # The legacy live fixture initializes its SQLite schema lazily.
    engine.get_module("live").live_risk_status(mode="paper", broker="paper", trade_broker="paper", quote_provider="paper")
    store = Store()
    migrate(store, engine, execute=True)
    dataset = Catalog(engine).dataset("baostock_cn:day:backward")
    provider = Path(dataset["qlib_dir"])
    if os.getenv("ALPHAPILOT_RUN_REAL_LLM") != "1":
        for name in ("features", "calendars", "instruments"):
            (provider / name).mkdir(parents=True, exist_ok=True)
        (provider / "calendars/day.txt").write_text("2026-01-05\n2026-01-06\n")
        (provider / "instruments/all.txt").write_text("SH600000\t2026-01-05\t2026-01-06\n")
        atomic_json(provider / ".research-revision.json", {"source": dataset["source"], "adjust_mode": dataset["adjust_mode"]})
    credentials = {name: AuthService(store).create("browser-test-" + name, sorted(SCOPES))["token"]
                   for name in ("gui", "external")}
    # This endpoint exists only in the isolated test server. It issues access
    # to disposable fixtures, never to the developer's research workspace.
    app.add_api_route("/__test__/credentials", lambda: credentials, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())
    try:
        uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("ALPHAPILOT_PLAYWRIGHT_PORT", "19911")), log_level="warning")
    finally:
        try:
            from alphapilot.systems.live.config import LiveConfig
            from alphapilot.systems.live.daemon import stop_daemon

            stop_daemon(LiveConfig.load(), timeout=2)
        except Exception:
            pass


if __name__ == "__main__":
    main()
