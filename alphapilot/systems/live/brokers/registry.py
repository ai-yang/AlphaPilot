"""Broker registry — the one place that knows every supported broker.

Adding a broker later = install its vn.py gateway package + add one
:class:`BrokerSpec` entry here (or call :func:`register_broker` from a plugin).
Nothing above this file changes: the adapter resolves the gateway class and the
connect settings through the registry.

Connect settings are built from environment variables — credentials never live
in code or config files. For broker ``xtp`` the variables are::

    ALPHAPILOT_LIVE_XTP_ACCOUNT / _PASSWORD / _CLIENT_ID / _SOFTWARE_KEY
    ALPHAPILOT_LIVE_XTP_QUOTE_HOST / _QUOTE_PORT / _TRADE_HOST / _TRADE_PORT
    ALPHAPILOT_LIVE_XTP_QUOTE_PROTOCOL (TCP/UDP) / _LOG_LEVEL

``ALPHAPILOT_LIVE_<BROKER>_SETTING_JSON`` overrides the whole dict (raw JSON in
the gateway's native keys) for anything the field map doesn't cover.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Callable, Mapping

ENV_PREFIX = "ALPHAPILOT_LIVE_"


@dataclass(frozen=True)
class SettingField:
    """One connect-setting entry: env suffix -> the gateway's native (Chinese) key."""

    env_suffix: str
    gateway_key: str
    cast: Callable[[str], Any] = str
    default: Any = ""


# vn.py A-share stock gateways share this connect-setting shape.
_COMMON_FIELDS: tuple[SettingField, ...] = (
    SettingField("ACCOUNT", "账号"),
    SettingField("PASSWORD", "密码"),
    SettingField("CLIENT_ID", "客户号", int, 1),
    SettingField("QUOTE_HOST", "行情地址"),
    SettingField("QUOTE_PORT", "行情端口", int, 0),
    SettingField("TRADE_HOST", "交易地址"),
    SettingField("TRADE_PORT", "交易端口", int, 0),
    SettingField("QUOTE_PROTOCOL", "行情协议", str, "TCP"),
    SettingField("LOG_LEVEL", "日志级别", str, "INFO"),
)


@dataclass(frozen=True)
class BrokerSpec:
    """Everything the live system needs to drive one broker."""

    name: str                      # registry key, lowercase (e.g. "xtp")
    gateway_path: str              # "package.module:ClassName" of the vn.py gateway
    gateway_name: str              # vn.py gateway_name passed to MainEngine calls
    setting_fields: tuple[SettingField, ...] = field(default=_COMMON_FIELDS)
    description: str = ""


_BROKERS: dict[str, BrokerSpec] = {}


def register_broker(spec: BrokerSpec) -> None:
    _BROKERS[spec.name.lower()] = spec


def get_broker(name: str) -> BrokerSpec:
    spec = _BROKERS.get(name.lower())
    if spec is None:
        raise ValueError(f"unknown broker {name!r}; registered: {sorted(_BROKERS)}")
    return spec


def list_brokers() -> list[BrokerSpec]:
    return [_BROKERS[k] for k in sorted(_BROKERS)]


def resolve_gateway_class(name: str) -> Any:
    """Import and return the vn.py gateway class for broker ``name``.

    Raises ImportError with an actionable message when the gateway package is
    not installed on this machine (e.g. running on macOS where the broker SDKs
    have no build).
    """
    spec = get_broker(name)
    module_path, cls_name = spec.gateway_path.split(":")
    try:
        module = import_module(module_path)
        return getattr(module, cls_name)
    except (ImportError, AttributeError) as exc:
        # AttributeError covers the dev-machine case where the vendored source
        # folder resolves as an empty namespace package (repo root on sys.path)
        # even though the compiled gateway is not installed.
        raise ImportError(
            f"broker {spec.name!r} needs the {module_path!r} package (compiled vn.py "
            f"gateway). Install it in the live environment (see Dockerfile.live): {exc}"
        ) from exc


def gateway_importable(name: str) -> bool:
    try:
        resolve_gateway_class(name)
        return True
    except Exception:  # noqa: BLE001 - availability probe
        return False


def build_connect_setting(name: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build the gateway's native connect-setting dict from the environment.

    Precedence: ``..._SETTING_JSON`` (full override) > per-field env vars >
    field defaults.
    """
    spec = get_broker(name)
    env = os.environ if env is None else env
    prefix = f"{ENV_PREFIX}{spec.name.upper()}_"

    raw_json = env.get(f"{prefix}SETTING_JSON")
    if raw_json:
        parsed = json.loads(raw_json)
        if not isinstance(parsed, dict):
            raise ValueError(f"{prefix}SETTING_JSON must be a JSON object")
        return parsed

    setting: dict[str, Any] = {}
    for fld in spec.setting_fields:
        raw = env.get(prefix + fld.env_suffix)
        if raw is None or raw == "":
            setting[fld.gateway_key] = fld.default
        else:
            setting[fld.gateway_key] = fld.cast(raw)
    return setting


def missing_setting_fields(name: str, env: Mapping[str, str] | None = None) -> list[str]:
    """Env variable names still unset for broker ``name`` (empty-string defaults)."""
    spec = get_broker(name)
    env = os.environ if env is None else env
    prefix = f"{ENV_PREFIX}{spec.name.upper()}_"
    if env.get(f"{prefix}SETTING_JSON"):
        return []
    return [
        prefix + fld.env_suffix
        for fld in spec.setting_fields
        if fld.default == "" and not env.get(prefix + fld.env_suffix)
    ]


# ---- built-in brokers ------------------------------------------------------ #
register_broker(
    BrokerSpec(
        name="xtp",
        gateway_path="vnpy_xtp:XtpGateway",
        gateway_name="XTP",
        setting_fields=_COMMON_FIELDS + (SettingField("SOFTWARE_KEY", "授权码"),),
        description="中泰证券 XTP（SDK 2.2.50.8）",
    )
)
register_broker(
    BrokerSpec(
        name="emt",
        gateway_path="vnpy_emt:EmtGateway",
        gateway_name="EMT",
        description="东方财富证券 EMT（trade ~2.27 / quote ~2.19）",
    )
)
