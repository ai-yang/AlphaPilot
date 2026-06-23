"""Persistent settings for the React/FastAPI portal."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

DEFAULT_PORTAL_HOST = "127.0.0.1"
DEFAULT_PORTAL_PORT = 19901
DEFAULT_TIMEZONE = "Asia/Shanghai"

_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

# A short curated list surfaced in the portal UI; any valid IANA name is accepted.
COMMON_TIMEZONES = (
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Asia/Kolkata",
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
)


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


def _coerce_timezone(value: Any) -> str:
    """Validate an IANA timezone name (e.g. ``Asia/Shanghai``); empty -> default."""
    tz = str(value or "").strip() or DEFAULT_TIMEZONE
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001 - unknown zone / missing tzdata
        raise ValueError(f"unknown timezone: {tz}") from exc
    return tz


def normalize_portal_settings(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": _coerce_host(payload.get("host", DEFAULT_PORTAL_HOST)),
        "port": _coerce_port(payload.get("port", DEFAULT_PORTAL_PORT)),
        "timezone": _coerce_timezone(payload.get("timezone", DEFAULT_TIMEZONE)),
    }


def load_file_portal_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return normalize_portal_settings({})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - bad config should not block startup
        raw = {}
    try:
        return normalize_portal_settings(raw if isinstance(raw, dict) else {})
    except ValueError:
        return normalize_portal_settings({})


def load_portal_settings(*, include_env: bool = True) -> dict[str, Any]:
    settings = load_file_portal_settings()
    if include_env:
        env_host = os.getenv("ALPHAPILOT_PORTAL_HOST")
        env_port = os.getenv("ALPHAPILOT_PORTAL_PORT")
        env_tz = os.getenv("ALPHAPILOT_TIMEZONE")
        if env_host is not None:
            settings["host"] = _coerce_host(env_host)
        if env_port is not None:
            settings["port"] = _coerce_port(env_port)
        if env_tz:
            try:
                settings["timezone"] = _coerce_timezone(env_tz)
            except ValueError:
                pass
    return settings


def save_portal_settings(payload: dict[str, Any]) -> Path:
    # Merge over existing settings so partial saves (e.g. only host/port, or only
    # timezone from the CLI) never reset the other fields.
    merged = {**load_file_portal_settings(), **{k: v for k, v in payload.items() if v is not None}}
    settings = normalize_portal_settings(merged)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def resolve_timezone() -> str:
    """Effective timezone: ``ALPHAPILOT_TIMEZONE`` env > settings.json > default."""
    return load_portal_settings(include_env=True)["timezone"]


def apply_timezone() -> str:
    """Set the process timezone (``TZ`` + ``tzset``) so ``datetime.now()`` and child
    processes use the configured zone. Returns the applied zone."""
    tz = resolve_timezone()
    os.environ["TZ"] = tz
    try:
        import time

        time.tzset()
    except AttributeError:  # non-POSIX (e.g. Windows) has no tzset
        pass
    return tz


def set_timezone(timezone: str) -> Path:
    """Validate and persist the timezone (keeps host/port). Returns the settings path."""
    return save_portal_settings({"timezone": _coerce_timezone(timezone)})
