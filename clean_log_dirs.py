#!/usr/bin/env python3
"""清理 log 目录中的空文件夹和无效桩目录。

删除条件（满足任一即删除该目录及其全部内容）：
1. 空文件夹
2. 直接子项恰好为：1 个子目录 + 1 个 .log 文件
3. log 根目录下的会话目录：仅有 1 个 pid 子目录，且其中只有 1 个 .log（中断/失败的 mining 桩目录）
"""

import argparse
import shutil
import sys
from pathlib import Path


def _is_under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _entries(path):
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _is_stub_session(path, log_root):
    """会话根目录：pid 子目录里只有 common_logs.log。"""
    if path.parent != log_root:
        return False
    entries = _entries(path)
    if len(entries) != 1:
        return False
    pid_dir = entries[0]
    if not pid_dir.is_dir():
        return False
    child_entries = _entries(pid_dir)
    child_dirs = [e for e in child_entries if e.is_dir()]
    child_logs = [e for e in child_entries if e.is_file() and e.suffix == ".log"]
    child_other = [e for e in child_entries if e.is_file() and e.suffix != ".log"]
    return (
        len(child_entries) == 1
        and not child_dirs
        and len(child_logs) == 1
        and not child_other
    )


def should_remove(path, log_root):
    """Return True if this directory should be removed."""
    if not path.is_dir():
        return False

    entries = _entries(path)
    if not entries:
        return True

    dirs = [e for e in entries if e.is_dir()]
    files = [e for e in entries if e.is_file()]
    logs = [e for e in files if e.suffix == ".log"]
    non_logs = [e for e in files if e.suffix != ".log"]

    # 1 个子目录 + 1 个 .log，无其它文件
    if len(entries) == 2 and len(dirs) == 1 and len(logs) == 1 and not non_logs:
        return True

    if _is_stub_session(path, log_root):
        return True

    return False


def collect_removable(log_root):
    """Collect directories to remove, deepest paths first."""
    candidates = []
    for path in log_root.rglob("*"):
        if path.is_dir() and path != log_root and should_remove(path, log_root):
            candidates.append(path)
    candidates.sort(key=lambda p: len(p.parts), reverse=True)
    # 若父目录也会被删，只保留最顶层待删路径，避免重复 rmtree
    to_remove = []
    covered = set()
    for path in candidates:
        if any(path == c or _is_under(path, c) for c in covered):
            continue
        to_remove.append(path)
        covered.add(path)
    return to_remove


def clean_log_dirs(log_root, execute=False):
    if not log_root.is_dir():
        print(f"错误: 目录不存在: {log_root}", file=sys.stderr)
        return 1

    removed = 0
    while True:
        batch = collect_removable(log_root)
        if not batch:
            break
        for path in batch:
            rel = path.relative_to(log_root)
            if execute:
                shutil.rmtree(path)
                print(f"已删除: {rel}")
            else:
                print(f"将删除: {rel}")
            removed += 1
        if not execute:
            break

    action = "已删除" if execute else "将删除"
    print(f"\n{action} {removed} 个目录")
    if not execute and removed:
        print("加上 --execute 才会真正删除")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log_dir",
        nargs="?",
        default="log",
        type=Path,
        help="log 根目录（默认: ./log）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际删除（默认仅预览）",
    )
    args = parser.parse_args()
    log_root = args.log_dir.resolve()
    return clean_log_dirs(log_root, execute=args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
