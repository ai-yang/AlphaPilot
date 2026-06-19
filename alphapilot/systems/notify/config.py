"""Notify config + credentials.

Credentials live in a file outside the repo (``~/.alphapilot/credentials/notify.json``,
borrowed from openclaw's dedicated credentials dir) so they are never committed,
and any ``ALPHAPILOT_NOTIFY_*`` environment variable overrides the file at load
time (handy for servers). The :data:`CHANNEL_FIELDS` spec drives both the env
override mapping and the portal config form, so there is one source of truth.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# field name -> type; types: bool | str | secret | int | list
CHANNEL_FIELDS: dict[str, list[tuple[str, str]]] = {
    "telegram": [
        ("enabled", "bool"),
        ("bot_token", "secret"),
        ("chat_id", "str"),
    ],
    "feishu": [
        ("enabled", "bool"),
        ("webhook", "str"),
        ("secret", "secret"),
    ],
    "email": [
        ("enabled", "bool"),
        ("host", "str"),
        ("port", "int"),
        ("use_ssl", "bool"),
        ("username", "str"),
        ("password", "secret"),
        ("sender", "str"),
        ("recipients", "list"),
    ],
}

SECRET_FIELD_TYPES = {"secret"}

_DEFAULTS: dict[str, dict[str, Any]] = {
    "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    "feishu": {"enabled": False, "webhook": "", "secret": ""},
    "email": {
        "enabled": False,
        "host": "",
        "port": 465,
        "use_ssl": True,
        "username": "",
        "password": "",
        "sender": "",
        "recipients": [],
    },
}


def credentials_path() -> Path:
    override = os.getenv("ALPHAPILOT_NOTIFY_CREDENTIALS_PATH")
    if override:
        return Path(override).expanduser()
    return Path("~/.alphapilot/credentials/notify.json").expanduser()


def _coerce(value: Any, ftype: str) -> Any:
    if ftype == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if ftype == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if ftype == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return "" if value is None else str(value)


def load_file_config() -> dict[str, Any]:
    """Read the credentials file only (no env overlay). Used by the editor UI."""
    cfg = {ch: dict(defaults) for ch, defaults in _DEFAULTS.items()}
    cfg["options"] = {"notify_on_all_jobs": False}
    path = credentials_path()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt file shouldn't crash callers
            stored = {}
        for channel, fields in CHANNEL_FIELDS.items():
            saved = stored.get(channel, {})
            for name, ftype in fields:
                if name in saved:
                    cfg[channel][name] = _coerce(saved[name], ftype)
        if isinstance(stored.get("options"), dict):
            cfg["options"].update(stored["options"])
    return cfg


def _env_key(channel: str, field: str) -> str:
    return f"ALPHAPILOT_NOTIFY_{channel.upper()}_{field.upper()}"


def load_notify_config() -> dict[str, Any]:
    """File config with ``ALPHAPILOT_NOTIFY_*`` env vars overlaid (env wins)."""
    cfg = load_file_config()
    for channel, fields in CHANNEL_FIELDS.items():
        for name, ftype in fields:
            env_val = os.getenv(_env_key(channel, name))
            if env_val is not None:
                cfg[channel][name] = _coerce(env_val, ftype)
    on_all = os.getenv("ALPHAPILOT_NOTIFY_ON_ALL_JOBS")
    if on_all is not None:
        cfg["options"]["notify_on_all_jobs"] = _coerce(on_all, "bool")
    return cfg


def save_notify_config(cfg: dict[str, Any]) -> Path:
    """Persist channel settings to the credentials file (0600, dir 0700)."""
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    payload: dict[str, Any] = {}
    for channel, fields in CHANNEL_FIELDS.items():
        section = cfg.get(channel, {})
        payload[channel] = {name: _coerce(section.get(name), ftype) for name, ftype in fields}
    payload["options"] = {
        "notify_on_all_jobs": bool(cfg.get("options", {}).get("notify_on_all_jobs", False))
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def notify_on_all_jobs() -> bool:
    return bool(load_notify_config().get("options", {}).get("notify_on_all_jobs", False))
