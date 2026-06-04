"""Pickle cache root resolution and per-workflow scope (mine vs backtest)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Literal

PickleCacheScope = Literal["mine", "backtest"]

_scope: ContextVar[PickleCacheScope | None] = ContextVar("pickle_cache_scope", default=None)
_folder_override: ContextVar[str | Path | None] = ContextVar("pickle_cache_folder_override", default=None)


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default.resolve()
    p = Path(value).expanduser()
    return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()


def default_pickle_cache_dir_mine() -> Path:
    return _env_path("ALPHAPILOT_PICKLE_CACHE_DIR_MINE", Path.cwd() / "pickle_cache" / "mine")


def default_pickle_cache_dir_backtest() -> Path:
    return _env_path("ALPHAPILOT_PICKLE_CACHE_DIR_BACKTEST", Path.cwd() / "pickle_cache" / "backtest")


def _resolve_explicit_folder(folder: str | Path) -> Path:
    p = Path(folder).expanduser()
    return (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()


@contextmanager
def pickle_cache_scope(
    scope: PickleCacheScope | None,
    *,
    folder: str | Path | None = None,
) -> Iterator[None]:
    """Set active pickle cache root for nested factor execute / qlib develop calls."""
    token_scope = _scope.set(scope)
    token_folder = _folder_override.set(folder)
    try:
        yield
    finally:
        _scope.reset(token_scope)
        _folder_override.reset(token_folder)


def get_pickle_cache_scope() -> PickleCacheScope | None:
    return _scope.get()


def resolve_pickle_cache_dir(
    *,
    explicit_folder: str | Path | None = None,
    scope: PickleCacheScope | None = None,
) -> Path:
    """
    Resolve directory that holds ``<module>.<func>/<hash>.pkl`` subfolders.

    Precedence: explicit_folder arg > context folder override > context scope
    > legacy ``PICKLE_CACHE_FOLDER_PATH_STR`` / ``ALPHAPILOT_PICKLE_CACHE_DIR``.
    """
    if explicit_folder is not None:
        return _resolve_explicit_folder(explicit_folder)

    ctx_folder = _folder_override.get()
    if ctx_folder is not None:
        return _resolve_explicit_folder(ctx_folder)

    active_scope = scope if scope is not None else _scope.get()
    if active_scope == "mine":
        return default_pickle_cache_dir_mine()
    if active_scope == "backtest":
        return default_pickle_cache_dir_backtest()

    legacy = os.getenv("ALPHAPILOT_PICKLE_CACHE_DIR")
    if legacy:
        return _resolve_explicit_folder(legacy)

    from alphapilot.core.conf import RD_AGENT_SETTINGS

    return Path(RD_AGENT_SETTINGS.pickle_cache_folder_path_str).expanduser().resolve()


def pickle_cache_enabled() -> bool:
    if os.getenv("ALPHAPILOT_PICKLE_CACHE_ENABLED") is not None:
        return os.getenv("ALPHAPILOT_PICKLE_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
    from alphapilot.core.conf import RD_AGENT_SETTINGS

    return bool(RD_AGENT_SETTINGS.cache_with_pickle)
