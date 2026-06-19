"""Channel base + capabilities + shared renderers.

A channel is *transport-only*: given a portable :class:`Message`, render it and
deliver it. Capabilities let the fan-out degrade gracefully (e.g. a channel
without inline buttons falls back to appending action links as text).
"""

from __future__ import annotations

import html
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from alphapilot.systems.notify.models import Message


@dataclass(frozen=True)
class ChannelCapabilities:
    supports_actions: bool = False  # native inline buttons / cards
    can_receive: bool = False  # Phase 2 inbound (long-poll / webhook)


class BaseChannel(ABC):
    """Transport-only delivery for one channel."""

    name: str = ""
    capabilities: ChannelCapabilities = ChannelCapabilities()

    def __init__(self, conf: dict[str, Any] | None = None) -> None:
        self.conf = conf or {}

    @abstractmethod
    def is_configured(self) -> bool:
        """True when this channel is enabled and has the credentials it needs."""

    @abstractmethod
    def send(self, message: Message) -> None:
        """Render and deliver *message*. Raise on failure (caller isolates)."""


# --------------------------------------------------------------------------- #
# Shared renderers (channels pick the format that fits their transport)
# --------------------------------------------------------------------------- #
def render_plaintext(message: Message) -> str:
    """Plain text: ``emoji title`` + body + ``key: value`` rows + action links."""
    lines: list[str] = [f"{message.emoji()} {message.title}".strip()]
    if message.body:
        lines += ["", message.body]
    if message.fields:
        lines.append("")
        lines += [f"{k}: {v}" for k, v in message.fields.items()]
    links = [a for a in message.actions if a.kind == "link" and a.value]
    if links:
        lines.append("")
        lines += [f"{a.label}: {a.value}" for a in links]
    return "\n".join(lines)


def render_html(message: Message) -> str:
    """Minimal HTML used by email and Telegram (HTML parse mode)."""
    esc = html.escape
    parts: list[str] = [f"<b>{esc(message.emoji())} {esc(message.title)}</b>"]
    if message.body:
        parts.append(f"<p>{esc(message.body)}</p>")
    if message.fields:
        rows = "".join(
            f"<tr><td><b>{esc(k)}</b></td><td>{esc(str(v))}</td></tr>" for k, v in message.fields.items()
        )
        parts.append(f"<table>{rows}</table>")
    links = [a for a in message.actions if a.kind == "link" and a.value]
    if links:
        parts.append(
            " ".join(f'<a href="{esc(a.value)}">{esc(a.label)}</a>' for a in links)
        )
    return "\n".join(parts)


def render_telegram_html(message: Message) -> str:
    """Telegram-safe HTML for the message text.

    Telegram's HTML parse mode allows only a small inline tag set (b/i/u/s/a/
    code/pre/blockquote); block tags like ``<p>`` or ``<table>`` raise
    ``400 Bad Request: can't parse entities``. So we lay the message out with
    newlines + bold labels only, and leave link actions to the inline keyboard
    the channel renders separately.
    """
    esc = html.escape
    header = f"{message.emoji()} {message.title}".strip()
    lines: list[str] = [f"<b>{esc(header)}</b>"]
    if message.body:
        lines += ["", esc(message.body)]
    if message.fields:
        lines.append("")
        lines += [f"<b>{esc(k)}</b>: {esc(str(v))}" for k, v in message.fields.items()]
    return "\n".join(lines)
