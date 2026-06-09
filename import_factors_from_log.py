#!/usr/bin/env python3
"""从 mining log 提取因子公式并导入因子库（自动去重）。

支持三种来源（按优先级合并）：
1. ``02_factor_expression/.../experiment generation/*.pkl`` — FactorTask 列表
2. common_logs.log 中的 ``Added new factor: [...] with expression: [...]``
3. llm_messages 日志中的 ``factor_name`` / ``factor_expression`` 对

用法::

    python import_factors_from_log.py
    python import_factors_from_log.py --log-dir log/2026-06-04_15-32-47-893456
    python import_factors_from_log.py --dry-run
"""

from __future__ import annotations

import argparse
import ast
import pickle
import re
import sys
from pathlib import Path

ADDED_FACTOR_RE = re.compile(
    r"Added new factor:\s*(?P<names>\[.+?\])\s+with expression:\s*(?P<exprs>\[.+?\])\s*$"
)
FACTOR_NAME_RE = re.compile(r"^factor_name:\s*(.+)$", re.MULTILINE)
FACTOR_EXPR_RE = re.compile(r"^factor_expression:\s*(.+)$", re.MULTILINE)


def _normalize_expr(expr: str) -> str:
    return " ".join(expr.strip().split())


def _normalize_name(name: str) -> str:
    return name.strip()


def _pair_from_blocks(text: str) -> list[tuple[str, str]]:
    names = [m.group(1).strip() for m in FACTOR_NAME_RE.finditer(text)]
    exprs = [m.group(1).strip() for m in FACTOR_EXPR_RE.finditer(text)]
    pairs: list[tuple[str, str]] = []
    for name, expr in zip(names, exprs):
        if name and expr:
            pairs.append((name, expr))
    return pairs


def _pair_from_added_factor_line(line: str) -> list[tuple[str, str]]:
    match = ADDED_FACTOR_RE.search(line)
    if not match:
        return []
    try:
        names = ast.literal_eval(match.group("names"))
        exprs = ast.literal_eval(match.group("exprs"))
    except (SyntaxError, ValueError):
        return []
    if not isinstance(names, list) or not isinstance(exprs, list):
        return []
    pairs: list[tuple[str, str]] = []
    for name, expr in zip(names, exprs):
        if isinstance(name, str) and isinstance(expr, str) and name.strip() and expr.strip():
            pairs.append((name.strip(), expr.strip()))
    return pairs


def _pair_from_pickle(path: Path) -> list[tuple[str, str]]:
    with path.open("rb") as handle:
        obj = pickle.load(handle)
    tasks = obj if isinstance(obj, list) else getattr(obj, "sub_tasks", [])
    pairs: list[tuple[str, str]] = []
    for task in tasks:
        name = getattr(task, "factor_name", None)
        expr = getattr(task, "factor_expression", None) or getattr(task, "factor_formulation", None)
        if isinstance(name, str) and isinstance(expr, str) and name.strip() and expr.strip():
            pairs.append((name.strip(), expr.strip()))
    return pairs


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """按表达式去重，保留首次出现的名称。"""
    seen_exprs: set[str] = set()
    seen_names: set[str] = set()
    unique: list[tuple[str, str]] = []
    for name, expr in pairs:
        norm_expr = _normalize_expr(expr)
        norm_name = _normalize_name(name)
        if norm_expr in seen_exprs or norm_name in seen_names:
            continue
        seen_exprs.add(norm_expr)
        seen_names.add(norm_name)
        unique.append((norm_name, expr.strip()))
    return unique


