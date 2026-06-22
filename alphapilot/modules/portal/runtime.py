"""Runtime process helpers for the portal server."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def runtime_path() -> Path:
    override = os.getenv("ALPHAPILOT_PORTAL_RUNTIME_PATH")
    if override:
        return Path(override).expanduser()
    return Path("~/.alphapilot/portal/runtime.json").expanduser()


def current_restart_argv() -> list[str]:
    return [sys.executable, *sys.argv]


def write_runtime(*, host: str, port: int, argv: list[str] | None = None, mode: str = "portal") -> Path:
    path = runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "mode": mode,
        "argv": argv or current_restart_argv(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_runtime() -> dict[str, Any]:
    path = runtime_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - stale/corrupt runtime metadata should not crash callers
        return {}
    return value if isinstance(value, dict) else {}


def clear_runtime() -> None:
    try:
        runtime_path().unlink()
    except FileNotFoundError:
        pass


def pid_running(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except OSError:
        return False
    return True


def schedule_current_process_restart(delay: float = 0.75) -> dict[str, Any]:
    argv = current_restart_argv()

    def restart() -> None:
        time.sleep(delay)
        os.execv(sys.executable, argv)

    thread = threading.Thread(target=restart, name="portal-restart", daemon=True)
    thread.start()
    return {"pid": os.getpid(), "argv": argv, "delay": delay}


def install_restart_signal_handler() -> None:
    if not hasattr(signal, "SIGUSR1"):
        return

    def handle_restart(_signum: int, _frame: Any) -> None:
        schedule_current_process_restart(delay=0.25)

    signal.signal(signal.SIGUSR1, handle_restart)


def request_runtime_restart() -> dict[str, Any]:
    runtime = load_runtime()
    pid = runtime.get("pid")
    if not pid_running(pid):
        raise RuntimeError("No running portal process found. Start it with `alphapilot portal` first.")
    if not hasattr(signal, "SIGUSR1"):
        raise RuntimeError("Portal restart signal is not supported on this platform.")
    os.kill(int(pid), signal.SIGUSR1)
    return {
        "accepted": True,
        "pid": int(pid),
        "host": runtime.get("host"),
        "port": runtime.get("port"),
        "runtime_path": str(runtime_path()),
    }
