"""Portal-managed environment overrides.

Values are stored outside the repository so secrets edited from the portal do
not end up in the project ``.env`` file by default.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MASKED_SECRET = "********"


@dataclass(frozen=True)
class EnvField:
    key: str
    label: str
    group: str
    kind: str = "text"
    secret: bool = False
    help_text: str = ""
    requires_restart: bool = True


ENV_FIELDS: tuple[EnvField, ...] = (
    EnvField("OPENAI_BASE_URL", "OpenAI Base URL", "LLM", help_text="Compatible OpenAI endpoint."),
    EnvField("OPENAI_API_KEY", "OpenAI API Key", "LLM", kind="password", secret=True),
    EnvField("CHAT_MODEL", "Chat Model", "LLM"),
    EnvField("REASONING_MODEL", "Reasoning Model", "LLM"),
    EnvField("MAX_RETRY", "Max Retry", "LLM", kind="number"),
    EnvField("FACTOR_MINING_TIMEOUT", "Factor Mining Timeout", "LLM", kind="number", help_text="Seconds."),
    EnvField("TUSHARE_TOKEN", "Tushare Token", "Data", kind="password", secret=True),
    EnvField("ALPHAPILOT_QLIB_DATA_DIR", "Qlib Data Dir", "Data Paths"),
    EnvField("ALPHAPILOT_RAW_DATA_DIR", "Raw Data Dir", "Data Paths"),
    EnvField("ALPHAPILOT_ADJUST_FACTOR_DIR", "Adjust Factor Dir", "Data Paths"),
    EnvField("ALPHAPILOT_LOG_DIR", "Log Dir", "Paths"),
    EnvField("ALPHAPILOT_WORKSPACE_ROOT", "Workspace Root", "Paths"),
    EnvField("ALPHAPILOT_BACKTEST_ROOT", "Backtest Root", "Paths"),
    EnvField("ALPHAPILOT_FACTOR_ZOO_DIR", "Factor Zoo Dir", "Paths"),
    EnvField("ALPHAPILOT_STRATEGY_PARAM_DIR", "Strategy Param Dir", "Paths"),
    EnvField("QLIB_FACTOR_QLIB_TEMPLATE_DIR", "Qlib Template Dir", "Qlib / Backtest"),
    EnvField("QLIB_FACTOR_QLIB_CONFIG_NAME", "Qlib Config Name", "Qlib / Backtest"),
    EnvField("ALPHAPILOT_PICKLE_CACHE_ENABLED", "Pickle Cache Enabled", "Cache", kind="boolean"),
    EnvField("ALPHAPILOT_PICKLE_CACHE_DIR_MINE", "Mine Cache Dir", "Cache"),
    EnvField("ALPHAPILOT_PICKLE_CACHE_DIR_BACKTEST", "Backtest Cache Dir", "Cache"),
)

_FIELD_BY_KEY = {field.key: field for field in ENV_FIELDS}


def env_path() -> Path:
    override = os.getenv("ALPHAPILOT_PORTAL_ENV_PATH")
    if override:
        return Path(override).expanduser()
    return Path("~/.alphapilot/portal/env.json").expanduser()


def _env_file_values() -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except Exception:  # noqa: BLE001 - optional at runtime
        return {}
    path = Path(".env")
    if not path.exists():
        return {}
    values = dotenv_values(path)
    return {str(k): str(v) for k, v in values.items() if k and v is not None}


def _coerce_value(field: EnvField, value: Any) -> str:
    if field.kind == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return "true"
        if text in {"0", "false", "no", "off"}:
            return "false"
        raise ValueError(f"{field.key} must be a boolean")
    if field.kind == "number":
        text = str(value).strip()
        if not text:
            return ""
        try:
            int(text)
        except ValueError as exc:
            raise ValueError(f"{field.key} must be an integer") from exc
        return text
    return "" if value is None else str(value).strip()


def _read_raw() -> dict[str, str]:
    path = env_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - bad portal env should not block startup
        return {}
    if not isinstance(raw, dict):
        return {}
    values: dict[str, str] = {}
    for key, value in raw.items():
        field = _FIELD_BY_KEY.get(str(key))
        if not field:
            continue
        try:
            coerced = _coerce_value(field, value)
        except ValueError:
            continue
        if coerced:
            values[field.key] = coerced
    return values


def save_env_values(values: dict[str, Any]) -> Path:
    current = _read_raw()
    for key, value in values.items():
        field = _FIELD_BY_KEY.get(str(key))
        if not field:
            raise ValueError(f"Unsupported portal environment key: {key}")
        if field.secret and (value is None or str(value) in {"", MASKED_SECRET}):
            continue
        coerced = _coerce_value(field, value)
        if coerced:
            current[field.key] = coerced
        else:
            current.pop(field.key, None)
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _display_values(values: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in values.items():
        field = _FIELD_BY_KEY.get(key)
        if field and field.secret:
            out[key] = MASKED_SECRET
        else:
            out[key] = value
    return out


def apply_portal_env(target: dict[str, str] | None = None) -> dict[str, str]:
    """Apply portal env overrides without clobbering real process env values.

    ``.env`` is loaded before the portal in normal CLI use. To preserve the
    intended precedence (real environment > portal env > .env), keys whose
    current value came from ``.env`` may be replaced by portal values, while
    externally provided environment variables are left untouched.
    """
    env = os.environ if target is None else target
    saved = _read_raw()
    dotenv_values = _env_file_values()
    applied: dict[str, str] = {}
    for key, value in saved.items():
        current = env.get(key)
        if current is not None and dotenv_values.get(key) != current:
            continue
        env[key] = value
        applied[key] = value
    return applied


def portal_env_payload() -> dict[str, Any]:
    saved = _read_raw()
    current = {field.key: os.environ.get(field.key, "") for field in ENV_FIELDS if os.environ.get(field.key)}
    restart_required_keys = [
        key
        for key, value in saved.items()
        if os.environ.get(key) != value and (os.environ.get(key) is None or _env_file_values().get(key) == os.environ.get(key))
    ]
    return {
        "fields": [asdict(field) for field in ENV_FIELDS],
        "values": _display_values(saved),
        "current": _display_values(current),
        "config_path": env_path(),
        "restart_required": bool(restart_required_keys),
        "restart_required_keys": restart_required_keys,
        "masked_secret": MASKED_SECRET,
    }