def collect_factors(log_dir: Path) -> list[tuple[str, str]]:
    if not log_dir.is_dir():
        raise FileNotFoundError(f"Log directory not found: {log_dir}")

    pairs: list[tuple[str, str]] = []

    for pkl_path in sorted(log_dir.rglob("02_factor_expression/**/experiment generation/*.pkl")):
        try:
            pairs.extend(_pair_from_pickle(pkl_path))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] skip pickle {pkl_path}: {exc}", file=sys.stderr)

    for log_path in sorted(log_dir.rglob("**/02_factor_expression/**/common_logs.log")):
        text = log_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            pairs.extend(_pair_from_added_factor_line(line))

    for log_path in sorted(log_dir.rglob("**/03_factor_values/**/llm_messages/**/common_logs.log")):
        pairs.extend(_pair_from_blocks(log_path.read_text(encoding="utf-8", errors="replace")))

    return _dedupe_pairs(pairs)


def load_existing_zoo(zoo_path: Path) -> tuple[set[str], set[str]]:
    if not zoo_path.exists():
        return set(), set()
    import pandas as pd

    df = pd.read_csv(zoo_path)
    names = {_normalize_name(str(v)) for v in df.get("factor_name", []) if str(v).strip()}
    exprs = {_normalize_expr(str(v)) for v in df.get("factor_expression", []) if str(v).strip()}
    return names, exprs


def import_to_zoo(
    pairs: list[tuple[str, str]],
    *,
    zoo_path: Path,
    dry_run: bool,
    validate: bool,
) -> dict[str, int]:
    import pandas as pd

    factor_system = None
    if validate:
        from alphapilot.kernel import build_engine

        factor_system = build_engine(discover=True).get_system("factor")

    existing_names, existing_exprs = load_existing_zoo(zoo_path)
    stats = {
        "found": len(pairs),
        "added": 0,
        "skipped_duplicate": 0,
        "skipped_invalid": 0,
    }
    new_rows: list[dict[str, str]] = []

    for name, expr in pairs:
        norm_expr = _normalize_expr(expr)
        norm_name = _normalize_name(name)

        if norm_expr in existing_exprs or norm_name in existing_names:
            stats["skipped_duplicate"] += 1
            print(f"[skip] duplicate: {norm_name}")
            continue

        if validate and factor_system is not None:
            validation = factor_system.validate_expression(expr)
            if not validation.acceptable:
                stats["skipped_invalid"] += 1
                print(f"[skip] not acceptable: {norm_name} ({validation.code}: {validation.message})")
                continue

        if dry_run:
            stats["added"] += 1
            print(f"[dry-run] would add: {norm_name} -> {expr}")
            existing_names.add(norm_name)
            existing_exprs.add(norm_expr)
            continue

        new_rows.append({"factor_name": norm_name, "factor_expression": expr.strip()})
        existing_names.add(norm_name)
        existing_exprs.add(norm_expr)
        stats["added"] += 1
        print(f"[add] {norm_name}")

    if not dry_run and new_rows:
        zoo_path.parent.mkdir(parents=True, exist_ok=True)
        if zoo_path.exists():
            df = pd.read_csv(zoo_path)
        else:
            df = pd.DataFrame(columns=["factor_name", "factor_expression"])
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        df.to_csv(zoo_path, index=False)
        print(f"[save] {zoo_path}")

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 mining log 导入因子到因子库")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("log"),
        help="log 根目录或单个会话目录（默认: log）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要导入的因子，不写因子库",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="仅导入通过 is_acceptable 校验的表达式",
    )
    args = parser.parse_args(argv)

    log_dir = args.log_dir.expanduser().resolve()
    pairs = collect_factors(log_dir)
    if not pairs:
        print(f"No factors found under {log_dir}")
        return 1

    from alphapilot.kernel import build_engine

    zoo_path = Path(build_engine(discover=True).config.factor.zoo_dir) / "factor_zoo.csv"
    print(f"Collected {len(pairs)} unique factor(s) from {log_dir}")
    print(f"Target zoo: {zoo_path}")
    stats = import_to_zoo(
        pairs,
        zoo_path=zoo_path,
        dry_run=args.dry_run,
        validate=args.validate,
    )
    print(
        "Done: "
        f"found={stats['found']} "
        f"added={stats['added']} "
        f"skipped_duplicate={stats['skipped_duplicate']} "
        f"skipped_invalid={stats['skipped_invalid']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
