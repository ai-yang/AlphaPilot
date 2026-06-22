"""Command parser and executor for inbound notification messages."""

from __future__ import annotations

import json
import re
import shlex
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from alphapilot.modules.portal import jobs
from alphapilot.systems.notify import fsbrowse
from alphapilot.systems.notify.config import (
    load_notify_config,
    public_notify_config,
    save_notify_config,
)
from alphapilot.systems.notify.inbound import (
    CommandContext,
    InboundMessage,
    InboundReply,
    append_event,
    append_turn,
    command_root,
    pending_path,
    recent_turns,
    redeem_pair_code,
)

SAFE_JOB_KINDS = set(jobs.VALID_KINDS)
QUERY_ACTIONS = {"help", "jobs", "status", "log", "result"}
FILE_ACTIONS = {"fs_ls", "fs_cat", "fs_tree", "fs_get"}
PENDING_TTL_MINUTES = 30
HISTORY_TURNS = 6  # prior turns fed to the natural-language planner

# Single source of truth for the command set: drives the parser routing below,
# the /help text, and Telegram's setMyCommands palette (no drift between them).
# ``command`` must be a Telegram-legal name ([a-z0-9_], <=32); ``desc`` <=256.
COMMAND_SPECS: list[dict[str, str]] = [
    {"command": "start", "desc": "配对设备或显示帮助 Pair with a code / show help", "usage": "/start [配对码]"},
    {"command": "help", "desc": "显示命令列表 Show this command list", "usage": "/help"},
    {"command": "jobs", "desc": "列出最近任务 List recent jobs", "usage": "/jobs"},
    {"command": "status", "desc": "查询任务状态 Job status", "usage": "/status [job_id]"},
    {"command": "log", "desc": "查看任务日志 Tail a job log", "usage": "/log <job_id>"},
    {"command": "result", "desc": "查看任务结果 Read a job result", "usage": "/result <job_id>"},
    {"command": "run", "desc": "启动任务 Start a job", "usage": "/run <kind> {json}"},
    {"command": "mine", "desc": "启动因子挖掘 Start factor mining", "usage": "/mine key=value"},
    {"command": "backtest", "desc": "启动回测 Start a backtest", "usage": "/backtest [factor|strategy] key=value"},
    {"command": "data", "desc": "数据任务 Data action", "usage": "/data action=download ..."},
    {"command": "cancel", "desc": "取消任务 Cancel a job", "usage": "/cancel <job_id>"},
    {"command": "confirm", "desc": "确认待执行计划 Confirm a pending action", "usage": "/confirm <id>"},
    {"command": "ls", "desc": "列出沙箱内文件 List files in the sandbox", "usage": "/ls [path]"},
    {"command": "cat", "desc": "查看文件内容 Show a file's text", "usage": "/cat <path>"},
    {"command": "tree", "desc": "目录树 Directory tree", "usage": "/tree [path]"},
    {"command": "get", "desc": "下载文件 Download a file", "usage": "/get <path>"},
]


def help_text() -> str:
    lines = ["AlphaPilot 命令 / commands:"]
    lines += [f"{spec['usage']} — {spec['desc']}" for spec in COMMAND_SPECS]
    lines.append("\n直接发送自然语言也可以 / plain natural language works too.")
    return "\n".join(lines)


@dataclass
class PlannedAction:
    action: str
    job_kind: str | None = None
    kwargs: dict[str, Any] | None = None
    job_id: str | None = None
    summary: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "job_kind": self.job_kind,
            "kwargs": self.kwargs or {},
            "job_id": self.job_id,
            "summary": self.summary,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
        }


class CommandError(ValueError):
    pass


def _boolish(value: str) -> bool | str:
    lower = value.strip().lower()
    if lower in {"true", "yes", "y", "1", "on"}:
        return True
    if lower in {"false", "no", "n", "0", "off"}:
        return False
    return value


def _coerce_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    bool_val = _boolish(value)
    if isinstance(bool_val, bool):
        return bool_val
    if value.lower() == "null":
        return None
    try:
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
    except Exception:
        pass
    if "," in value:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) > 1:
            return [_coerce_scalar(part) for part in parts]
    return value


