"""Path safety helpers for destructive filesystem operations."""

from __future__ import annotations

from pathlib import Path


def ensure_child_path(root: Path, target: Path) -> Path:
    """Resolve *target* and assert it is *root* or a descendant of *root*."""
    root_resolved = Path(root).expanduser().resolve()
    target_resolved = Path(target).expanduser().resolve()
    if target_resolved == root_resolved:
        return target_resolved
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Path {target_resolved} is outside allowed root {root_resolved}") from exc
    return target_resolved
