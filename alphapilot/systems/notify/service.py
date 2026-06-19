"""Notification system: fan-out send with per-channel failure isolation.

The core ``send`` is a plain module function (no engine needed), so a spawned
job worker can notify on completion without rebuilding the kernel.
``NotificationSystem`` is a thin :class:`BaseSystem` wrapper for engine access.
"""

from __future__ import annotations

from typing import Any

from alphapilot.kernel.base import BaseSystem
from alphapilot.log import logger
from alphapilot.systems.notify.channels import CHANNEL_CLASSES
from alphapilot.systems.notify.channels.base import BaseChannel
from alphapilot.systems.notify.config import load_notify_config
from alphapilot.systems.notify.models import Message, NotifyLevel

_KIND_LABEL = {
    "mine": "因子挖掘 Factor Mining",
    "factor_backtest": "因子回测 Factor Backtest",
    "strategy_backtest": "策略回测 Strategy Backtest",
    "data": "数据任务 Data",
}


def _build_channels(cfg: dict[str, Any] | None = None) -> list[BaseChannel]:
    cfg = cfg if cfg is not None else load_notify_config()
    return [cls(cfg.get(name, {})) for name, cls in CHANNEL_CLASSES.items()]


def configured_channel_names() -> list[str]:
    return [c.name for c in _build_channels() if c.is_configured()]


def send(message: Message) -> dict[str, str]:
    """Deliver *message* to every configured channel. Returns ``{channel: 'ok'|error}``.

    Each channel is isolated: one failure neither aborts the others nor raises
    to the caller (a notification must never break the task that triggered it).
    """
    results: dict[str, str] = {}
    for channel in _build_channels():
        if not channel.is_configured():
            continue
        try:
            channel.send(message)
            results[channel.name] = "ok"
        except Exception as exc:  # noqa: BLE001 - isolate; notify is best-effort
            logger.warning(f"[notify] {channel.name} send failed: {exc}")
            results[channel.name] = f"{type(exc).__name__}: {exc}"
    return results


def test_send(channel: str | None = None) -> dict[str, str]:
    """Send a test message to one channel (or all). Reports per-channel status."""
    message = Message(
        title="AlphaPilot 通知测试 / Test",
        body="If you can read this, the channel is configured correctly.",
        level=NotifyLevel.SUCCESS,
        source={"kind": "test"},
    )
    results: dict[str, str] = {}
    for ch in _build_channels():
        if channel and ch.name != channel:
            continue
        if not ch.is_configured():
            results[ch.name] = "not configured"
            continue
        try:
            ch.send(message)
            results[ch.name] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[ch.name] = f"{type(exc).__name__}: {exc}"
    return results


def _summarize(result: Any) -> str:
    if result is None:
        return "—"
    if isinstance(result, dict):
        keys = ", ".join(list(result.keys())[:8])
        return keys or "dict"
    if isinstance(result, (list, tuple, set)):
        return f"{len(result)} items"
    text = str(result)
    return text if len(text) <= 400 else text[:397] + "..."


def build_job_message(
    *,
    kind: str,
    job_id: str,
    status: str,
    result: Any = None,
    error: Any = None,
    kwargs: dict[str, Any] | None = None,
    job_dir: Any = None,
) -> Message:
    """Compose a concise completion notification for a finished background job."""
    ok = status == "succeeded"
    label = _KIND_LABEL.get(kind, kind)
    title = f"{label} {'完成 Done' if ok else '失败 Failed'}"
    fields: dict[str, str] = {"任务 Type": label, "状态 Status": status, "Job ID": job_id}
    for key in ("action", "source", "step_n", "scenario"):
        value = (kwargs or {}).get(key)
        if value not in (None, ""):
            fields[key] = str(value)
    if job_dir is not None:
        fields["Log"] = str(job_dir)
    if ok:
        body = f"结果摘要 / Result: {_summarize(result)}"
    else:
        body = f"错误 / Error: {error}" if error else "任务未成功完成。"
    return Message(
        title=title,
        body=body,
        level=NotifyLevel.SUCCESS if ok else NotifyLevel.ERROR,
        fields=fields,
        source={"kind": kind, "job_id": job_id},
    )


class NotificationSystem(BaseSystem):
    """Engine-facing wrapper around the module-level notify functions."""

    name = "notify"

    def send(self, message: Message) -> dict[str, str]:
        return send(message)

    def test_send(self, channel: str | None = None) -> dict[str, str]:
        return test_send(channel)

    def configured_channels(self) -> list[str]:
        return configured_channel_names()
