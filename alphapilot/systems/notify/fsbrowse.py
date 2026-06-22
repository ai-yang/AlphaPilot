"""Sandboxed, read-only local file browsing for inbound chat commands.

Exposes ``/ls`` ``/cat`` ``/tree`` ``/get`` over a messaging channel, but only
*inside one configured root* and only for *reading*. Every path is resolved (so
``..`` and escaping symlinks are normalised), checked to stay within the root, and
screened against a deny-list of secret-bearing names — even if such a file happens
to sit under the root. The whole feature is opt-in (``options.file_browse_enabled``).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from alphapilot.systems.notify.config import load_notify_config

_MAX_ENTRIES = 100  # per /ls listing
_MAX_TREE_ENTRIES = 200  # total across a /tree walk

# Names (any path component) and globs (final component) that are never served,
# so secrets under the root can't leak even when browsing is enabled.
_DENY_NAMES = {".git", ".env", ".ssh", "credentials", "node_modules", "__pycache__"}
_DENY_GLOBS = (
    ".env*",
    "*secret*",
    "*token*",
    "*password*",
    "credentials*",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
)


class FileBrowseError(ValueError):
    """User-facing problem (disabled, out of bounds, denied, not found, too big)."""


def settings() -> dict[str, Any]:
    """Resolve the current file-browse settings from notify config options."""
    opts = load_notify_config().get("options", {})
    root_raw = str(opts.get("file_browse_root") or "").strip()
    root = (Path(root_raw).expanduser() if root_raw else Path.cwd()).resolve()
    try:
        max_kb = max(1, int(opts.get("file_browse_max_kb", 256)))
    except (TypeError, ValueError):
        max_kb = 256
    return {
        "enabled": bool(opts.get("file_browse_enabled", False)),
        "root": root,
        "allow_download": bool(opts.get("file_browse_allow_download", True)),
        "max_bytes": max_kb * 1024,
    }


def _check_enabled(st: dict[str, Any]) -> None:
    if not st["enabled"]:
        raise FileBrowseError("文件浏览未启用 / file browsing is disabled")


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_denied(path: Path) -> bool:
    # Absolute guard: never serve the credentials dir, wherever it is.
    cred = Path("~/.alphapilot/credentials").expanduser()
    try:
        if _within(path.resolve(), cred.resolve()):
            return True
    except OSError:
        pass
    for part in path.parts:
        low = part.lower()
        if low in _DENY_NAMES:
            return True
        if any(fnmatch.fnmatch(low, glob) for glob in _DENY_GLOBS):
            return True
    return False


def resolve_within_root(rel: str, *, st: dict[str, Any] | None = None) -> Path:
    """Resolve *rel* under the sandbox root, rejecting escapes and denied names."""
    st = st or settings()
    root = st["root"]
    rel = (rel or "").strip().lstrip("/").lstrip("~")
    resolved = (root / rel).resolve()
    if resolved != root and not _within(resolved, root):
        raise FileBrowseError("路径越界 / path escapes the sandbox root")
    if _is_denied(resolved):
        raise FileBrowseError("该路径被禁止访问 / path is denied")
    return resolved


def _human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def _display(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path)
    return "." if str(rel) == "." else str(rel)


def _entry_line(path: Path) -> str:
    try:
        if path.is_dir():
            return f"📁 {path.name}/"
        return f"📄 {path.name}  ·  {_human_size(path.stat().st_size)}"
    except OSError:
        return f"❔ {path.name}"


def ls(rel: str = "") -> str:
    st = settings()
    _check_enabled(st)
    target = resolve_within_root(rel, st=st)
    if not target.exists():
        raise FileBrowseError(f"不存在 / not found: {rel or '.'}")
    if target.is_file():
        return f"📄 {_display(target, st['root'])}  ·  {_human_size(target.stat().st_size)}"
    rows: list[str] = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if _is_denied(child):
            continue
        rows.append(_entry_line(child))
        if len(rows) >= _MAX_ENTRIES:
            rows.append(f"… (truncated at {_MAX_ENTRIES})")
            break
    body = "\n".join(rows) if rows else "(empty)"
    return f"📁 {_display(target, st['root'])}\n{body}"


def _walk(node: Path, root: Path, *, prefix: str, depth: int, lines: list[str], budget: list[int]) -> None:
    if depth <= 0 or budget[0] <= 0:
        return
    try:
        children = sorted(node.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return
    for child in children:
        if _is_denied(child):
            continue
        if budget[0] <= 0:
            lines.append(f"{prefix}…")
            return
        budget[0] -= 1
        if child.is_dir():
            lines.append(f"{prefix}{child.name}/")
            _walk(child, root, prefix=prefix + "  ", depth=depth - 1, lines=lines, budget=budget)
        else:
            lines.append(f"{prefix}{child.name}")


def tree(rel: str = "", *, depth: int = 2) -> str:
    st = settings()
    _check_enabled(st)
    target = resolve_within_root(rel, st=st)
    if not target.exists():
        raise FileBrowseError(f"不存在 / not found: {rel or '.'}")
    if target.is_file():
        return _entry_line(target)
    lines = [f"📁 {_display(target, st['root'])}"]
    _walk(target, st["root"], prefix="  ", depth=max(1, depth), lines=lines, budget=[_MAX_TREE_ENTRIES])
    return "\n".join(lines)


def read_text(rel: str) -> str:
    st = settings()
    _check_enabled(st)
    target = resolve_within_root(rel, st=st)
    if not target.is_file():
        raise FileBrowseError(f"不是文件 / not a file: {rel}")
    max_bytes = st["max_bytes"]
    with target.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    header = f"📄 {_display(target, st['root'])}"
    if truncated:
        text += f"\n… (truncated at {max_bytes // 1024} KB)"
    return f"{header}\n{text}"


def file_for_download(rel: str) -> Path:
    """Validate *rel* for transfer and return its absolute path (no read here)."""
    st = settings()
    _check_enabled(st)
    if not st["allow_download"]:
        raise FileBrowseError("文件下载未启用 / file download is disabled")
    target = resolve_within_root(rel, st=st)
    if not target.is_file():
        raise FileBrowseError(f"不是文件 / not a file: {rel}")
    size = target.stat().st_size
    if size > st["max_bytes"]:
        raise FileBrowseError(
            f"文件过大 / file too large: {_human_size(size)} > {st['max_bytes'] // 1024} KB"
        )
    return target
