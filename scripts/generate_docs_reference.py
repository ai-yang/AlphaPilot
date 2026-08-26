#!/usr/bin/env python3
"""Generate checked-in CLI, Portal, HTTP and component documentation indexes."""

from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# A source checkout may coexist with an editable install or another Git
# worktree. Always document the checkout that owns this generator.
if sys.path[0] != str(ROOT):
    sys.path.insert(0, str(ROOT))
DOCS = ROOT / "docs"
CATALOG_PATH = DOCS / "catalog.json"
REFERENCE_DIR = DOCS / "reference"


def _catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _isolated_engine():
    """Build first-party components without touching user runtime state."""

    temporary = tempfile.TemporaryDirectory(prefix="alphapilot-docs-")
    root = Path(temporary.name)
    overrides = {
        "ALPHAPILOT_IMPORTANT_DATA_DIR": str(root / "important_data"),
        "ALPHAPILOT_FACTOR_ZOO_DIR": str(root / "factor_zoo"),
        "ALPHAPILOT_STRATEGY_PARAM_DIR": str(root / "strategy_zoo"),
        "ALPHAPILOT_QLIB_DATA_DIR": str(root / "qlib"),
        "ALPHAPILOT_RAW_DATA_DIR": str(root / "raw"),
        "ALPHAPILOT_ADJUST_FACTOR_DIR": str(root / "adjust"),
        "ALPHAPILOT_WORKSPACE_ROOT": str(root / "workspaces"),
        "ALPHAPILOT_LOG_DIR": str(root / "logs"),
        "ALPHAPILOT_LIVE_LEDGER_DIR": str(root / "ledger"),
        "ALPHAPILOT_LIVE_STATE_DIR": str(root / "state"),
        "ALPHAPILOT_LIVE_MARKET_DATA_DIR": str(root / "market"),
        "ALPHAPILOT_STRATEGY_RUNTIME_STORE": str(root / "state" / "strategy.sqlite3"),
        "ALPHAPILOT_STRATEGY_DIR": str(root / "strategies"),
        "ALPHAPILOT_PORTFOLIO_POLICY_DIR": str(root / "policies"),
        "ALPHAPILOT_LIVE_MODE": "paper",
        "ALPHAPILOT_LIVE_BROKER": "paper",
        "ALPHAPILOT_LIVE_TRADE_BROKER": "paper",
        "ALPHAPILOT_LIVE_QUOTE_PROVIDER": "paper",
    }
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        from alphapilot.kernel import build_engine

        engine = build_engine(discover=False)
    except Exception:
        temporary.cleanup()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        raise

    def cleanup() -> None:
        engine.shutdown()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        temporary.cleanup()

    return engine, cleanup


def _summary(callable_object: Any) -> str:
    doc = inspect.getdoc(callable_object) or ""
    return doc.splitlines()[0].strip() if doc else "—"


def _annotation(value: Any) -> str:
    if value is inspect.Signature.empty:
        return "—"
    return str(value).replace("typing.", "").replace("<class '", "").replace("'>", "")


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _command_destination(name: str) -> tuple[str, str]:
    if name == "portal_operator_auth":
        return "首页/高级设置", "GET /api/portal/security（只读）"
    if name.startswith(("factor_", "category_")):
        return "因子与策略库", "/api/factors"
    if name.startswith("pool_"):
        return "行情数据", "/api/modules/run (stock_pool)"
    if name in {"mine", "mine_aff", "mine_gp", "mine_rl", "list_mine_logs", "delete_mine_log", "list_runs", "delete_run"}:
        return "因子挖掘", "/api/jobs、/api/mining"
    if name in {"backtest", "strategy_backtest", "strategy_backtest_list"}:
        return "回测", "/api/jobs、/api/backtests"
    if name.startswith("qlib_yaml_"):
        return "CLI 专用", "—"
    if name.startswith(("daily_", "trade_session_")):
        return "每日交易", "/api/daily-trade、/api/trade-sessions"
    if name.startswith("live_"):
        return "模拟与实盘", "/api/live"
    if name.startswith("trading_"):
        return "策略实例/模拟与实盘", "/api/trading"
    if name in {"prepare_data", "list_stocks", "delete_stock", "trim_stock", "refresh_stock", "data_viz"}:
        return "行情数据", "/api/data、/api/market"
    if name in {
        "portal", "portal_operator_auth", "portal_restart", "timezone",
        "modules", "clean_logs", "ui", "backtest_ui",
    }:
        return "首页/高级设置", "/api/portal、/api/modules、/api/logs"
    if name in {"scheduler"}:
        return "调度", "/api/schedules"
    if name in {"notify_commands"}:
        return "通知", "/api/notify"
    if name.startswith("strategy_"):
        return "因子与策略库/回测", "/api/strategies"
    if name in {"backtest_viz"}:
        return "回测", "/api/backtests"
    return "CLI", "—"


