"""Utilities for cleaning empty or stub log directories."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LogCleanupResult:
    """Structured result returned by a log cleanup pass."""

    log_root: Path
    execute: bool
    removed: int
    paths: list[Path] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "log_root": str(self.log_root),
            "execute": self.execute,
            "removed": self.removed,
            "paths": [str(path) for path in self.paths],
        }


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _entries(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _is_stub_session(path: Path, log_root: Path) -> bool:
    """Session root with a single pid directory containing only one .log file."""
    if path.parent != log_root:
        return False
    entries = _entries(path)
    if len(entries) != 1:
        return False
    pid_dir = entries[0]
    if not pid_dir.is_dir() or pid_dir.is_symlink():
        return False
    child_entries = _entries(pid_dir)
    child_dirs = [entry for entry in child_entries if entry.is_dir()]
    child_logs = [entry for entry in child_entries if entry.is_file() and entry.suffix == ".log"]
    child_other = [entry for entry in child_entries if entry.is_file() and entry.suffix != ".log"]
    return (
        len(child_entries) == 1
        and not child_dirs
        and len(child_logs) == 1
        and not child_other
    )


def should_remove_log_dir(path: Path, log_root: Path) -> bool:
    """Return True when a directory matches AlphaPilot log cleanup rules."""
    if not path.is_dir() or path.is_symlink():
        return False

    entries = _entries(path)
    if not entries:
        return True

    dirs = [entry for entry in entries if entry.is_dir()]
    files = [entry for entry in entries if entry.is_file()]
    logs = [entry for entry in files if entry.suffix == ".log"]
    non_logs = [entry for entry in files if entry.suffix != ".log"]

    if len(entries) == 2 and len(dirs) == 1 and len(logs) == 1 and not non_logs:
        return True

    return _is_stub_session(path, log_root)


def collect_removable_log_dirs(log_root: str | Path) -> list[Path]:
    """Collect removable directories under ``log_root``, highest paths first."""
    root = Path(log_root).expanduser().resolve()
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_dir() and path != root and should_remove_log_dir(path, root)
    ]
    candidates.sort(key=lambda item: len(item.parts))

    to_remove: list[Path] = []
    covered: set[Path] = set()
    for path in candidates:
        if any(path == parent or _is_under(path, parent) for parent in covered):
            continue
        to_remove.append(path)
        covered.add(path)
    return to_remove


def clean_log_dirs(log_root: str | Path, *, execute: bool = False) -> LogCleanupResult:
    """Preview or remove AlphaPilot log directories that match cleanup rules."""
    root = Path(log_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"log directory does not exist: {root}")

    removed_paths: list[Path] = []
    while True:
        batch = collect_removable_log_dirs(root)
        if not batch:
            break
        for path in batch:
            removed_paths.append(path.relative_to(root))
            if execute:
                shutil.rmtree(path)
        if not execute:
            break

    return LogCleanupResult(
        log_root=root,
        execute=execute,
        removed=len(removed_paths),
        paths=removed_paths,
    )
