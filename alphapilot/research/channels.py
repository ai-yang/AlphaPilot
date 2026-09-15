"""Authenticated text commands adapt to the same typed research services."""
from __future__ import annotations

import json
import uuid
from contextvars import ContextVar

from .assets import AssetService
from .auth import Actor
from .catalog import Catalog
from .common import ResearchError, SCOPES, digest
from .models import JOB_ADAPTER
from .tasks import TaskService

_current: ContextVar[tuple | None] = ContextVar("research_command_context", default=None)


def command_spec(kind: str, kwargs: dict, tasks: TaskService, actor: Actor) -> dict:
    """Keep established text command spellings, validate against the v1 contract."""
    if "input" in kwargs:
        return JOB_ADAPTER.validate_python({"kind": kind, **kwargs}).model_dump(mode="json")
    data = dict(kwargs)
    notify = data.pop("notify", None)
    budget = data.pop("budget", {"timeout_seconds": 3600})
    catalog = Catalog(tasks.engine)
    assets = AssetService(tasks.engine, tasks.store)
    for unsafe in ("path", "factor_path", "model_pickle_path", "state_path", "qlib_dir", "qlib_data_dir",
                   "qlib_template_dir", "factor_data_dir", "data_dir", "output_dir", "source_path"):
        if data.get(unsafe):
            raise ResearchError("RESOURCE_ID_REQUIRED", f"Replace {unsafe} with a registered resource ID", 422)
        data.pop(unsafe, None)
    source = data.pop("source", "baostock_cn")
    source = {"baostock": "baostock_cn", "tushare": "tushare_cn"}.get(source, source)
    freq = data.pop("freq", "day")
    adjust = data.pop("adjust_mode", "backward" if freq == "day" else "none")
    if kind != "report_factor_extract":
        data.setdefault("dataset_id", f"{source}:{freq}:{adjust}")
    market = data.pop("market", None) or data.pop("instruments", None)
    if market and market != "all" and not data.get("stock_pool_id"):
        pool = next((p for p in assets.all("stock_pool", actor) if p["name"] == market or p["id"] == market), None)
        if not pool:
            raise ResearchError("NOT_FOUND", "Select a registered stock_pool_id", 404)
        data["stock_pool_id"] = pool["id"]
    template_name = data.pop("qlib_config_name", None)
    if template_name:
        template = next((t for t in catalog.templates(private=True) if t["config_name"] == template_name), None)
        if not template:
            raise ResearchError("NOT_FOUND", "Select a registered template_id", 404)
        data["template_id"] = template["template_id"]
    params = data.pop("yaml_params", None)
    if params:
        data["parameters"] = json.loads(params) if isinstance(params, str) else params
    if kind == "mine" and "step_n" in data:
        data["max_steps"] = data.pop("step_n")
    if kind in {"strategy_backtest", "daily_signals"} and "strategy_name" in data:
        name = data.pop("strategy_name")
        row = next((r for r in assets.all("strategy", actor) if r["name"] == name), None)
        if not row:
            raise ResearchError("NOT_FOUND", "Strategy asset not found", 404)
        data["strategy_id"] = row["id"]
    if kind == "daily_signals" and "session" in data:
        name = data.pop("session")
        row = next((r for r in assets.all("signal_session", actor) if r["name"] == name), None)
        if not row:
            raise ResearchError("NOT_FOUND", "Signal session not found", 404)
        data["session_id"] = row["id"]
        data.setdefault("mode", "advance")
    if kind == "factor_backtest" and "factor_names" in data:
        names = data.pop("factor_names")
        if isinstance(names, str):
            names = names.split(",")
        rows = {r["name"]: r for r in assets.all("factor", actor)}
        if any(name not in rows for name in names):
            raise ResearchError("NOT_FOUND", "Factor not found", 404)
        data["factor_source"] = {"type": "library", "factor_ids": [rows[name]["id"] for name in names]}
    return JOB_ADAPTER.validate_python({"kind": kind, "input": data, "budget": budget, "notify": notify}).model_dump(mode="json")


def execute_action(action, message, actor: Actor | None = None):
    from alphapilot.systems.notify.inbound import InboundReply
    active = _current.get()
    if active:
        actor, tasks, key = active
    else:
        actor = actor or Actor(f"{message.channel}:{message.user_id}", SCOPES, message.channel, request_id=uuid.uuid4().hex)
        tasks = TaskService()
        raw = message.raw or {}
        message_id = raw.get("update_id") or raw.get("message_id") or raw.get("event_id")
        key = f"channel:{message.channel}:{message.chat_id}:{message_id}" if message_id else uuid.uuid4().hex
    actor.require("research:read")
    if action.action in {"jobs", "status"}:
        data = tasks.get(action.job_id, actor) if action.job_id else tasks.list(actor, limit=8)
    elif action.action == "log":
        tasks.get(action.job_id, actor)
        path = tasks.store.root / action.job_id / "run.log"
        cursor = max(0, path.stat().st_size - 3500) if path.exists() else 0
        data = tasks.logs(action.job_id, actor, cursor=cursor, limit=3500)
    elif action.action == "result":
        data = tasks.read_result(action.job_id, actor)
    elif action.action == "cancel":
        data = tasks.cancel(action.job_id, actor)
    elif action.action == "start_job":
        request = command_spec(action.job_kind, action.kwargs or {}, tasks, actor)
        data = tasks.submit(request, actor, key)
    else:
        raise ResearchError("UNKNOWN_COMMAND", "Unsupported research command", 422)
    return InboundReply(text=json.dumps(data, ensure_ascii=False, indent=2)[:3500], data=data)


def dispatch_authenticated(text: str, actor: Actor, tasks: TaskService, idempotency_key: str) -> dict:
    from alphapilot.systems.notify.commands import dispatch_text
    token = _current.set((actor, tasks, idempotency_key))
    try:
        return dispatch_text(text, channel="portal", user_id=actor.client_id, chat_id=actor.client_id,
                             enforce_auth=False, actor=actor)
    finally:
        _current.reset(token)
