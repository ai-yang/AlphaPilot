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
    "daily_signals": "每日交易信号 Daily Signals",
    "data": "数据任务 Data",
}

# Cap per-section rows so a large universe never blows past a channel's size limit.
_MAX_NOTIFY_ROWS = 40


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


def _fmt_money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_shares(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _trade_line(row: dict[str, Any]) -> str:
    """``600000.SH  1,000 股 @ 12.34`` (amount / price optional)."""
    bits = [str(row.get("instrument", "?"))]
    amount = row.get("amount")
    price = row.get("price")
    if amount not in (None, ""):
        bits.append(f"{_fmt_shares(amount)} 股")
    if price not in (None, "") and str(price).lower() != "nan":
        bits.append(f"@ {_fmt_money(price)}")
    return "  ".join(bits)


def _holding_line(row: dict[str, Any]) -> str:
    line = _trade_line(row)
    amount, price = row.get("amount"), row.get("price")
    try:
        if amount not in (None, "") and price not in (None, "") and str(price).lower() != "nan":
            line += f"  ≈ {_fmt_money(float(amount) * float(price))}"
    except (TypeError, ValueError):
        pass
    return line


def _section(title: str, rows: list[dict[str, Any]], render) -> str:  # noqa: ANN001
    shown = [f"· {render(r)}" for r in rows[:_MAX_NOTIFY_ROWS]]
    if len(rows) > _MAX_NOTIFY_ROWS:
        shown.append(f"… (+{len(rows) - _MAX_NOTIFY_ROWS})")
    return f"{title}\n" + "\n".join(shown)


def build_daily_signals_message(
    *,
    result: dict[str, Any],
    job_id: str,
    kwargs: dict[str, Any] | None = None,
    job_dir: Any = None,
) -> Message:
    """Rich notification listing today's positions and buy/sell trades.

    ``result`` is the ``daily_trade.summarize`` dict: ``date / new_cash /
    n_positions / trades[] / holdings[] / top_scores[] / info``.
    """
    trades = result.get("trades") or []
    holdings = result.get("holdings") or []
    buys = [t for t in trades if str(t.get("status_label")) == "买入"]
    sells = [t for t in trades if str(t.get("status_label")) == "卖出"]
    strategy = (kwargs or {}).get("strategy_name") or "手动 manual"

    fields: dict[str, str] = {
        "日期 Date": str(result.get("date", "—")),
        "策略 Strategy": str(strategy),
        "持仓数 Positions": str(result.get("n_positions", len(holdings))),
        "买入 Buys": str(len(buys)),
        "卖出 Sells": str(len(sells)),
    }
    if result.get("new_cash") is not None:
        fields["现金 Cash"] = _fmt_money(result.get("new_cash"))
    if job_dir is not None:
        fields["Log"] = str(job_dir)

    parts: list[str] = []
    if buys:
        parts.append(_section(f"🟢 买入 Buy ({len(buys)})", buys, _trade_line))
    if sells:
        parts.append(_section(f"🔴 卖出 Sell ({len(sells)})", sells, _trade_line))
    if not buys and not sells:
        parts.append("今日无调仓 / No rebalance today.")
    if holdings:
        parts.append(_section(f"📋 持仓 Holdings ({len(holdings)})", holdings, _holding_line))

    return Message(
        title="每日交易信号 Daily Signals",
        body="\n\n".join(parts),
        level=NotifyLevel.SUCCESS,
        fields=fields,
        source={"kind": "daily_signals", "job_id": job_id},
    )


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
    # Daily signals get a dedicated, detail-rich layout (positions + trades).
    if kind == "daily_signals" and ok and isinstance(result, dict):
        return build_daily_signals_message(
            result=result, job_id=job_id, kwargs=kwargs, job_dir=job_dir
        )
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
