"""Channel-agnostic notification model.

Following openclaw's "channels are transport-only" rule: the core produces a
portable :class:`Message` (title / body / fields / typed actions) and each
channel renders it to its own native format. Business logic never builds
channel-specific payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NotifyLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


# Level -> emoji prefix, reused by every channel's renderer.
LEVEL_EMOJI = {
    NotifyLevel.INFO: "ℹ️",
    NotifyLevel.SUCCESS: "✅",
    NotifyLevel.WARNING: "⚠️",
    NotifyLevel.ERROR: "❌",
}


@dataclass
class MessageAction:
    """A portable action a channel may render natively.

    ``kind="link"`` is the only one used in Phase 1 (renders as a button/URL).
    ``command``/``approve``/``deny`` are reserved for Phase 2 inbound; channels
    without inline-action support degrade to plain text.
    """

    label: str
    value: str = ""
    kind: str = "link"  # link | command | approve | deny


@dataclass
class Message:
    """A channel-agnostic notification."""

    title: str
    body: str = ""
    level: NotifyLevel = NotifyLevel.INFO
    fields: dict[str, str] = field(default_factory=dict)  # label -> value rows
    actions: list[MessageAction] = field(default_factory=list)
    source: dict[str, str] = field(default_factory=dict)  # job_id / kind / etc. (context)

    def emoji(self) -> str:
        return LEVEL_EMOJI.get(self.level, "")