def _command_effect(name: str) -> str:
    if name in {"ui", "backtest_ui"}:
        return "仅输出迁移提示"
    if name in {"portal", "scheduler", "notify_commands", "data_viz", "backtest_viz", "live_run"}:
        return "长运行进程"
    if name.startswith("trading_broker_uat_"):
        return "本地受控券商 UAT"
    if name in {
        "live_brokers", "live_daemon_status", "live_ledger_events", "live_market_bars",
        "live_market_snapshot", "live_modes", "live_plugins", "live_preflight",
        "live_quote_providers", "live_risk_status", "live_state", "live_status",
    }:
        return "只读、诊断或本地计算"
    if name.startswith("live_"):
        return "交易/运行时写操作"
    if name == "trading_compatibility":
        return "兼容审计（可选写入 cutoff/报告）"
    if name == "trading_decision_compare":
        return "诊断写入"
    if name.startswith("trading_") and name not in {
        "trading_definitions", "trading_policies", "trading_instances", "trading_status",
        "trading_audit", "trading_deployments", "trading_diagnostics",
        "trading_decision_comparisons", "trading_backtest_status", "trading_broker_uat_status",
        "trading_broker_uat_preflight", "trading_removal_check",
    }:
        return "策略或部署写操作"
    if name.startswith("trading_"):
        return "只读、诊断或本地计算"
    if any(token in name for token in ("delete", "remove", "trim", "clean", "reset", "abort")):
        return "破坏性/清理操作"
    if name in {
        "list_mine_logs", "list_runs", "list_stocks", "modules", "daily_state",
        "trade_session_history", "trade_session_list", "trade_session_show", "category_list",
        "factor_duplicates", "factor_list", "factor_validate", "pool_list", "pool_show",
        "strategy_backtest_list", "qlib_yaml_validate",
    }:
        return "只读、诊断或本地计算"
    if name.startswith(("mine", "backtest")) or name in {
        "strategy_backtest", "daily_signals", "qlib_yaml_generate",
    }:
        return "计算并写入产物"
    if name in {"prepare_data", "refresh_stock"}:
        return "数据下载/转换写操作"
    if name in {"portal_operator_auth", "portal_restart", "timezone"}:
        return "配置或进程控制"
    if name == "strategy_create":
        return "研究资产写操作"
    if name.startswith(("factor_", "category_", "pool_", "trade_session_")) and not name.endswith(("list", "show", "history")):
        return "资源写操作"
    return "只读、诊断或本地计算"


def _cli_status(name: str, catalog: dict[str, Any]) -> str:
    statuses = catalog["cli_status"]
    if name in statuses["deprecated"]:
        return "已弃用"
    if name in statuses["fallback"]:
        return "回退工具"
    if name in statuses["local_uat"]:
        return "仅本地 UAT"
    return "正式"


def _cli_row(name: str, function: Any, catalog: dict[str, Any]) -> str:
    signature = inspect.signature(function)
    portal, api = _command_destination(name)
    return (
        f"| `{name}` | {_md_cell(_summary(function))} | `{_md_cell(signature)}` | "
        f"`{_md_cell(_annotation(signature.return_annotation))}` | {_command_effect(name)} | "
        f"{_cli_status(name, catalog)} | {portal} | `{api}` |"
    )