def _parse_key_values(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    out: dict[str, Any] = {}
    for token in shlex.split(text):
        if "=" not in token:
            raise CommandError(f"参数需使用 key=value 或 JSON：{token}")
        key, value = token.split("=", 1)
        key = key.strip()
        if not key:
            raise CommandError("参数 key 不能为空")
        out[key] = _coerce_scalar(value)
    return out


def parse_kwargs(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CommandError(f"JSON 参数错误：{exc}") from exc
        if not isinstance(payload, dict):
            raise CommandError("JSON 参数必须是对象")
        return payload
    return _parse_key_values(text)


def parse_command(text: str) -> PlannedAction:
    text = text.strip()
    if not text:
        raise CommandError("命令为空")
    if not text.startswith("/"):
        return PlannedAction(action="plan_natural_language", summary=text, requires_confirmation=True)

    head, _, rest = text.partition(" ")
    cmd = head.split("@", 1)[0].lower()
    rest = rest.strip()

    if cmd == "/start":
        code = rest.split()[0] if rest else ""
        if code:
            return PlannedAction(action="pair", kwargs={"code": code}, summary="配对设备 / pair device")
        return PlannedAction(action="help", summary="显示命令帮助")
    if cmd == "/help":
        return PlannedAction(action="help", summary="显示命令帮助")
    if cmd == "/ls":
        return PlannedAction(action="fs_ls", kwargs={"path": rest}, summary="列出文件")
    if cmd == "/tree":
        return PlannedAction(action="fs_tree", kwargs={"path": rest}, summary="目录树")
    if cmd == "/cat":
        if not rest:
            raise CommandError("/cat 需要文件路径")
        return PlannedAction(action="fs_cat", kwargs={"path": rest}, summary="查看文件")
    if cmd == "/get":
        if not rest:
            raise CommandError("/get 需要文件路径")
        return PlannedAction(action="fs_get", kwargs={"path": rest}, summary="下载文件")
    if cmd == "/jobs":
        return PlannedAction(action="jobs", summary="列出最近任务")
    if cmd == "/status":
        return PlannedAction(action="status", job_id=rest or None, summary="查询任务状态")
    if cmd == "/log":
        if not rest:
            raise CommandError("/log 需要 job_id")
        return PlannedAction(action="log", job_id=rest, summary="读取任务日志")
    if cmd == "/result":
        if not rest:
            raise CommandError("/result 需要 job_id")
        return PlannedAction(action="result", job_id=rest, summary="读取任务结果")
    if cmd == "/cancel":
        if not rest:
            raise CommandError("/cancel 需要 job_id")
        return PlannedAction(action="cancel", job_id=rest, summary=f"取消任务 {rest}", risk_level="medium")
    if cmd == "/confirm":
        if not rest:
            raise CommandError("/confirm 需要确认 ID")
        return PlannedAction(action="confirm", job_id=rest, summary=f"确认执行 {rest}")
    if cmd == "/run":
        kind, sep, raw_kwargs = rest.partition(" ")
        if not sep and not raw_kwargs and kind:
            raw_kwargs = ""
        if not kind:
            raise CommandError("/run 需要 job kind，例如 /run mine {\"step_n\": 1}")
        return _job_action(kind, parse_kwargs(raw_kwargs), explicit=True)
    if cmd == "/mine":
        return _job_action("mine", parse_kwargs(rest), explicit=True)
    if cmd == "/backtest":
        tokens = shlex.split(rest) if rest else []
        kind = "factor_backtest"
        raw = rest
        if tokens and tokens[0] in {"factor", "strategy"}:
            kind = "strategy_backtest" if tokens[0] == "strategy" else "factor_backtest"
            raw = rest.split(None, 1)[1] if len(rest.split(None, 1)) > 1 else ""
        return _job_action(kind, parse_kwargs(raw), explicit=True)
    if cmd == "/data":
        return _job_action("data", parse_kwargs(rest), explicit=True)
    raise CommandError(f"不支持的命令：{cmd}")


def _job_action(kind: str, kwargs: dict[str, Any], *, explicit: bool) -> PlannedAction:
    if kind not in SAFE_JOB_KINDS:
        raise CommandError(f"不支持的 job kind：{kind}")
    action = PlannedAction(
        action="start_job",
        job_kind=kind,
        kwargs=kwargs,
        summary=f"启动 {kind}",
        risk_level="medium" if kind == "data" else "low",
        requires_confirmation=not explicit,
    )
    return action


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def authorize(message: InboundMessage, cfg: dict[str, Any] | None = None) -> tuple[bool, str]:
    cfg = cfg or load_notify_config()
    channel_cfg = cfg.get(message.channel, {}) if isinstance(cfg.get(message.channel), dict) else {}
    if not channel_cfg.get("receive_enabled"):
        return False, f"{message.channel} command receiver is disabled"
    allowed_users = set(_as_list(channel_cfg.get("allowed_user_ids")))
    if not allowed_users:
        return False, "no allowed user ids configured"
    if str(message.user_id) not in allowed_users:
        return False, f"user {message.user_id} is not allowed"
    allowed_chats = set(_as_list(channel_cfg.get("allowed_chat_ids")))
    if allowed_chats and str(message.chat_id) not in allowed_chats:
        return False, f"chat {message.chat_id} is not allowed"
    if channel_cfg.get("require_mention") and message.chat_type not in {"private", "p2p"}:
        bot_name = str(channel_cfg.get("bot_username") or "").strip().lstrip("@")
        if bot_name and f"@{bot_name}".lower() not in message.text.lower():
            return False, "group command requires bot mention"
    return True, "allowed"


def _load_pending(root: Path | None = None) -> dict[str, Any]:
    path = pending_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_pending(payload: dict[str, Any], root: Path | None = None) -> None:
    path = pending_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def create_pending(action: PlannedAction, message: InboundMessage, *, root: Path | None = None) -> dict[str, Any]:
    payload = _load_pending(root)
    pending_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    item = {
        "id": pending_id,
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat(timespec="seconds"),
        "channel": message.channel,
        "user_id": str(message.user_id),
        "chat_id": str(message.chat_id),
        "action": action.to_dict(),
    }
    payload[pending_id] = item
    _save_pending(payload, root)
    return item


def pop_pending(pending_id: str, message: InboundMessage, *, root: Path | None = None) -> dict[str, Any]:
    payload = _load_pending(root)
    item = payload.get(pending_id)
    if not isinstance(item, dict):
        raise CommandError(f"确认 ID 不存在：{pending_id}")
    expires_at = datetime.fromisoformat(str(item["expires_at"]))
    if expires_at < datetime.now(timezone.utc):
        payload.pop(pending_id, None)
        _save_pending(payload, root)
        raise CommandError(f"确认 ID 已过期：{pending_id}")
    if str(item.get("user_id")) != str(message.user_id):
        raise CommandError("只能由创建该计划的用户确认")
    payload.pop(pending_id, None)
    _save_pending(payload, root)
    return item


def _format_job(job: dict[str, Any]) -> str:
    return f"{job.get('job_id')} | {job.get('kind')} | {job.get('status')} | {job.get('result_summary') or '-'}"


def _add_allowed_user(channel: str, user_id: str) -> None:
    """Add *user_id* to a channel's allowlist + enable receiving, then persist."""
    cfg = public_notify_config(include_secrets=True)  # real secrets so save keeps them
    section = cfg.setdefault(channel, {})
    allowed = _as_list(section.get("allowed_user_ids"))
    if str(user_id) not in allowed:
        allowed.append(str(user_id))
    section["allowed_user_ids"] = allowed
    section["receive_enabled"] = True
    save_notify_config(cfg)


def _execute_pair(action: PlannedAction, message: InboundMessage) -> InboundReply:
    code = str((action.kwargs or {}).get("code") or "").strip()
    if not code:
        raise CommandError("缺少配对码 / missing pairing code")
    try:
        redeem_pair_code(code, message.channel)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    _add_allowed_user(message.channel, message.user_id)
    return InboundReply(
        text=(
            f"✅ 配对成功 / Paired. user_id={message.user_id} 已加入白名单。\n"
            "发送 /help 查看可用命令 / send /help for commands."
        ),
        data={"paired": True, "user_id": str(message.user_id)},
    )


def _execute_fs(action: PlannedAction, message: InboundMessage) -> InboundReply:
    path = str((action.kwargs or {}).get("path") or "").strip()
    try:
        if action.action == "fs_ls":
            return InboundReply(text=fsbrowse.ls(path))
        if action.action == "fs_tree":
            return InboundReply(text=fsbrowse.tree(path))
        if action.action == "fs_cat":
            return InboundReply(text=fsbrowse.read_text(path))
        if action.action == "fs_get":
            target = fsbrowse.file_for_download(path)
            return InboundReply(
                text=f"📎 发送文件 / sending: {target.name}",
                data={"document_path": str(target)},
            )
    except fsbrowse.FileBrowseError as exc:
        raise CommandError(str(exc)) from exc
    raise CommandError(f"不支持的文件动作：{action.action}")


def execute_action(action: PlannedAction, message: InboundMessage) -> InboundReply:
    if action.action == "help":
        return InboundReply(text=help_text())
    if action.action == "pair":
        return _execute_pair(action, message)
    if action.action in FILE_ACTIONS:
        return _execute_fs(action, message)
    if action.action == "jobs":
        rows = jobs.list_jobs()[:8]
        text = "\n".join(_format_job(row) for row in rows) if rows else "暂无任务"
        return InboundReply(text=text)
    if action.action == "status":
        if action.job_id:
            return InboundReply(text=json.dumps(jobs.get_job(action.job_id), ensure_ascii=False, indent=2)[:3500])
        rows = jobs.list_jobs()[:5]
        text = "\n".join(_format_job(row) for row in rows) if rows else "暂无任务"
        return InboundReply(text=text)
    if action.action == "log":
        assert action.job_id
        return InboundReply(text=jobs.read_log_tail(action.job_id, max_chars=3500) or "日志为空")
    if action.action == "result":
        assert action.job_id
        result = jobs.read_result(action.job_id)
        return InboundReply(text=json.dumps(result or {"result": None}, ensure_ascii=False, indent=2)[:3500])
    if action.action == "cancel":
        assert action.job_id
        job = jobs.cancel_job(action.job_id)
        return InboundReply(text=f"已取消：{_format_job(job)}")
    if action.action == "start_job":
        if not action.job_kind:
            raise CommandError("缺少 job kind")
        if action.job_kind not in SAFE_JOB_KINDS:
            raise CommandError(f"不支持的 job kind：{action.job_kind}")
        job = jobs.start_job(action.job_kind, action.kwargs or {})
        return InboundReply(text=f"已启动 job：{_format_job(job)}", data={"job": job})
    raise CommandError(f"不支持的动作：{action.action}")


def _history_preamble(history: list[dict[str, Any]] | None) -> str:
    """Render recent turns so the planner can resolve follow-ups like 'backtest it'."""
    if not history:
        return ""
    lines: list[str] = []
    for turn in history[-HISTORY_TURNS:]:
        user = str(turn.get("text") or "").strip()
        reply = str(turn.get("reply") or "").strip()
        if user:
            lines.append(f"User: {user}")
        if reply:
            lines.append(f"Assistant: {reply[:300]}")
    if not lines:
        return ""
    return "Recent conversation (context only):\n" + "\n".join(lines) + "\n\n"


def plan_natural_language(
    text: str,
    *,
    history: list[dict[str, Any]] | None = None,
    llm_factory: Callable[[], Any] | None = None,
) -> PlannedAction:
    system_prompt = (
        "You convert a user request into one AlphaPilot portal action. "
        "Return JSON only with keys: action, job_kind, kwargs, job_id, summary, risk_level, requires_confirmation. "
        "Allowed actions: start_job, jobs, status, log, result, cancel. "
        f"Allowed job_kind values: {sorted(SAFE_JOB_KINDS)}. "
        "Use the recent conversation only to resolve references in the current request. "
        "Do not invent required parameters. If insufficient info, use action=status and summary describing missing fields. "
        "Natural language actions that start/cancel tasks must set requires_confirmation=true."
    )
    prompt = _history_preamble(history) + f"Current request: {text}"
    try:
        if llm_factory is None:
            from alphapilot.adapters import get_llm

            llm_factory = get_llm
        resp = llm_factory().chat_completion(prompt, system_prompt=system_prompt, json_mode=True)
        from alphapilot.oai.llm_utils import extract_and_validate_llm_json

        payload = json.loads(extract_and_validate_llm_json(resp))
    except Exception as exc:  # noqa: BLE001
        raise CommandError(f"LLM 规划失败：{type(exc).__name__}: {exc}") from exc

    if not isinstance(payload, dict):
        raise CommandError("LLM 规划结果不是对象")
    action = str(payload.get("action") or "").strip()
    if action not in {"start_job", "jobs", "status", "log", "result", "cancel"}:
        raise CommandError(f"LLM 规划动作不受支持：{action}")
    job_kind = payload.get("job_kind")
    if job_kind:
        job_kind = str(job_kind)
        if job_kind not in SAFE_JOB_KINDS:
            raise CommandError(f"LLM 规划 job kind 不受支持：{job_kind}")
    kwargs = payload.get("kwargs") if isinstance(payload.get("kwargs"), dict) else {}
    requires = bool(payload.get("requires_confirmation", action not in QUERY_ACTIONS))
    if action in {"start_job", "cancel"}:
        requires = True
    return PlannedAction(
        action=action,
        job_kind=job_kind,
        kwargs=kwargs,
        job_id=str(payload.get("job_id") or "") or None,
        summary=str(payload.get("summary") or action),
        risk_level=str(payload.get("risk_level") or "medium"),
        requires_confirmation=requires,
    )


def _is_pair_attempt(text: str) -> bool:
    """True for ``/start <code>`` (robust to ``/start@bot``), matching parse_command."""
    parts = str(text).strip().split(maxsplit=1)
    if not parts:
        return False
    head = parts[0].split("@", 1)[0].lower()
    return head == "/start" and len(parts) > 1 and parts[1].strip() != ""


def dispatch_text(
    text: str,
    *,
    channel: str = "portal",
    user_id: str = "portal",
    chat_id: str = "portal",
    user_name: str | None = None,
    raw: dict[str, Any] | None = None,
    enforce_auth: bool = False,
    llm_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    cfg = load_notify_config()
    message = InboundMessage(
        channel=channel,
        text=text,
        user_id=str(user_id),
        chat_id=str(chat_id),
        user_name=user_name,
        raw=raw or {},
    )
    authorized, reason = (True, "portal") if not enforce_auth else authorize(message, cfg)
    ctx = CommandContext(message=message, notify_config=cfg, authorized=authorized, reason=reason)
    event: dict[str, Any] = {
        "channel": channel,
        "user_id": str(user_id),
        "chat_id": str(chat_id),
        "text": text,
        "authorized": authorized,
        "reason": reason,
    }
    try:
        # Pairing is the one path open to not-yet-authorized users: the one-time
        # code is the credential. Gate everything else on the allowlist (and don't
        # even parse it, to avoid leaking command structure to strangers).
        is_pair_attempt = _is_pair_attempt(text)
        if not ctx.authorized and not is_pair_attempt:
            raise CommandError(f"未授权：{ctx.reason}")
        action = parse_command(text)
        if action.action == "plan_natural_language":
            history = recent_turns(channel, chat_id, limit=HISTORY_TURNS)
            action = plan_natural_language(action.summary, history=history, llm_factory=llm_factory)
        if action.action == "confirm":
            pending = pop_pending(str(action.job_id), message)
            action_payload = pending.get("action", {})
            action = PlannedAction(
                action=str(action_payload.get("action")),
                job_kind=action_payload.get("job_kind"),
                kwargs=action_payload.get("kwargs") if isinstance(action_payload.get("kwargs"), dict) else {},
                job_id=action_payload.get("job_id"),
                summary=str(action_payload.get("summary") or ""),
                risk_level=str(action_payload.get("risk_level") or "medium"),
                requires_confirmation=False,
            )
        if action.requires_confirmation:
            pending = create_pending(action, message)
            reply = InboundReply(
                text=(
                    f"需要确认：{action.summary}\n"
                    f"动作：{action.action} {action.job_kind or ''}\n"
                    f"参数：{json.dumps(action.kwargs or {}, ensure_ascii=False)}\n"
                    f"确认执行：/confirm {pending['id']}"
                ),
                data={"pending": pending},
            )
        else:
            reply = execute_action(action, message)
        event.update({"action": action.to_dict(), "reply": reply.text, "ok": True, "data": reply.data})
        append_event(event)
        append_turn(channel, chat_id, {"text": text, "reply": reply.text, "action": action.to_dict(), "ok": True})
        return {"ok": True, "reply": reply.text, "action": action.to_dict(), "data": reply.data}
    except Exception as exc:  # noqa: BLE001
        event.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        append_event(event)
        append_turn(channel, chat_id, {"text": text, "reply": f"错误：{exc}", "ok": False})
        return {"ok": False, "reply": f"错误：{exc}", "error": f"{type(exc).__name__}: {exc}"}


def command_payload_status() -> dict[str, Any]:
    root = command_root()
    return {
        "root": str(root),
        "events": len(list(root.glob("events.jsonl"))) if root.exists() else 0,
        "pending_count": len(_load_pending(root)),
    }
