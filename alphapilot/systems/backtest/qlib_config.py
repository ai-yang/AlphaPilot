"""Resolve which qlib yaml config to use for factor backtests."""

from __future__ import annotations

from typing import Any

DEFAULT_QLIB_CONFIG_SINGLE = "conf.yaml"
DEFAULT_QLIB_CONFIG_COMBINED = "conf_cn_combined_kdd_ver.yaml"


def default_qlib_config_name(exp: Any) -> str:
    """Legacy rule: single-factor vs combined-factor yaml."""
    based = getattr(exp, "based_experiments", None) or []
    if len(based) == 0:
        return DEFAULT_QLIB_CONFIG_SINGLE
    return DEFAULT_QLIB_CONFIG_COMBINED


def resolve_qlib_config_name(exp: Any, override: str | None = None) -> str:
    """
    Pick qlib config file name for ``qrun``.

    Priority: explicit override > ``exp.qlib_config_name`` > legacy based_experiments rule.
    """
    if override:
        return override
    exp_name = getattr(exp, "qlib_config_name", None)
    if exp_name:
        return str(exp_name)
    return default_qlib_config_name(exp)
