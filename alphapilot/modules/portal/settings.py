"""Persistent settings for the React/FastAPI portal."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

DEFAULT_PORTAL_HOST = "127.0.0.1"
DEFAULT_PORTAL_PORT = 19901

_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def settings_path() -> Path:
    override = os.getenv("ALPHAPILOT_PORTAL_SETTINGS_PATH")
    if override:
        return Path(override).expanduser()
    return Path("~/.alphapilot/portal/settings.json").expanduser()


def _coerce_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def _coerce_host(value: Any) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError("host is required")
    if "/" in host or "\\" in host or not _HOST_RE.match(host):
        raise ValueError("host must be a host name or IP address")
    return host


def normalize_portal_settings(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": _coerce_host(payload.get("host", DEFAULT_PORTAL_HOST)),
        "port": _coerce_port(payload.get("port", DEFAULT_PORTAL_PORT)),
    }


def load_file_portal_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {"host": DEFAULT_PORTAL_HOST, "port": DEFAULT_PORTAL_PORT}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - bad config should not block startup
        raw = {}
    try:
        return normalize_portal_settings(raw if isinstance(raw, dict) else {})
    except ValueError:
        return {"host": DEFAULT_PORTAL_HOST, "port": DEFAULT_PORTAL_PORT}


def load_portal_settings(*, include_env: bool = True) -> dict[str, Any]:
    settings = load_file_portal_settings()
    if include_env:
        env_host = os.getenv("ALPHAPILOT_PORTAL_HOST")
        env_port = os.getenv("ALPHAPILOT_PORTAL_PORT")
        if env_host is not None:
            settings["host"] = _coerce_host(env_host)
        if env_port is not None:
            settings["port"] = _coerce_port(env_port)
    return settings


def save_portal_settings(payload: dict[str, Any]) -> Path:
    settings = normalize_portal_settings(payload)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
