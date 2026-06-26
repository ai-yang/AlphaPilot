#!/usr/bin/env python3
"""清理 log 目录中的空文件夹和无效桩目录。

删除条件（满足任一即删除该目录及其全部内容）：
1. 空文件夹
2. 直接子项恰好为：1 个子目录 + 1 个 .log 文件
3. log 根目录下的会话目录：仅有 1 个 pid 子目录，且其中只有 1 个 .log（中断/失败的 mining 桩目录）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alphapilot.log.cleanup import (
    clean_log_dirs as _clean_log_dirs,
    collect_removable_log_dirs,
    should_remove_log_dir,
)

collect_removable = collect_removable_log_dirs
should_remove = should_remove_log_dir


def clean_log_dirs(log_root: str | Path, execute: bool = False) -> int:
    try:
        result = _clean_log_dirs(log_root, execute=execute)
    except FileNotFoundError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    action = "已删除" if result.execute else "将删除"
    for path in result.paths:
        print(f"{action}: {path}")

    print(f"\n{action} {result.removed} 个目录")
    if not result.execute and result.removed:
        print("加上 --execute 才会真正删除")
    return 0


def main() -> int:
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
    return clean_log_dirs(args.log_dir, execute=args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