def _cli_reference(engine: Any, catalog: dict[str, Any]) -> str:
    lines = [
        "# CLI 完整参考",
        "",
        "> 本文件由 `scripts/generate_docs_reference.py` 生成，请勿手工编辑。",
        "",
        f"当前内置公共命令共 **{len(engine.collect_commands())}** 个。第三方模块命令不计入此清单。",
        "",
        "通用帮助：`alphapilot <command> -- --help`。参数由 Python Fire 解析，布尔值建议显式写成 `--flag=True|False`。",
        "",
    ]
    for module_name, module in engine.modules.items():
        commands = {
            name: function
            for name, function in module.commands().items()
            if name not in catalog["cli_status"]["deprecated"]
        }
        if not commands:
            continue
        title = catalog["modules"][module_name]["title"]
        lines.extend([f"## {title}（`{module_name}`）", "", "| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |", "|---|---|---|---|---|---|---|---|"])
        for name, function in sorted(commands.items()):
            lines.append(_cli_row(name, function, catalog))
        lines.append("")

    all_commands = engine.collect_commands()
    lines.extend([
        "## 已弃用命令附录",
        "",
        f"这些命令仍计入 {len(all_commands)} 个公共命令，但只输出迁移提示，不应由新脚本继续采用。",
        "",
        "| 命令 | 用途 | 参数签名 | 返回 | 影响 | 状态 | Portal | HTTP |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for name in catalog["cli_status"]["deprecated"]:
        lines.append(_cli_row(name, all_commands[name], catalog))
    lines.extend([
        "",
        "## 已移除命令（不可用）",
        "",
        "以下命令不再注册，也不应由脚本或自动化调用：",
        "",
        *[f"- `{name}`" for name in catalog["cli_status"]["removed"]],
        "",
    ])
    return "\n".join(lines)


def _api_domain(path: str) -> str:
    parts = path.split("/")
    return parts[2] if path.startswith("/api/") and len(parts) > 2 else "static"


def _api_auth(method: str, path: str) -> str:
    if path == "/api/live/runtime/preflight":
        return "免 Operator token（只读探测）"
    if method != "GET" and path.startswith(("/api/live/", "/api/trading/")):
        return "Portal operator auth（required / optional）"
    if method == "GET" and path.startswith(("/api/live/", "/api/trading/")):
        return "免 Operator token"
    if path == "/api/portal/security":
        return "只读、免 Operator token"
    if path == "/api/notify/feishu/events":
        return "飞书回调校验"
    return "本机 Portal"


def _http_reference(spec: dict[str, Any]) -> str:
    methods = {"get", "post", "put", "patch", "delete"}
    grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method not in methods:
                continue
            grouped.setdefault(_api_domain(path), []).append((method.upper(), path, operation))
    count = sum(len(items) for items in grouped.values())
    lines = [
        "# HTTP API 完整参考",
        "",
        "> 本文件由 `scripts/generate_docs_reference.py` 从 FastAPI OpenAPI 生成，请勿手工编辑。",
        "",
        f"当前共有 **{len(spec['paths'])}** 条路径、**{count}** 个操作。运行 Portal 后可访问 `/docs` 查看请求和响应 Schema。",
        "",
        "Portal 默认只监听 `127.0.0.1`。交易写操作由启动时冻结的 "
        "`required | optional` 模式决定；`optional + 0.0.0.0 + wildcard CORS` "
        "允许可达客户端无令牌写入，不等于互联网级认证边界。",
        "",
    ]
    for domain in sorted(grouped):
        lines.extend([f"## `{domain}`", "", "| 方法 | 路径 | 用途 | 认证/边界 |", "|---|---|---|---|"])
        for method, path, operation in sorted(grouped[domain], key=lambda row: (row[1], row[0])):
            summary = str(operation.get("summary") or operation.get("operationId") or "—")
            lines.append(f"| `{method}` | `{path}` | {summary} | {_api_auth(method, path)} |")
        lines.append("")
    return "\n".join(lines)


def _portal_reference(catalog: dict[str, Any]) -> str:
    lines = [
        "# Portal 功能矩阵",
        "",
        "> 页面清单由 `docs/catalog.json` 管理，并与 React Router 路由进行一致性校验。",
        "",
        "| 页面 | 路由 | 主要功能 | CLI 等价入口 | HTTP 领域 | 能力关系 | 使用说明 | 截图 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for page in catalog["portal_pages"]:
        lines.append(
            f"| {page['title']} | `{page['route']}` | {page['features']} | "
            f"`{page['cli']}` | `{page['api']}` | {page['equivalence']} | "
            f"[打开](../{page['user_doc']}) | [查看](../{page['screenshot']}) |"
        )
    lines.extend([
        "",
        "## 接口边界",
        "",
        "- Portal 是现有系统和模块的操作界面，不另外实现交易或研究逻辑。",
        "- `/api/trading` 承担正式策略实例与部署控制；`/api/live` 承担运行时和人工运维。",
        "- 两个交易前缀的写操作统一遵循 `required | optional` operator-auth；安全状态 HTTP 只读，只能由本机 CLI 修改。",
        "- `optional + 0.0.0.0 + wildcard CORS` 会允许可达客户端无令牌写入，Portal 必须持续显示高风险警告。",
        "- UAT 只能由本地 CLI 发起，Portal 仅展示 UAT 结果。",
        "- 高级设置中的 `/api/modules/run` 是本机运维入口，不应暴露到不可信网络。",
        "",
    ])
    return "\n".join(lines)


def _component_reference(engine: Any, catalog: dict[str, Any]) -> str:
    lines = [
        "# 组件与文档覆盖矩阵",
        "",
        "> 本文件由 `scripts/generate_docs_reference.py` 生成。组件与文档映射来自 `docs/catalog.json`。",
        "",
        "## 系统",
        "",
        "| 系统 | 实现 | 用户说明 | 开发文档 |",
        "|---|---|---|---|",
    ]
    for name, system in engine.systems.items():
        item = catalog["systems"][name]
        impl = f"{type(system).__module__}.{type(system).__qualname__}"
        lines.append(f"| `{name}` | `{impl}` | [打开](../{item['user_doc']}) | [打开](../{item['developer_doc']}) |")
    lines.extend(["", "## 模块", "", "| 模块 | CLI 数量 | 用户说明 | 开发文档 |", "|---|---:|---|---|"])
    for name, module in engine.modules.items():
        item = catalog["modules"][name]
        lines.append(
            f"| `{name}` | {len(module.commands())} | [打开](../{item['user_doc']}) | "
            f"[打开](../{item['developer_doc']}) |"
        )
    lines.extend([
        "",
        "## 非注册策略子系统",
        "",
        "- [择时 provider](../developer/subsystems/timing.md)",
        "- [Qlib 横截面选股](../developer/subsystems/selection.md)",
        "- [研究门禁与证据](../developer/subsystems/research.md)",
        "- [自定义 Provider、PortfolioPolicy 与 artifact](../developer/strategy-extension.md)",
        "",
    ])
    return "\n".join(lines)


def _router_routes() -> set[str]:
    text = (ROOT / "alphapilot/modules/portal/web/src/main.tsx").read_text(encoding="utf-8")
    routes = {"/"}
    for value in re.findall(r'\{ path: "([^"]+)"', text):
        routes.add("/" + value.strip("/"))
    return routes


def generate() -> dict[Path, str]:
    catalog = _catalog()
    engine, cleanup = _isolated_engine()
    try:
        expected_systems = set(catalog["systems"])
        expected_modules = set(catalog["modules"])
        if set(engine.systems) != expected_systems:
            raise RuntimeError(f"system catalog drift: runtime={sorted(engine.systems)} catalog={sorted(expected_systems)}")
        if set(engine.modules) != expected_modules:
            raise RuntimeError(f"module catalog drift: runtime={sorted(engine.modules)} catalog={sorted(expected_modules)}")
        removed = set(catalog["cli_status"]["removed"])
        exposed_removed = removed.intersection(engine.collect_commands())
        if exposed_removed:
            raise RuntimeError(f"removed CLI commands are exposed: {sorted(exposed_removed)}")
        catalog_routes = {item["route"] for item in catalog["portal_pages"]}
        source_routes = _router_routes()
        if catalog_routes != source_routes:
            raise RuntimeError(f"Portal route catalog drift: source={sorted(source_routes)} catalog={sorted(catalog_routes)}")

        from alphapilot.modules.portal.api import create_app

        spec = create_app(engine=engine).openapi()
        return {
            REFERENCE_DIR / "cli.md": _cli_reference(engine, catalog),
            REFERENCE_DIR / "http-api.md": _http_reference(spec),
            REFERENCE_DIR / "portal-capabilities.md": _portal_reference(catalog),
            REFERENCE_DIR / "components.md": _component_reference(engine, catalog),
        }
    finally:
        cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when checked-in references are stale")
    args = parser.parse_args()
    outputs = generate()
    stale: list[str] = []
    for path, content in outputs.items():
        normalized = content.rstrip() + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != normalized:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized, encoding="utf-8")
    if stale:
        print("stale generated documentation: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
