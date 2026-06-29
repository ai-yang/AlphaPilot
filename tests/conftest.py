"""Shared pytest fixtures and helpers for the AlphaPilot test suite.

Provides:
* ``isolated_env`` — point every ``ALPHAPILOT_*`` path at ``tmp_path`` so a test
  never touches the developer's real factor zoo / qlib data / portal state.
* ``engine`` — a real ``build_engine()`` instance on top of the isolated env.
* credential helpers (``require_tushare`` / ``require_openai`` / ``require_notify``)
  that *skip* (not fail) when the relevant secret is absent.
* ``captured_notify`` — replace the notify fan-out with an in-memory capturing
  channel so dispatch logic can be asserted without sending anything externally.

Real tokens (TUSHARE_TOKEN / OPENAI_API_KEY / ...) come from the repo ``.env``,
which we load once at import so the marker-gated tiers can find them. Secrets are
never printed or asserted on — only their presence is checked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Load the repo .env (if present) so the marker-gated tiers can discover real
# credentials. Existing environment variables win (override=False).
try:  # pragma: no cover - best effort, never break collection
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except Exception:  # noqa: BLE001
    pass


# Regression snapshot of the CLI command surface contributed by built-in
# modules. Kept here so both the registry test and the real-CLI smoke test can
# share a single source of truth.
EXPECTED_CLI_COMMANDS: frozenset[str] = frozenset(
    {
        "backtest",
        "backtest_ui",
        "backtest_viz",
        "category_create",
        "category_delete",
        "category_list",
        "category_rename",
        "clean_logs",
        "daily_signals",
        "daily_state",
        "data_viz",
        "delete_mine_log",
        "delete_run",
        "delete_stock",
        "factor_add",
        "factor_categorize",
        "factor_category_add",
        "factor_category_remove",
        "factor_duplicates",
        "factor_list",
        "factor_rename",
        "factor_validate",
        "list_mine_logs",
        "list_runs",
        "list_stocks",
        "mine",
        "mine_aff",
        "mine_gp",
        "mine_rl",
        "modules",
        "notify_commands",
        "pool_add",
        "pool_create",
        "pool_delete",
        "pool_export",
        "pool_list",
        "pool_remove",
        "pool_rename",
        "pool_save",
        "pool_set_description",
        "pool_show",
        "portal",
        "portal_restart",
        "prepare_data",
        "qlib_yaml_generate",
        "qlib_yaml_validate",
        "refresh_stock",
        "scheduler",
        "strategy_backtest",
        "strategy_backtest_list",
        "strategy_create",
        "timezone",
        "trade_session_cash",
        "trade_session_create",
        "trade_session_delete",
        "trade_session_history",
        "trade_session_list",
        "trade_session_show",
        "trim_stock",
        "ui",
    }
)

EXPECTED_SYSTEMS: frozenset[str] = frozenset(
    {"data", "factor", "strategy", "backtest", "notify"}
)
EXPECTED_MODULES: frozenset[str] = frozenset(
    {
        "alpha_mining",
        "alphaforge_aff",
        "alphaforge_search",
        "backtest_viz",
        "daily_trade",
        "data_viz",
        "factor",
        "platform",
        "portal",
        "qlib_yaml",
        "stock_pool",
        "strategy_backtest",
    }
)


# --------------------------------------------------------------------------- #
# Credential detection (skip, don't fail, when secrets are missing)
# --------------------------------------------------------------------------- #
def has_tushare() -> bool:
    return bool(os.getenv("TUSHARE_TOKEN"))


def has_openai() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def require_tushare() -> str:
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        pytest.skip("TUSHARE_TOKEN not set; skipping real-data test")
    return token


def require_openai() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not set; skipping real-LLM test")
    return key


def require_notify(channel: str) -> dict[str, Any]:
    """Skip unless *channel* is configured (credentials file or env overlay)."""
    from alphapilot.systems.notify.channels import CHANNEL_CLASSES
    from alphapilot.systems.notify.config import load_notify_config

    cfg = load_notify_config()
    cls = CHANNEL_CLASSES.get(channel)
    if cls is None:
        pytest.skip(f"unknown notify channel {channel!r}")
    if not cls(cfg.get(channel, {})).is_configured():
        pytest.skip(f"notify channel {channel!r} not configured; skipping real send")
    return cfg.get(channel, {})


# --------------------------------------------------------------------------- #
# Isolated environment + engine
# --------------------------------------------------------------------------- #
@dataclass
class AlphaEnv:
    """Resolved paths for an isolated AlphaPilot test environment."""

    root: Path
    important: Path
    factor_zoo: Path
    strategy_zoo: Path
    raw_data: Path
    qlib_dir: Path
    factor_dir: Path
    log_dir: Path
    workspace_root: Path
    runs_dir: Path
    portal_job_root: Path
    portal_schedule_root: Path
    trade_sessions: Path
    notify_credentials: Path
    notify_command_root: Path
    env: dict[str, str] = field(default_factory=dict)


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AlphaEnv:
    """Redirect all AlphaPilot state under ``tmp_path`` for the duration of a test."""
    important = tmp_path / "important_data"
    factor_zoo = important / "factor_zoo"
    strategy_zoo = important / "strategy_zoo"
    raw_data = tmp_path / "raw_data_back_adjust"
    qlib_dir = tmp_path / "qlib"
    factor_dir = tmp_path / "adjust_factors"
    log_dir = tmp_path / "log"
    workspace_root = tmp_path / "workspaces"
    runs_dir = tmp_path / "runs"
    portal_job_root = tmp_path / "portal_jobs"
    portal_schedule_root = tmp_path / "portal_schedules"
    trade_sessions = tmp_path / "trade_sessions"
    notify_credentials = tmp_path / "notify.json"
    notify_command_root = tmp_path / "notify_commands"

    for path in (
        important,
        factor_zoo,
        strategy_zoo,
        raw_data,
        qlib_dir,
        factor_dir,
        log_dir,
        workspace_root,
        runs_dir,
        portal_job_root,
        portal_schedule_root,
        trade_sessions,
        notify_command_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    env = {
        "ALPHAPILOT_IMPORTANT_DATA_DIR": str(important),
        "ALPHAPILOT_FACTOR_ZOO_DIR": str(factor_zoo),
        "ALPHAPILOT_STRATEGY_PARAM_DIR": str(strategy_zoo),
        "ALPHAPILOT_RAW_DATA_DIR": str(raw_data),
        "ALPHAPILOT_QLIB_DATA_DIR": str(qlib_dir),
        "ALPHAPILOT_ADJUST_FACTOR_DIR": str(factor_dir),
        "ALPHAPILOT_LOG_DIR": str(log_dir),
        "ALPHAPILOT_WORKSPACE_ROOT": str(workspace_root),
        "ALPHAPILOT_RUNS_DIR": str(runs_dir),
        "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false",
        "ALPHAPILOT_PORTAL_JOB_ROOT": str(portal_job_root),
        "ALPHAPILOT_PORTAL_SCHEDULE_ROOT": str(portal_schedule_root),
        "ALPHAPILOT_TRADE_SESSIONS_DIR": str(trade_sessions),
        "ALPHAPILOT_PORTAL_ENV_PATH": str(tmp_path / "portal_env.json"),
        "ALPHAPILOT_PORTAL_RUNTIME_PATH": str(tmp_path / "portal_runtime.json"),
        "ALPHAPILOT_PORTAL_SETTINGS_PATH": str(tmp_path / "portal_settings.json"),
        "ALPHAPILOT_NOTIFY_CREDENTIALS_PATH": str(notify_credentials),
        "ALPHAPILOT_NOTIFY_COMMAND_ROOT": str(notify_command_root),
        "ALPHAPILOT_TIMEZONE": "Asia/Shanghai",
        "USE_LOCAL": "True",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    return AlphaEnv(
        root=tmp_path,
        important=important,
        factor_zoo=factor_zoo,
        strategy_zoo=strategy_zoo,
        raw_data=raw_data,
        qlib_dir=qlib_dir,
        factor_dir=factor_dir,
        log_dir=log_dir,
        workspace_root=workspace_root,
        runs_dir=runs_dir,
        portal_job_root=portal_job_root,
        portal_schedule_root=portal_schedule_root,
        trade_sessions=trade_sessions,
        notify_credentials=notify_credentials,
        notify_command_root=notify_command_root,
        env=env,
    )


@pytest.fixture()
def engine(isolated_env: AlphaEnv):
    """A fully-loaded engine bound to the isolated environment."""
    from alphapilot.kernel import build_engine

    eng = build_engine()
    try:
        yield eng
    finally:
        try:
            eng.shutdown()
        except Exception:  # noqa: BLE001 - shutdown is best-effort in tests
            pass


# --------------------------------------------------------------------------- #
# Capturing notify channel (offline assertions on rendered messages)
# --------------------------------------------------------------------------- #
class CapturingChannel:
    """A configured channel that records messages instead of sending them."""

    name = "capture"

    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    def is_configured(self) -> bool:
        return True

    def send(self, message: Any) -> None:
        self._sink.append(message)


@pytest.fixture()
def captured_notify(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Patch the notify fan-out to capture messages in-process.

    Returns the list that accumulates every ``Message`` handed to ``send``.
    """
    sink: list[Any] = []

    def _fake_build_channels(cfg: Any = None) -> list[Any]:
        return [CapturingChannel(sink)]

    monkeypatch.setattr(
        "alphapilot.systems.notify.service._build_channels", _fake_build_channels
    )
    return sink
