"""Project-root data paths for user-owned artifacts."""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path.cwd()


def important_data_dir() -> Path:
    raw = os.getenv("ALPHAPILOT_IMPORTANT_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (_PROJECT_ROOT / "important_data").resolve()


def strategy_zoo_dir() -> Path:
    return important_data_dir() / "strategy_zoo"


def factor_qlib_templates_dir() -> Path:
    return important_data_dir() / "factor_qlib_templates"


# Relative paths stored in older strategy metadata / .env examples.
LEGACY_PATH_REMAP: dict[str, str] = {
    "git_ignore_folder/strategy_zoo": "important_data/strategy_zoo",
    "git_ignore_folder/factor_qlib_templates": "important_data/factor_qlib_templates",
}


def remap_legacy_relative_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    for old, new in LEGACY_PATH_REMAP.items():
        if normalized == old or normalized.startswith(old + "/"):
            return normalized.replace(old, new, 1)
    return text
